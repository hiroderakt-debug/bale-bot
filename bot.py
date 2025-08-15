import asyncio
from datetime import datetime, timedelta
from collections import deque
from bale import Bot, Message, InputFile
import bale.error

from fastapi import FastAPI
import uvicorn
import threading

# 🎯 توکن ربات
bot = Bot(token="347447058:s19i9J3UPZLUrprUqrH12UYD1lDGcPPi1ulV9iFL")

# صف‌ها
send_queue = asyncio.Queue()
scheduled_queue = deque()

# ارسال امن پیام
async def safe_send(chat_id: int, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except bale.error.Forbidden:
        print(f"❌ ارسال پیام به کاربر {chat_id} ممکن نیست.")

# وقتی ربات آماده شد
@bot.event
async def on_ready():
    print("✅ ربات آماده است.")
    asyncio.create_task(process_queue())

# دریافت پیام
@bot.event
async def on_message(message: Message):
    if getattr(message.chat, "type", None) != "private":
        return
    if message.author.username != "heroderact":
        return

    # بررسی زمان با ریپلای
    if message.reply_to_message and message.content.strip().lower() == "زمان؟":
        reply_id = message.reply_to_message.message_id
        for original_msg, scheduled_time in scheduled_queue:
            if original_msg.message_id == reply_id:
                remaining = scheduled_time - datetime.now()
                if remaining.total_seconds() > 0:
                    minutes = int(remaining.total_seconds() // 60)
                    seconds = int(remaining.total_seconds() % 60)
                    await safe_send(message.author.user_id, f"⏳ حدود {minutes} دقیقه و {seconds} ثانیه تا ارسال باقی مانده.")
                else:
                    await safe_send(message.author.user_id, "✅ این رسانه در حال ارسال یا ارسال شده است.")
                return
        await safe_send(message.author.user_id, "❌ این پیام در صف ارسال نیست یا قبلاً ارسال شده.")
        return

    # زمان‌بندی پیام جدید
    if scheduled_queue:
        last_scheduled_time = scheduled_queue[-1][1]
        scheduled_time = last_scheduled_time + timedelta(minutes=20)
    else:
        scheduled_time = datetime.now() + timedelta(minutes=20)

    scheduled_queue.append((message, scheduled_time))
    await send_queue.put(message)

# پردازش صف ارسال
async def process_queue():
    global scheduled_queue

    while True:
        message = await send_queue.get()
        user_id = message.author.user_id
        caption = message.content or ""
        media_sent = False

        # پیدا کردن زمان ارسال
        scheduled_time = None
        for msg, time in scheduled_queue:
            if msg.message_id == message.message_id:
                scheduled_time = time
                break

        # صبر تا زمان ارسال
        if scheduled_time:
            now = datetime.now()
            wait_seconds = (scheduled_time - now).total_seconds()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

        try:
            # ارسال ویدیو
            if isinstance(message.video, dict) and "file_id" in message.video:
                await bot.send_video(
                    chat_id="@hiromce",
                    video=InputFile(message.video["file_id"]),
                    caption=caption
                )
                print(f"✅ ویدیو از کاربر {user_id} ارسال شد.")
                await safe_send(user_id, "🎥 ویدیو با موفقیت ارسال شد.")
                media_sent = True

            # ارسال عکس‌ها
            elif isinstance(message.photos, list) and len(message.photos) > 0:
                for photo in message.photos:
                    await bot.send_photo(
                        chat_id="@hiromce",
                        photo=InputFile(photo.file_id),
                        caption=caption
                    )
                    print(f"✅ عکس از کاربر {user_id} ارسال شد.")
                    await safe_send(user_id, "🖼️ عکس با موفقیت ارسال شد.")
                    media_sent = True

            else:
                await safe_send(user_id, "⚠️ لطفاً فقط عکس یا ویدیو همراه با متن ارسال کنید.")

        except Exception as e:
            print(f"❌ خطا در ارسال رسانه: {e}")
            await safe_send(user_id, "⚠️ خطا در ارسال رسانه.")

        # حذف از صف
        scheduled_queue = deque([
            (msg, time) for msg, time in scheduled_queue if msg.message_id != message.message_id
        ])

# 🌐 سرور FastAPI برای فعال نگه داشتن سرویس در Render
app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "ok"}

def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=10000)

# اجرای سرور FastAPI در ترد جداگانه
threading.Thread(target=run_fastapi, daemon=True).start()

# اجرای ربات
if __name__ == "__main__":
    print("🤖 ربات در حال اجرا و فقط به پیام‌های شخصی از @heroderact پاسخ می‌دهد...")
    bot.run()
