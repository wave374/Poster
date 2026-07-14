import os

# ---- Telegram credentials (fill these in) ----
API_ID = int(os.environ.get("API_ID", "12345"))
API_HASH = os.environ.get("API_HASH", "your_api_hash_here")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token_here")

# Only these Telegram user IDs may use the bot. Leave empty to allow everyone.
ADMINS = [int(x) for x in os.environ.get("ADMINS", "").split() if x.strip().isdigit()]

# ---- Default poster branding (all changeable per-poster via caption, see README) ----
DEFAULT_LOGO_TEXT = os.environ.get("LOGO_TEXT", "Animerulz")
DEFAULT_CHANNEL_TAG = os.environ.get("CHANNEL_TAG", "@YourChannel")
DEFAULT_JOIN_TEXT = os.environ.get("JOIN_TEXT", "Join Channel")
DEFAULT_SMALL_TEXT = os.environ.get("DEFAULT_SMALL_TEXT", "WELCOME")
DEFAULT_BIG_TEXT = os.environ.get("DEFAULT_BIG_TEXT", "OTAKU'S")

SESSION_NAME = "poster_bot"
