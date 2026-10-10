import asyncio
import functools
import html
import logging
import math
import re
import shutil
import time
from pathlib import Path

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
    ReplyKeyboardMarkup, BotCommand, Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

import config
import database as db
import runner

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger("hosting-bot")
START_TIME = time.time()
HTML = ParseMode.HTML

BTN_UPDATES = "📢 Updates Channel"
BTN_UPLOAD = "📥 Upload File"
BTN_FILES = "📂 Check Files"
BTN_SPEED = "⚡ Bot Speed"
BTN_STATS = "📊 Statistics"
BTN_PREMIUM = "💎 Buy Premium"
BTN_OWNER = "📞 Contact Owner"

MAIN_KB = ReplyKeyboardMarkup(
    [[KeyboardButton(BTN_UPDATES)],
     [KeyboardButton(BTN_UPLOAD), KeyboardButton(BTN_FILES)],
     [KeyboardButton(BTN_SPEED), KeyboardButton(BTN_STATS)],
     [KeyboardButton(BTN_PREMIUM)],
     [KeyboardButton(BTN_OWNER)]],
    resize_keyboard=True,
)


# ======================= helpers =======================
def esc(s):
    return html.escape(str(s), quote=False)


def is_owner(uid):
    return uid == config.OWNER_ID


def limit_for(row):
    if is_owner(row["user_id"]):
        return None
    return config.PREMIUM_LIMIT if db.is_premium(row) else config.FREE_LIMIT


def status_of(row):
    if is_owner(row["user_id"]):
        return "👑 Owner"
    if db.is_premium(row):
        days = math.ceil((row["premium_until"] - time.time()) / 86400)
        return f"💎 Premium ({days}d left)"
    return "🆓 Free User"


def fmt_uptime(sec):
    sec = int(sec)
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    return f"{d}d {h}h {m}m {s}s" if d else f"{h}h {m}m {s}s"


def sanitize(name):
    name = Path(name).name
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80] or "file"


async def safe_edit(q, text, kb=None):
    try:
        await q.edit_message_text(text, parse_mode=HTML, reply_markup=kb)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def get_user(update: Update):
    u = update.effective_user
    if not u:
        return None
    row = db.upsert_user(u.id, u.username, u.first_name)
    if row["banned"]:
        if update.callback_query:
            await update.callback_query.answer("🚫 You are banned.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("🚫 You are banned.")
        return None
    return row


def guarded(fn):
    @functools.wraps(fn)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        row = await get_user(update)
        if row:
            await fn(update, ctx, row)
    return wrapper


def owner_only(fn):
    @functools.wraps(fn)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user and is_owner(update.effective_user.id):
            await fn(update, ctx)
    return wrapper


# ======================= views =======================
def welcome_text(row, tg_user):
    lim = limit_for(row)
    used = db.count_user_files(row["user_id"])
    uname = f"@{esc(tg_user.username)}" if tg_user.username else "N/A"
    return (
        f"👋 Welcome, <b>{esc(tg_user.first_name)}</b>!\n\n"
        f"🆔 Your User ID: <code>{row['user_id']}</code>\n"
        f"✳️ Username: {uname}\n"
        f"🔰 Your Status: {status_of(row)}\n"
        f"📁 Files Uploaded: {used} / {lim if lim is not None else '∞'}\n\n"
        "🤖 Host & run Python (<code>.py</code>) or JS (<code>.js</code>) scripts.\n"
        "Upload single scripts or <code>.zip</code> archives.\n\n"
        "👇 Use buttons or type commands."
    )


def files_view(uid):
    rows = db.list_files(uid)
    if not rows:
        return "📂 Abhi tak koi file upload nahi ki.\n📥 Upload File dabao.", None
    kb = [
        [InlineKeyboardButton(
            f"{'🟢' if runner.is_running(r['id']) else '🔴'} {r['name']}",
            callback_data=f"file:{r['id']}")]
        for r in rows
    ]
    return f"📂 <b>Your Files</b> ({len(rows)})\n🟢 running   🔴 stopped", InlineKeyboardMarkup(kb)


def file_view(f):
    st, info = runner.status(f["id"])
    if st == "running":
        line = f"🟢 Running (PID {info})"
    else:
        line = "🔴 Stopped" + (f" (exit code {info})" if info is not None else "")
    text = (
        f"📄 <b>{esc(f['name'])}</b>\n\n"
        f"Status: {line}\n"
        f"Entry: <code>{esc(f['entry'])}</code>\n"
        f"File ID: <code>{f['id']}</code>"
    )
    fid = f["id"]
    first = (
        [InlineKeyboardButton("⏹ Stop", callback_data=f"stop:{fid}"),
         InlineKeyboardButton("🔄 Restart", callback_data=f"restart:{fid}")]
        if st == "running" else
        [InlineKeyboardButton("▶️ Run", callback_data=f"run:{fid}")]
    )
    kb = InlineKeyboardMarkup([
        first,
        [InlineKeyboardButton("📜 Logs", callback_data=f"logs:{fid}"),
         InlineKeyboardButton("🔃 Refresh", callback_data=f"file:{fid}")],
        [InlineKeyboardButton("🗑 Delete", callback_data=f"del:{fid}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="list")],
    ])
    return text, kb


# ======================= user commands =======================
async def cmd_start(update, ctx, row):
    await update.effective_message.reply_text(
        welcome_text(row, update.effective_user), parse_mode=HTML, reply_markup=MAIN_KB)


async def cmd_help(update, ctx, row):
    await update.effective_message.reply_text(
        "📖 <b>Commands</b>\n"
        "/start - main menu\n/upload - upload a script\n/files - your files\n"
        "/speed - bot speed\n/stats - statistics\n/premium - buy premium\n/owner - contact owner\n\n"
        "💡 ZIP me <code>main.py</code> / <code>index.js</code> aur "
        "<code>requirements.txt</code> / <code>package.json</code> rakho.",
        parse_mode=HTML)


async def cmd_updates(update, ctx, row):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=config.UPDATES_CHANNEL)]])
    await update.effective_message.reply_text("📢 Latest updates ke liye channel join karo:", reply_markup=kb)


