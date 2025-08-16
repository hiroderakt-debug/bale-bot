import asyncio
import json
import sqlite3
import os
from datetime import datetime, timedelta
from collections import deque
from bale import Bot, Message, InputFile
import bale.error
import aiohttp
from fastapi import FastAPI
import uvicorn
import threading

bot = Bot(token="347447058:s19i9J3UPZLUrprUqrH12UYD1lDGcPPi1ulV9iFL")
send_queue = asyncio.Queue()
scheduled_queue = deque()

# اتصال به دیتابیس
conn = sqlite3.connect("data.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS scheduled (
    message_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    content TEXT,
    video TEXT,
    photos TEXT,
    scheduled_time TEXT
)
""")
conn.commit()

# وب‌سرور FastAPI
app = FastAPI()

@app.get("/")
def ping():
    return {"status": "ok"}

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

def save_message_to_db(message: Message, scheduled_time: datetime):
    cursor.execute("""
    INSERT OR REPLACE INTO scheduled (message_id, user_id, content, video, photos, scheduled_time)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        message.message_id,
        message.author.user_id,
        message.content,
        message.video["file_id"] if message.video else None,
        json.dumps([photo.file_id for photo in message.photos]) if message.photos else "[]",
        scheduled_time.isoformat()
    ))
    conn.commit()

def delete_message_from_db(message_id: int):
    cursor.execute("DELETE FROM scheduled WHERE message_id = ?", (message_id,))
    conn.commit()

def load_queue_from_db():
    cursor.execute("SELECT * FROM scheduled ORDER BY scheduled_time")
    rows = cursor.fetchall()
    for row in rows:
        FakeMessage = type("FakeMessage", (), {})
        FakeAuthor = type("FakeAuthor", (), {})
        FakePhoto = type("FakePhoto", (), {})

        msg = FakeMessage()
        msg.message_id = row[0]
        msg.content = row[2]
        msg.video = {"file_id": row[3]} if row[3] else None
        photo_ids = json.loads(row[4])
        msg.photos = [FakePhoto() for _ in photo_ids]
        for i, pid in enumerate(photo_ids):
            msg.photos[i].file_id = pid

        msg.author = FakeAuthor()
        msg.author.user_id = row[1]

        time = datetime.fromisoformat(row[5])
        scheduled_queue.append((msg, time))

