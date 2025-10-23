import datetime
import os
import time  # <--- 1. 導入 time 模組
from src.chatgpt import ChatGPT, DALLE
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

# --- Gemini API 設定開始 ---
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

# --- [修改] Gemini 模型設定 (加入系統提示詞和範例) ---

# ！！！！！！！！！！！！！！！！！！！！！！！！！！！！
# ！！！ 這就是你設定「原則」和「學習範例」的地方 ！！！
# ！！！！！！！！！！！！！！！！！！！！！！！！！！！！
YOUR_SYSTEM_PROMPT = """
# === 你的角色 ===
(這裡填寫你希望 AI 扮演的角色，例如：你是一個風趣、健談的台灣男生...)

# === 聊天原則 (你希望他遵守的) ===
1. 每一句話都要風趣幽默。
2. 主動提出開放式問題。
3. 如果對方的個人簡介有內容，優先從簡介中找話題。
4. 絕對不要使用粗俗的詞語。
5. (新增更多你的原則...)

# === 學習範例 (教 AI 如何回應) ===
以下是 AI 應該如何根據[對話紀錄]和[你的個人簡介]來生成 [Sender] 回應的範例。

---
範例1: (開場白)
[對話紀錄]
(無對話紀錄)
[你的個人簡介]
職業：工程師
興趣：爬山、看電影
[Sender]
嗨！我看到你的個人簡介，你也喜歡爬山嗎？我上週末才剛去了七星山！

---
範例2: (回覆對方)
[對話紀錄]
對方: 你住哪裡？
[你的個人簡介]
職業：工程師
住在：台北
[Sender]
我住在台北市區，你呢？聽起來我們可能蠻近的。

---
範例3: (幽默回應)
[對話紀錄]
對方: hi
[你的個人簡介]
興趣：看電影、冷笑話
[Sender]
Hi! 你的 "hi" 真是言簡意賅，是在測試我會不會說更多字嗎？哈哈。
"""
# ！！！！！！！！！！！！！！！！！！！！！！！！！！！！
# ！！！ 提示詞設定結束 ！！！
# ！！！！！！！！！！！！！！！！！！！！！！！！！！！！


try:
    gemini_model = genai.GenerativeModel(
        model_name="gemini-2.5-pro-latest",
        system_instruction=YOUR_SYSTEM_PROMPT
    )
    
    # 設定模型的生成參數 (例如溫度)
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
            response = get_gemini_response(content)  # 使用 Gemini 函數
            if response:
                response = cc.convert(response)
                
                # --- 2. 模擬人類延遲 ---
                logger.info(f'AI 已生成回應，等待 3 秒後發送...')
                time.sleep(3) # 執行緒暫停 3 秒
                # -----------------------

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