async def cmd_upload(update, ctx, row):
    lim = limit_for(row)
    used = db.count_user_files(row["user_id"])
    await update.effective_message.reply_text(
        f"📥 <b>Upload File</b>\n\nMujhe <code>.py</code>, <code>.js</code> ya <code>.zip</code> "
        f"file bhejo (max {config.MAX_FILE_MB} MB).\n"
        f"📁 Slots: {used} / {lim if lim is not None else '∞'}",
        parse_mode=HTML)


async def cmd_files(update, ctx, row):
    text, kb = files_view(row["user_id"])
    await update.effective_message.reply_text(text, parse_mode=HTML, reply_markup=kb)


async def cmd_speed(update, ctx, row):
    t0 = time.perf_counter()
    m = await update.effective_message.reply_text("⚡ Testing...")
    ms = (time.perf_counter() - t0) * 1000
    await m.edit_text(f"⚡ <b>Bot Speed</b>\n\n📡 Latency: <b>{ms:.0f} ms</b>\n"
                      f"⏱ Uptime: {fmt_uptime(time.time() - START_TIME)}", parse_mode=HTML)


async def cmd_stats(update, ctx, row):
    users, prem, files = db.stats()
    mine = db.count_user_files(row["user_id"])
    await update.effective_message.reply_text(
        "📊 <b>Statistics</b>\n\n"
        f"👥 Total Users: {users}\n💎 Premium Users: {prem}\n"
        f"📁 Total Files: {files}\n🟢 Running Scripts: {runner.running_count()}\n"
        f"⏱ Uptime: {fmt_uptime(time.time() - START_TIME)}\n\n"
        f"📂 Your Files: {mine}", parse_mode=HTML)


async def cmd_premium(update, ctx, row):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📞 Contact Owner", url=f"https://t.me/{config.OWNER_USERNAME}")]])
    await update.effective_message.reply_text(config.PREMIUM_TEXT, parse_mode=HTML, reply_markup=kb)


async def cmd_owner(update, ctx, row):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💬 Message Owner", url=f"https://t.me/{config.OWNER_USERNAME}")]])
    await update.effective_message.reply_text(f"📞 Owner: @{config.OWNER_USERNAME}", reply_markup=kb)


ROUTES = {
    BTN_UPDATES: cmd_updates, BTN_UPLOAD: cmd_upload, BTN_FILES: cmd_files,
    BTN_SPEED: cmd_speed, BTN_STATS: cmd_stats, BTN_PREMIUM: cmd_premium, BTN_OWNER: cmd_owner,
}


@guarded
async def on_text_button(update, ctx, row):
    fn = ROUTES.get(update.effective_message.text)
    if fn:
        await fn(update, ctx, row)