async def safe_send(chat_id: int, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except bale.error.Forbidden:
        print(f"❌ ارسال پیام به کاربر {chat_id} ممکن نیست.")

@bot.event
async def on_ready():
    print("✅ ربات آماده است.")
    load_queue_from_db()
    asyncio.create_task(process_queue())
    asyncio.create_task(log_remaining_times())
    asyncio.create_task(keep_alive())

@bot.event
async def on_message(message: Message):
    global scheduled_queue

    if getattr(message.chat, "type", None) != "private":
        return
    if message.author.username != "heroderact":
        return

    if message.reply_to_message and message.content.strip().lower() == "لغو":
        reply_id = message.reply_to_message.message_id
        for original_msg, _ in scheduled_queue:
            if original_msg.message_id == reply_id:
                scheduled_queue = deque([
                    (msg, time) for msg, time in scheduled_queue if msg.message_id != reply_id
                ])
                delete_message_from_db(reply_id)
                await safe_send(message.author.user_id, "❌ پیام با موفقیت لغو شد و دیگر ارسال نمی‌شود.")
                return
        await safe_send(message.author.user_id, "⚠️ این پیام در صف نبود یا قبلاً ارسال شده.")
        return

    if message.reply_to_message and message.content.strip().lower() == "زمان":
        reply_id = message.reply_to_message.message_id
        for original_msg, scheduled_time in scheduled_queue:
            if original_msg.message_id == reply_id:
                remaining = scheduled_time - datetime.now()
                if remaining.total_seconds() > 0:
                    await safe_send(message.author.user_id, format_remaining_time(remaining))
                else:
                    await safe_send(message.author.user_id, "✅ این رسانه در حال ارسال یا ارسال شده است.")
                return
        await safe_send(message.author.user_id, "❌ این پیام در صف ارسال نیست یا قبلاً ارسال شده.")
        return

    if message.content.strip().lower() == "حذف":
        scheduled_queue.clear()
        cursor.execute("DELETE FROM scheduled")
        conn.commit()
        await safe_send(message.author.user_id, "🗑️ کل صف زمان‌بندی‌شده با موفقیت حذف شد.")
        return

    if scheduled_queue:
        last_scheduled_time = scheduled_queue[-1][1]
        scheduled_time = last_scheduled_time + timedelta(minutes=20)
    else:
        scheduled_time = datetime.now() + timedelta(minutes=20)

    scheduled_queue.append((message, scheduled_time))
    await send_queue.put(message)
    save_message_to_db(message, scheduled_time)

async def process_queue():
    global scheduled_queue

    while True:
        message = await send_queue.get()

        user_id = message.author.user_id
        caption = message.content or ""

        scheduled_time = None
        for msg, time in scheduled_queue:
            if msg.message_id == message.message_id:
                scheduled_time = time
                break

        if scheduled_time:
            now = datetime.now()
            wait_seconds = (scheduled_time - now).total_seconds()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

        try:
            if isinstance(message.video, dict) and "file_id" in message.video:
                await bot.send_video(
                    chat_id="@hiromce",
                    video=InputFile(message.video["file_id"]),
                    caption=caption
                )
                print(f"✅ ویدیو از کاربر {user_id} ارسال شد: {datetime.now()}")
                await safe_send(user_id, "🎥 ویدیو با موفقیت ارسال شد.")

            elif isinstance(message.photos, list) and len(message.photos) > 0:
                for photo in message.photos:
                    await bot.send_photo(
                        chat_id="@hiromce",
                        photo=InputFile(photo.file_id),
                        caption=caption
                    )
                    print(f"✅ عکس از کاربر {user_id} ارسال شد: {datetime.now()}")
                    await safe_send(user_id, "🖼️ عکس با موفقیت ارسال شد.")

            else:
                await safe_send(user_id, "⚠️ لطفاً فقط عکس یا ویدیو همراه با متن ارسال کنید.")

        except Exception as e:
            print(f"❌ خطا در ارسال رسانه: {e}")
            await safe_send(user_id, "⚠️ خطا در ارسال رسانه.")

        scheduled_queue = deque([
            (msg, time) for msg, time in scheduled_queue if msg.message_id != message.message_id
        ])
        delete_message_from_db(message.message_id)

def format_remaining_time(remaining: timedelta) -> str:
    total_seconds = int(remaining.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    parts = []
    if days > 0:
        parts.append(f"{days} روز")
    if hours > 0:
        parts.append(f"{hours} ساعت")
    if minutes > 0:
        parts.append(f"{minutes} دقیقه")
    if seconds > 0 and days == 0:
        parts.append(f"{seconds} ثانیه")

    return "⏳ حدود " + " و ".join(parts) + " تا ارسال باقی مانده."

async def log_remaining_times():
    while True:
        print("📋 وضعیت صف ارسال:")
        now = datetime.now()
        for msg, scheduled_time in scheduled_queue:
            remaining = scheduled_time - now
            if remaining.total_seconds() <= 0:
                print(f"✅ پیام {msg.message_id} آماده ارسال است.")
            else:
                print(f"🕒 پیام {msg.message_id} از کاربر {msg.author.user_id} در {format_remaining_time(remaining)} دیگر ارسال می‌شود.")
        await asyncio.sleep(180)

async def keep_alive():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("http://localhost:" + os.environ.get("PORT", "10000")) as resp:
                    print(f"🔄 پینگ داخلی: {resp.status}")
        except Exception
