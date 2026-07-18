# Deploying to Koyeb

`render.yaml` is ignored by Koyeb — this repo now uses a `Dockerfile` instead, which Koyeb builds natively (no buildpack guessing needed).

## Steps

1. **Revoke the old bot token.** It was hardcoded in the original `bot.py` and should be treated as leaked. Open a chat with **@BotFather** → `/revoke` (or `/token`) on your bot → generate a new token.

2. **Push this folder to a GitHub repo** (Koyeb deploys from Git or Docker Hub).

3. **Create the Koyeb service:**
   - New Service → GitHub → select the repo
   - Builder: **Dockerfile** (auto-detected since one exists now)
   - Instance: smallest/free eco instance is fine — this is a lightweight polling bot, not a web server
   - Port: `8000` (matches the `EXPOSE`/`ENV PORT` in the Dockerfile; Koyeb will route health checks here)

4. **Set environment variables/secrets** in the Koyeb dashboard (Service → Settings → Environment variables):
   - `BOT_TOKEN` — your new token from step 1 (mark as *secret*)
   - `OWNER_ID` — your numeric Telegram user ID (mark as *secret* or plain env var)

5. Deploy. Koyeb will build the Docker image, start the container, and `bot.py`'s built-in dummy HTTP server will satisfy Koyeb's health check while `run_polling()` handles Telegram updates in the background.

## Notes on persistence

`_users` (in `bot.py`) and per-user brand settings live in memory (`ctx.bot_data`), and `users.json` on disk isn't reloaded/saved anywhere in the code shown. Any redeploy, restart, or scale-to-zero event on Koyeb will wipe this data — same as it would have on Render. If you need durability, swap this for a small external store (e.g., a free Postgres/Redis instance, or even periodically writing `users.json` to a mounted volume if Koyeb persistent volumes are enabled on your plan).