# ======================= upload =======================
@guarded
async def on_document(update, ctx, row):
    msg = update.effective_message
    doc = msg.document
    uid = row["user_id"]
    name = sanitize(doc.file_name or "")
    ext = Path(name).suffix.lower()

    if ext not in (".py", ".js", ".zip"):
        await msg.reply_text("❌ Sirf <code>.py</code>, <code>.js</code> ya <code>.zip</code> allowed hai.", parse_mode=HTML)
        return
    if doc.file_size and doc.file_size > config.MAX_FILE_MB * 1024 * 1024:
        await msg.reply_text(f"❌ File {config.MAX_FILE_MB} MB se badi hai.")
        return
    lim = limit_for(row)
    if lim is not None and db.count_user_files(uid) >= lim:
        await msg.reply_text(
            f"⚠️ File limit reached ({lim}).\nPurani file delete karo ya 💎 Premium lo.")
        return

    status = await msg.reply_text("⏳ Uploading...")
    fid = db.add_file(uid, name)
    folder = config.DATA_DIR / "users" / str(uid) / str(fid)
    src = folder / "src"
    try:
        src.mkdir(parents=True)
        tg_file = await doc.get_file()
        if ext == ".zip":
            zpath = folder / "_upload.zip"
            await tg_file.download_to_drive(zpath)
            await asyncio.to_thread(runner.safe_extract, zpath, src)
            zpath.unlink(missing_ok=True)
            workdir = runner.flatten(src)
        else:
            await tg_file.download_to_drive(src / name)
            workdir = src
        entry = runner.find_entry(workdir)
        if not entry:
            raise ValueError("Koi .py/.js file nahi mili (main.py, bot.py, index.js...)")
        db.update_file(fid, str(workdir), entry)

        note = ""
        if (workdir / "requirements.txt").is_file() or (workdir / "package.json").is_file():
            await status.edit_text("📦 Dependencies install ho rahi hain...")
            note = await runner.install_deps(workdir)
    except Exception as e:
        shutil.rmtree(folder, ignore_errors=True)
        db.delete_file(fid)
        await status.edit_text(f"❌ Upload failed: {esc(e)}", parse_mode=HTML)
        return

    text, kb = file_view(db.get_file(fid))
    await status.edit_text(
        f"✅ <b>Uploaded!</b>\n{esc(note)}\n\n" + text if note else "✅ <b>Uploaded!</b>\n\n" + text,
        parse_mode=HTML, reply_markup=kb)


# ======================= inline buttons =======================
@guarded
async def on_button(update, ctx, row):
    q = update.callback_query
    uid = row["user_id"]
    action, _, arg = q.data.partition(":")

    if action == "list":
        text, kb = files_view(uid)
        await safe_edit(q, text, kb)
        await q.answer()
        return
    if not arg.isdigit():
        await q.answer()
        return

    f = db.get_file(int(arg))
    if not f or (f["user_id"] != uid and not is_owner(uid)):
        await q.answer("File not found", show_alert=True)
        return
    fid = f["id"]

    if action == "run":
        ok, res = runner.start(fid, f["workdir"], f["entry"])
        if ok:
            db.set_state(fid, res, 1)
            await q.answer("▶️ Started")
        else:
            await q.answer(f"❌ {res}", show_alert=True)
    elif action == "stop":
        await runner.stop(fid)
        db.set_state(fid, None, 0)
        await q.answer("⏹ Stopped")
    elif action == "restart":
        await runner.stop(fid)
        ok, res = runner.start(fid, f["workdir"], f["entry"])
        db.set_state(fid, res if ok else None, 1 if ok else 0)
        await q.answer("🔄 Restarted" if ok else f"❌ {res}", show_alert=not ok)
    elif action == "logs":
        await q.answer()
        raw = runner.tail_log(f["workdir"], 2000) or "(abhi koi output nahi)"
        while len(esc(raw)) > 3500:
            raw = raw[len(raw) // 4:]
        await q.message.reply_text(
            f"📜 <b>Logs — {esc(f['name'])}</b>\n<pre>{esc(raw)}</pre>", parse_mode=HTML)
        return
    elif action == "del":
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, delete", callback_data=f"delyes:{fid}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"file:{fid}")]])
        await safe_edit(q, f"🗑 <b>{esc(f['name'])}</b> delete karni hai?", kb)
        await q.answer()
        return
    elif action == "delyes":
        await runner.stop(fid)
        shutil.rmtree(config.DATA_DIR / "users" / str(f["user_id"]) / str(fid), ignore_errors=True)
        db.delete_file(fid)
        await q.answer("🗑 Deleted")
        text, kb = files_view(uid)
        await safe_edit(q, text, kb)
        return
    elif action == "file":
        await q.answer()

    text, kb = file_view(db.get_file(fid))
    await safe_edit(q, text, kb)


# ======================= admin =======================
ADMIN_HELP = (
    "👑 <b>Admin commands</b>\n"
    "/addpremium &lt;user_id&gt; &lt;days&gt;\n/removepremium &lt;user_id&gt;\n"
    "/ban &lt;user_id&gt;\n/unban &lt;user_id&gt;\n/broadcast &lt;text&gt;"
)


@owner_only
async def cmd_admin(update, ctx):
    await update.effective_message.reply_text(ADMIN_HELP, parse_mode=HTML)


