import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
TEXT2SQL_AGENT_URL = os.getenv("TEXT2SQL_AGENT_URL", "http://localhost:8080")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://dungvu:dungvu@localhost:5432/banking_mcp_test")
CURRENT_BANK_CODE = os.getenv("CURRENT_BANK_CODE", "SHB")
MOCK_OTP_CODE = os.getenv("MOCK_OTP_CODE", "123456")
LOG_DIR = Path(os.getenv("LOG_DIR", "/home/ubuntu/workspace/logs"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Langfuse
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
