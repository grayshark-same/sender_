import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
TELEMETR_API_KEY: str = os.getenv("TELEMETR_API_KEY", "")
TELEMETR_SESSION: str = os.getenv("TELEMETR_SESSION", "")

# Несколько админов через запятую: 123456789,987654321
ADMIN_IDS: set[int] = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "0")).split(",")
    if x.strip().isdigit()
}