@owner_only
async def cmd_addpremium(update, ctx):
    try:
        uid, days = int(ctx.args[0]), int(ctx.args[1])
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /addpremium <user_id> <days>")
        return
    until = db.add_premium(uid, days)
    await update.effective_message.reply_text(
        f"✅ {uid} premium till {time.strftime('%Y-%m-%d', time.localtime(until))}")
    try:
        await ctx.bot.send_message(uid, f"💎 Aapko {days} din ka Premium mil gaya! /start dabao.")
    except Exception:
        pass


@owner_only
async def cmd_removepremium(update, ctx):
    try:
        uid = int(ctx.args[0])
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /removepremium <user_id>")
        return
    db.remove_premium(uid)
    await update.effective_message.reply_text(f"✅ Premium removed for {uid}")


@owner_only
async def cmd_ban(update, ctx):
    try:
        uid = int(ctx.args[0])
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /ban <user_id>")
        return
    db.set_ban(uid, True)
    for f in db.list_files(uid):
        await runner.stop(f["id"])
        db.set_state(f["id"], None, 0)
    await update.effective_message.reply_text(f"🚫 {uid} banned (scripts stopped)")


@owner_only
async def cmd_unban(update, ctx):
    try:
        uid = int(ctx.args[0])
    except (IndexError, ValueError):
        await update.effective_message.reply_text("Usage: /unban <user_id>")
        return
    db.set_ban(uid, False)
    await update.effective_message.reply_text(f"✅ {uid} unbanned")


@owner_only
async def cmd_broadcast(update, ctx):
    text = " ".join(ctx.args)
    if not text:
        await update.effective_message.reply_text("Usage: /broadcast <text>")
        return
    ok = fail = 0
    for uid in db.all_user_ids():
        try:
            await ctx.bot.send_message(uid, text)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await update.effective_message.reply_text(f"📣 Sent: {ok} | Failed: {fail}")


# ======================= startup =======================
async def post_init(app: Application):
    try:
        await app.bot.set_my_commands([
            BotCommand("start", "Main menu"), BotCommand("upload", "Upload a script"),
            BotCommand("files", "Your files"), BotCommand("speed", "Bot speed"),
            BotCommand("stats", "Statistics"), BotCommand("premium", "Buy premium"),
            BotCommand("owner", "Contact owner"), BotCommand("help", "Help"),
        ])
    except Exception:
        log.exception("set_my_commands failed (ignored)")
    # revive scripts that were running before restart
    # (ek script ki wajah se poora bot crash na ho -> har file try/except me)
    try:
        files = db.autostart_files()
    except Exception:
        log.exception("autostart list failed")
        files = []
    for f in files:
        try:
            runner.kill_stale(f["pid"], f["workdir"])
            ok, res = runner.start(f["id"], f["workdir"], f["entry"])
            db.set_state(f["id"], res if ok else None, 1 if ok else 0)
            log.info("autostart file %s -> %s", f["id"], ok)
        except Exception:
            log.exception("autostart file %s failed", f["id"])


async def on_error(update, ctx):
    log.error("Update caused error", exc_info=ctx.error)
    # user ko bhi batao, warna button "loading" pe atka rehta hai
    try:
        if update and getattr(update, "callback_query", None):
            await update.callback_query.answer("⚠️ Error aaya, dobara try karo", show_alert=True)
        elif update and getattr(update, "effective_message", None):
            await update.effective_message.reply_text("⚠️ Error aaya, dobara try karo.")
    except Exception:
        pass


def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN set nahi hai (.env file ya environment variable me daalo).")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", config.BOT_TOKEN):
        raise SystemExit(
            "BOT_TOKEN galat format me hai. @BotFather wala asli token daalo "
            "(example.env wala placeholder nahi, quotes/space bhi nahi).")
    db.init()

    # Python 3.12+/3.14: main thread me event loop nahi hota -> run_polling crash
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    app = (
        Application.builder().token(config.BOT_TOKEN)
        .read_timeout(60).write_timeout(60).connect_timeout(30)
        .concurrent_updates(True).post_init(post_init).build()
    )

    for name, fn in [("start", cmd_start), ("help", cmd_help), ("upload", cmd_upload),
                     ("files", cmd_files), ("speed", cmd_speed), ("stats", cmd_stats),
                     ("premium", cmd_premium), ("owner", cmd_owner), ("updates", cmd_updates)]:
        app.add_handler(CommandHandler(name, guarded(fn)))

    for name, fn in [("admin", cmd_admin), ("addpremium", cmd_addpremium),
                     ("removepremium", cmd_removepremium), ("ban", cmd_ban),
                     ("unban", cmd_unban), ("broadcast", cmd_broadcast)]:
        app.add_handler(CommandHandler(name, fn))

    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.Text(list(ROUTES)), on_text_button))
    app.add_error_handler(on_error)

    log.info("Hosting bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
