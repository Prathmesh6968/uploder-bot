#!/usr/bin/env python3
"""
Telegram Upload Bot
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Install: pip install pyrogram tgcrypto aiohttp aiofiles
Run:     python3 upload_bot.py
"""

import asyncio
import json
import os
import re
import sys
import time
import math

try:
    import aiohttp
    import aiofiles
    from pyrogram import Client, filters
    from pyrogram.types import (
        Message, CallbackQuery,
        InlineKeyboardMarkup, InlineKeyboardButton
    )
except ImportError:
    print("\n[!] Dependencies install karo:")
    print("    pip install pyrogram tgcrypto aiohttp aiofiles\n")
    sys.exit(1)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   Render env variables se aayega
#   Ya seedha hardcode karo Termux ke liye
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
API_ID       = int(os.environ.get("API_ID",       "12345678"))
API_HASH     =     os.environ.get("API_HASH",     "your_api_hash")
BOT_TOKEN    =     os.environ.get("BOT_TOKEN",    "your_bot_token")
ALLOWED_USER = int(os.environ.get("ALLOWED_USER", "123456789"))
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONFIG_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_config.json")
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# user_state stores per-user data:
# {
#   uid: {
#     "url": str,
#     "filename": str,
#     "caption": str,
#     "waiting": "rename" | "caption" | None
#   }
# }
user_state: dict = {}

app = Client(
    name="upload_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(data: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_channel(user_id: int):
    return load_config().get(str(user_id), {}).get("channel_id")


def set_channel(user_id: int, channel_id: int, channel_title: str):
    cfg = load_config()
    cfg[str(user_id)] = {"channel_id": channel_id, "channel_title": channel_title}
    save_config(cfg)


# ── Helpers ───────────────────────────────────────────────────────────────────

def human_size(b: int) -> str:
    if b == 0: return "0 B"
    units = ["B", "KB", "MB", "GB"]
    i = int(math.floor(math.log(b, 1024)))
    return f"{b / math.pow(1024, i):.1f} {units[min(i, 3)]}"


def human_speed(bps: float) -> str:
    return human_size(int(bps)) + "/s"


def progress_bar(cur, total, w=12) -> str:
    if not total: return "░" * w
    f = int(w * cur / total)
    return "█" * f + "░" * (w - f)


def get_filename(url: str) -> str:
    import hashlib
    name = url.split("?")[0].split("/")[-1]
    # URL decode karo
    try:
        from urllib.parse import unquote
        name = unquote(name)
    except Exception:
        pass
    # Sirf safe characters rakho — baaki underscore se replace
    name = re.sub(r'[^\w\.\-]', '_', name)
    # Multiple underscores ek karo
    name = re.sub(r'_+', '_', name).strip('_')
    ext  = os.path.splitext(name)[1].lower()
    if len(name) > 60 or not name:
        if not ext:
            ext = ".mp4"
        name = hashlib.md5(url.encode()).hexdigest()[:16] + ext
    elif not ext:
        name = name + ".mp4"
    return name


def safe_filename(name: str, default_ext: str = ".mp4") -> str:
    """Custom naam ko safe banao"""
    ext = os.path.splitext(name)[1].lower()
    if not ext:
        base = name
        ext  = default_ext
    else:
        base = os.path.splitext(name)[0]
    # Special chars hata do
    base = re.sub(r'[^\w\-]', '_', base)
    base = re.sub(r'_+', '_', base).strip('_')
    return (base + ext)[:80]


def make_confirm_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Rename", callback_data="action_rename"),
            InlineKeyboardButton("📝 Caption", callback_data="action_caption"),
        ],
        [
            InlineKeyboardButton("✅ Upload Karo", callback_data="action_done"),
            InlineKeyboardButton("❌ Cancel",      callback_data="action_cancel"),
        ]
    ])


def make_confirm_text(uid: int) -> str:
    state    = user_state.get(uid, {})
    filename = state.get("filename", "unknown")
    caption  = state.get("caption", "")
    url      = state.get("url", "")
    short    = url[:50] + "..." if len(url) > 50 else url

    text = (
        f"📥 **Link mila!**\n\n"
        f"🔗 `{short}`\n"
        f"📁 **File name:** `{filename}`\n"
    )
    if caption:
        text += f"📝 **Caption:** `{caption[:80]}{'...' if len(caption)>80 else ''}`\n"
    text += "\nKya karna hai?"
    return text


# ── Download ──────────────────────────────────────────────────────────────────

