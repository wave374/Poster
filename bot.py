import os
from pyrogram import Client

from config import API_ID, API_HASH, BOT_TOKEN, ADMINS, SESSION_NAME
from config import DEFAULT_LOGO_TEXT, DEFAULT_CHANNEL_TAG, DEFAULT_JOIN_TEXT, DEFAULT_SMALL_TEXT, DEFAULT_BIG_TEXT
from helper.settings_store import load_settings

os.makedirs("downloads", exist_ok=True)
os.makedirs("outputs", exist_ok=True)

app = Client(
    SESSION_NAME,
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins={"root": "plugins"},
)

app.admins = ADMINS  # empty list = everyone allowed
app.poster_settings = load_settings({
    "logo_text": DEFAULT_LOGO_TEXT,
    "channel_tag": DEFAULT_CHANNEL_TAG,
    "join_text": DEFAULT_JOIN_TEXT,
    "small_text": DEFAULT_SMALL_TEXT,
    "big_text": DEFAULT_BIG_TEXT,
    "theme": "auto",
})

if __name__ == "__main__":
    print("Starting Anime Poster Bot...")
    app.run()
