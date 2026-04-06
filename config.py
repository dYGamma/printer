import os

# Telegram Bot Token
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Allowed User IDs (comma separated string)
ALLOWED_USERS_ENV = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = [int(uid.strip()) for uid in ALLOWED_USERS_ENV.split(",") if uid.strip().isdigit()]

# Temporary directory for downloads/scans
TEMP_DIR = os.path.join(os.getcwd(), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)
