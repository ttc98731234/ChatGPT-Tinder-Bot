import datetime
import os
import google.generativeai as genai  # <--- [新增] 
# from src.chatgpt import ChatGPT, DALLE  # <--- [移除]
# from src.models import OpenAIModel     # <--- [移除]
from src.tinder import TinderAPI
from src.dialog import Dialog
from src.logger import logger
from opencc import OpenCC

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn
load_dotenv('.env')


# --- [移除] OpenAI 設定 ---
# models = OpenAIModel(api_key=os.getenv('OPENAI_API'), model_engine=os.getenv('OPENAI_MODEL_ENGINE'))
# chatgpt = ChatGPT(models)
# dalle = DALLE(models) # dalle 也先移除

# --- [新增] Gemini API 設定開始 ---
try:
    # ！！！注意：你需要在 .env 或部署平台上設定 'GOOGLE_API_KEY' ！！！
    api_key = os.getenv("GOOGLE_API_KEY") 
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not found in environment variables.")
    genai.configure(api_key=api_key)
except Exception as e:
    logger.error(f"Failed to configure Gemini API: {e}")
    exit()

# --- [新增] Gemini 模型設定 ---
try:
    gemini_model = genai.GenerativeModel(
        model_name="gemini-1.5-pro-latest"
        # 注意：我們假設 'dialog.generate_input' 會產生完整的上下文提示詞
        # 因此我們不在這裡設定 system_instruction
    )
    generation_config = genai.types.GenerationConfig(
        temperature=0.7, # 你可以調整溫度
    )
except Exception as e:
    logger.error(f"Failed to initialize Gemini model: {e}")
    exit()

# --- [新增] Gemini 回應函數 ---
def get_gemini_response(prompt_text: str) -> str | None:
    """
    Get completion from Google Gemini API
    """
    try:
        # 假設 'prompt_text' (來自 dialog.generate_input) 
        # 已經是 Gemini 可以理解的完整提示詞字串
        response = gemini_model.generate_content(
            prompt_text,
            generation_config=generation_config
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        try:
            # 嘗試記錄更詳細的錯誤 (例如安全阻擋)
            if response and response.prompt_feedback:
                 logger.error(f"Prompt Feedback (Safety/Block): {response.prompt_feedback}")
        except Exception:
            pass
        return None
# --- Gemini API 設定結束 ---


dialog = Dialog()
app = FastAPI()
scheduler = AsyncIOScheduler()
cc = OpenCC('s2t')
TINDER_TOKEN = os.getenv('TINDER_TOKEN')


@scheduler.scheduled_job("cron", minute='*/5', second=0, id='reply_messages')
def reply_messages():
    tinder_api = TinderAPI(TINDER_TOKEN)
    profile = tinder_api.profile()

    user_id = profile.id

    for match in tinder_api.matches(limit=50):
        chatroom = tinder_api.get_messages(match.match_id)
        lastest_message = chatroom.get_lastest_message()
        if lastest_message:
            if lastest_message.from_id == user_id:
                from_user_id = lastest_message.from_id
                to_user_id = lastest_message.to_id
                last_message = 'me'
            else:
                from_user_id = lastest_message.to_id
                to_user_id = lastest_message.from_id
                last_message = 'other'
            sent_date = lastest_message.sent_date
            if last_message == 'other' or (sent_date + datetime.timedelta(days=1)) < datetime.datetime.now():
                content = dialog.generate_input(from_user_id, to_user_id, chatroom.messages[::-1])
                
                # --- [修改] 呼叫 Gemini ---
                # response = chatgpt.get_response(content) # <--- [舊的]
                response = get_gemini_response(content)  # <--- [新的]
                
                if response:
                    response = cc.convert(response)
                    if response.startswith('[Sender]'):
                        chatroom.send(response[8:], from_user_id, to_user_id)
                    else:
                        chatroom.send(response, from_user_id, to_user_id)
                logger.info(f'Content: {content}, Reply: {response}')


@app.on_event("startup")
async def startup():
    scheduler.start()


@app.on_event("shutdown")
async def shutdown():
    scheduler.remove_job('reply_messages')


@app.get("/")
async def root():
    return {"message": "Hello World"}


if __name__ == "__main__":
    uvicorn.run('main:app', host='0.0.0.0', port=8080)
