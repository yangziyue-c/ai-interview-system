# config.py
import os
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    print("⚠️ 警告: 请在项目根目录创建 .env 文件，并设置 DEEPSEEK_API_KEY=你的密钥")

API_URL = "https://api.deepseek.com/v1/chat/completions"

PROMPTS = {
    # 保留原有 PROMPTS（可能其他接口用到）
}

DEFAULT_POSITION = "backend"   # 根据实际调整
MAX_ROUNDS = 7
MAX_MINUTES = 10

# 新增：兜底问题
FALLBACK_QUESTION = "请介绍一下你的项目经历。"