async def download_file(url: str, dest: str, status_msg: Message):
    start = time.time()
    last  = 0
    async with aiohttp.ClientSession() as session:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status != 200:
                raise Exception(f"HTTP {resp.status}")
            total = int(resp.headers.get("Content-Length", 0))
            done  = 0
            async with aiofiles.open(dest, "wb") as f:
                async for chunk in resp.content.iter_chunked(256 * 1024):
                    await f.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if now - last >= 2:
                        elapsed = now - start
                        speed   = done / elapsed if elapsed else 0
                        bar     = progress_bar(done, total)
                        pct     = f"{done/total*100:.1f}%" if total else ""
                        eta     = f"ETA: {int((total-done)/speed)}s" if speed and total else ""
                        try:
                            await status_msg.edit_text(
                                f"⬇️ **Downloading...**\n\n"
                                f"`{bar}` {pct}\n"
                                f"📦 {human_size(done)}"
                                f"{f' / {human_size(total)}' if total else ''}\n"
                                f"⚡ {human_speed(speed)}  {eta}"
                            )
                        except Exception:
                            pass
                        last = now
    return done


# ── Upload progress ───────────────────────────────────────────────────────────

async def upload_progress(cur, total, msg: Message, start: float, state: dict):
    now = time.time()
    if now - state.get("t", 0) < 2:
        return
    state["t"] = now
    speed = cur / (now - start) if now - start > 0 else 0
    bar   = progress_bar(cur, total)
    pct   = f"{cur/total*100:.1f}%" if total else ""
    eta   = f"ETA: {int((total-cur)/speed)}s" if speed and total else ""
    try:
        await msg.edit_text(
            f"⬆️ **Uploading...**\n\n"
            f"`{bar}` {pct}\n"
            f"📦 {human_size(cur)} / {human_size(total)}\n"
            f"⚡ {human_speed(speed)}  {eta}"
        )
    except Exception:
        pass


# ── Do upload ─────────────────────────────────────────────────────────────────

async def do_upload(client: Client, uid: int, status_msg: Message):
    state      = user_state.get(uid, {})
    url        = state.get("url")
    filename   = state.get("filename", get_filename(url))
    custom_cap = state.get("caption", "")
    channel_id = get_channel(uid)

    if not url or not channel_id:
        await status_msg.edit_text("❌ Kuch missing hai — dobara link bhejo.")
        return

    filepath = os.path.join(DOWNLOAD_DIR, filename)

    # Download
    try:
        await download_file(url, filepath, status_msg)
    except Exception as e:
        await status_msg.edit_text(f"❌ Download fail!\n`{e}`")
        user_state.pop(uid, None)
        return

    # Build caption
    base    = custom_cap if custom_cap else f"📁 `{filename}`"
    caption = (
        f"{base}\n\n"
        f"> 🔰 Main:[ @AnimeDillo ]\n"
        f"> 🔰 Powered By:[ @NeonSenpaiGalaxy ]"
    )

    await status_msg.edit_text("⬆️ Upload shuru ho raha hai...")
    ustart = time.time()
    pstate = {"t": 0}

    try:
        fsize = os.path.getsize(filepath)

        if fsize > 2 * 1024 ** 3:
            await status_msg.edit_text("❌ File 2GB se badi hai!")
            return

        video_exts = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v"}
        ext = os.path.splitext(filepath)[1].lower()

        if ext in video_exts:
            await client.send_video(
                chat_id=channel_id,
                video=filepath,
                caption=caption,
                supports_streaming=True,
                progress=upload_progress,
                progress_args=(status_msg, ustart, pstate),
            )
        else:
            await client.send_document(
                chat_id=channel_id,
                document=filepath,
                caption=caption,
                progress=upload_progress,
                progress_args=(status_msg, ustart, pstate),
            )

        elapsed = time.time() - ustart
        cfg     = load_config().get(str(uid), {})
        await status_msg.edit_text(
            f"✅ **Done!**\n\n"
            f"📁 `{filename}`\n"
            f"📦 {human_size(fsize)}\n"
            f"⏱ {int(elapsed)}s mein upload hua\n"
            f"📢 `{cfg.get('channel_title', channel_id)}`"
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ Upload fail!\n`{e}`")
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)
        user_state.pop(uid, None)


# ── Message handler ───────────────────────────────────────────────────────────

