# Anime Poster Bot

A Telegram bot that turns any photo into a branded "Animerulz"-style poster:
dark cinematic gradient, corner ✕ marks, logo, "Join Channel" pill, rotated
channel tag, dotted accents, and a glowing two-line headline — auto-colored
to match the photo, or set manually.

## How it works

1. Send the bot a photo.
2. It downloads it, runs it through `poster/generator.py` (pure Pillow — no
   AI image generation, so it's instant and free to run), and sends back a
   1280x720 poster.
3. Optionally control the text/theme per-poster via the photo's caption:

   ```
   small text | BIG TEXT | theme
   ```

   Example caption: `WELCOME | OTAKU'S | purple`

   - Leave the theme out (or write `auto`) to let the bot pick a glow color
     from the photo's own dominant vivid hue.
   - Available themes: `red`, `pink`, `purple`, `blue`, `cyan`, `orange`,
     `gold`, `green`.
   - No caption at all → uses your configured defaults.

## Setup

```bash
pip install -r requirements.txt
```

Set your credentials as environment variables (or edit `config.py` directly):

```bash
export API_ID=123456
export API_HASH=your_api_hash
export BOT_TOKEN=your_bot_token
export ADMINS="6497757690 7115720502"   # space-separated Telegram user IDs; leave unset = open to everyone
export LOGO_TEXT="Animerulz"
export CHANNEL_TAG="@New_Anime_Hindi_Dubbed_32"
export JOIN_TEXT="Join Channel"
```

Run it:

```bash
python3 bot.py
```

## Bot commands

| Command | Who | What it does |
|---|---|---|
| `/start` | anyone | shows usage + current defaults |
| `/setlogo <text>` | admins | change the logo text (top-left) |
| `/settag <@channel>` | admins | change the vertical channel tag (right edge) |
| `/setjoin <text>` | admins | change the "Join Channel" pill text |
| `/settheme <name\|auto>` | admins | change the default glow color |

Settings persist across restarts in `settings.json` (created automatically).

## Project structure

```
anime-poster-bot/
├── bot.py                     # entry point
├── config.py                  # credentials & defaults (env-var driven)
├── settings.json              # runtime settings (auto-created)
├── requirements.txt
├── poster/
│   ├── generator.py           # core poster rendering (Pillow)
│   ├── color_utils.py         # auto theme/color detection from the photo
│   └── assets/fonts/          # bundled Poppins fonts
├── plugins/
│   └── poster_handler.py      # Telegram handlers (auto-loaded by Pyrogram)
└── helper/
    └── settings_store.py      # tiny JSON settings persistence
```

## Notes on deployment (Render, etc.)

- No `ffmpeg`, no GPU, no external API needed — pure Pillow, so it runs
  anywhere Python does and is fast (well under a second per poster).
- Fonts are bundled in `poster/assets/fonts/` so you don't depend on
  system fonts being installed on the host.
- If you want the exact same house style across every poster (rather than
  auto-detected colors), set `/settheme <your_color>` once and every future
  poster will use it unless overridden per-caption.
