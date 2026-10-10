# Telegram Hosting Bot

Users upload `.py` / `.js` scripts or `.zip` archives and the bot runs them 24/7.

## Features
- Welcome screen: user id, username, status (Free / Premium / Owner), files used
- Upload `.py`, `.js`, `.zip` (auto-detects main.py / bot.py / index.js ...)
- Auto install `requirements.txt` and `package.json`
- Check Files -> Run / Stop / Restart / Logs / Delete
- Free limit = 1 file, Premium limit = 10 (change in .env)
- Bot Speed, Statistics, Buy Premium, Contact Owner, Updates Channel
- Scripts auto-start again after the bot restarts
- Admin: /addpremium /removepremium /ban /unban /broadcast /admin

## Setup
1. Make a bot with @BotFather and copy the token
2. `cp .env.example .env` and fill BOT_TOKEN, OWNER_ID, OWNER_USERNAME, UPDATES_CHANNEL
3. `pip install -r requirements.txt`
4. Node scripts support ke liye `node` + `npm` install hona chahiye
5. `python bot.py`

### Docker (recommended)
```
docker build -t hosting-bot .
docker run -d --restart always --env-file .env -v $(pwd)/data:/app/data hosting-bot
```
(`--env-file` use karo, `.env` file image me copy mat karo -> add `.env` in `.dockerignore`.)

### Replit / VPS
Token ko Secrets / environment variables me rakho. Linux required (process groups, resource limits).

## Security (important)
Hosted scripts run on YOUR server with the same OS user as the bot.
- Bot token is NOT passed to scripts (clean env), memory + file-size limits are applied.
- But scripts can still read other files of the same user. So run the bot inside Docker / a separate low-privilege VPS,
  never keep other important data on that machine, and give access only to people you trust (use /ban when needed).