@app.on_message(filters.private & filters.user(ALLOWED_USER))
async def handle(client: Client, message: Message):
    uid  = message.from_user.id
    text = (message.text or "").strip()

    # /start
    if text == "/start":
        ch    = get_channel(uid)
        ch_tx = f"📢 Channel: `{load_config().get(str(uid), {}).get('channel_title', ch)}`" if ch else "⚠️ Channel set nahi — `/setchannel` use karo"
        await message.reply(
            "👋 **Upload Bot**\n\n"
            "**Commands:**\n"
            "`/setchannel` — Upload channel set karo\n"
            "`/mychannel`  — Current channel dekho\n\n"
            "Koi bhi direct link bhejo — main confirm karunga phir upload! 🚀\n\n"
            + ch_tx
        )
        return

    # /mychannel
    if text == "/mychannel":
        cfg = load_config().get(str(uid), {})
        if cfg:
            await message.reply(
                f"📢 **Current Channel:**\n"
                f"Title: `{cfg.get('channel_title', 'Unknown')}`\n"
                f"ID: `{cfg.get('channel_id')}`"
            )
        else:
            await message.reply("⚠️ Koi channel set nahi!\n`/setchannel` use karo.")
        return

    # /setchannel
    if text == "/setchannel":
        user_state[uid] = {"waiting": "channel"}
        await message.reply(
            "📢 **Channel set karo:**\n\n"
            "1️⃣ Username: `@mychannelname`\n"
            "2️⃣ ID: `-1001234567890`\n\n"
            "⚠️ Bot channel ka **admin** hona chahiye!"
        )
        return

    # Waiting for channel
    if user_state.get(uid, {}).get("waiting") == "channel":
        try:
            chat = await client.get_chat(
                int(text) if text.lstrip("-").isdigit() else text
            )
            set_channel(uid, chat.id, chat.title)
            user_state.pop(uid, None)
            await message.reply(
                f"✅ **Channel set!**\n\n"
                f"📢 `{chat.title}`\n"
                f"🆔 `{chat.id}`\n\n"
                f"Ab link bhejo! 🚀"
            )
        except Exception as e:
            await message.reply(f"❌ Channel nahi mila!\n`{e}`")
        return

    # Waiting for rename
    if user_state.get(uid, {}).get("waiting") == "rename":
        new_name = text.strip()
        ext      = os.path.splitext(user_state[uid].get("filename", "file.mp4"))[1] or ".mp4"
        user_state[uid]["filename"] = safe_filename(new_name, ext)
        user_state[uid]["waiting"]  = None
        await message.reply(
            f"✅ Naam set: `{new_name + ext}`",
            reply_markup=make_confirm_buttons()
        )
        # Update confirm message
        try:
            confirm_id = user_state[uid].get("confirm_msg_id")
            if confirm_id:
                await client.edit_message_text(
                    chat_id=uid,
                    message_id=confirm_id,
                    text=make_confirm_text(uid),
                    reply_markup=make_confirm_buttons()
                )
        except Exception:
            pass
        return

    # Waiting for caption
    if user_state.get(uid, {}).get("waiting") == "caption":
        user_state[uid]["caption"] = text.strip()
        user_state[uid]["waiting"] = None
        await message.reply(
            f"✅ Caption set!",
            reply_markup=make_confirm_buttons()
        )
        try:
            confirm_id = user_state[uid].get("confirm_msg_id")
            if confirm_id:
                await client.edit_message_text(
                    chat_id=uid,
                    message_id=confirm_id,
                    text=make_confirm_text(uid),
                    reply_markup=make_confirm_buttons()
                )
        except Exception:
            pass
        return

    # URL received
    url_match = re.search(r'https?://\S+', text)
    if not url_match:
        await message.reply("❌ Valid URL nahi mili!\nHTTP/HTTPS link bhejo.")
        return

    channel_id = get_channel(uid)
    if not channel_id:
        await message.reply("⚠️ Pehle channel set karo!\n`/setchannel` use karo.")
        return

    url      = url_match.group(0)
    filename = get_filename(url)

    user_state[uid] = {
        "url":      url,
        "filename": filename,
        "caption":  "",
        "waiting":  None,
    }

    sent = await message.reply(
        make_confirm_text(uid),
        reply_markup=make_confirm_buttons()
    )
    user_state[uid]["confirm_msg_id"] = sent.id


# ── Callback handler (buttons) ────────────────────────────────────────────────

@app.on_callback_query(filters.user(ALLOWED_USER))
async def handle_callback(client: Client, query: CallbackQuery):
    uid  = query.from_user.id
    data = query.data

    if data == "action_cancel":
        user_state.pop(uid, None)
        await query.message.edit_text("❌ Cancelled.")
        await query.answer("Cancelled!")
        return

    if data == "action_done":
        await query.answer("Upload shuru ho raha hai! ⬆️")
        status = await query.message.edit_text("🔄 Shuru ho raha hai...")
        await do_upload(client, uid, status)
        return

    if data == "action_rename":
        user_state[uid]["waiting"] = "rename"
        await query.answer("Naam bhejo!")
        await query.message.reply(
            "✏️ **Naya file naam bhejo:**\n(Extension mat likho, automatically lagega)"
        )
        return

    if data == "action_caption":
        user_state[uid]["waiting"] = "caption"
        await query.answer("Caption bhejo!")
        await query.message.reply("📝 **Custom caption bhejo:**")
        return


# ── Dummy web server (Render free tier ke liye) ──────────────────────────────

from flask import Flask
from threading import Thread

web = Flask(__name__)

@web.route("/")
def home():
    return "✅ Upload Bot is running!", 200

@web.route("/health")
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web.run(host="0.0.0.0", port=port)


# ── Run ───────────────────────────────────────────────────────────────────────

print("━━━ Upload Bot Starting ━━━")
print("Bot chal raha hai... (Ctrl+C se band karo)\n")

# Web server alag thread mein chalao
Thread(target=run_web, daemon=True).start()

app.run()

