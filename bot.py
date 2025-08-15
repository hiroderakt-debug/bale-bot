import asyncio
from datetime import datetime, timedelta
from collections import deque
from bale import Bot, Message, InputFile
import bale.error
import aiohttp
import threading
import http.server
import socketserver

bot = Bot(token="347447058:s19i9J3UPZLUrprUqrH12UYD1lDGcPPi1ulV9iFL")

# صف ارسال پیام‌ها
send_queue = asyncio.Queue()
scheduled_queue = deque()  # صف با زمان برنامه‌ریزی‌شده

async def safe_send(chat_id: int, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except bale.error.Forbidden:
        print(f"❌ ارسال پیام به کاربر {chat_id} ممکن نیست.")

@bot.event
async def on_ready():
    print("✅ ربات آماده است.")
    asyncio.create_task(process_queue())
    asyncio.create_task(keep_alive())  # فعال نگه‌داشتن سرور

@bot.event
async def on_message(message: Message):
    if getattr(message.chat, "type", None) != "private":
        return
    if message.author.username != "heroderact":
        return

    # بررسی درخواست زمان با ریپلای
    if message.reply_to_message and message.content.strip().lower() == "زمان":
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

    # تعیین زمان ارسال بر اساس آخرین پیام صف
    if scheduled_queue:
        last_scheduled_time = scheduled_queue[-1][1]
        scheduled_time = last_scheduled_time + timedelta(minutes=20)
    else:
        scheduled_time = datetime.now() + timedelta(minutes=20)

    scheduled_queue.append((message, scheduled_time))
    await send_queue.put(message)

async def process_queue():
    global scheduled_queue

    while True:
        message = await send_queue.get()
        user_id = message.author.user_id
        caption = message.content or ""
        media_sent = False

        # پیدا کردن زمان برنامه‌ریزی‌شده برای این پیام
        scheduled_time = None
        for msg, time in scheduled_queue:
            if msg.message_id == message.message_id:
                scheduled_time = time
                break

        # اگر زمان برنامه‌ریزی‌شده وجود داشت، تا اون زمان صبر کن
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
                print(f"✅ ویدیو از کاربر {user_id} ارسال شد: {datetime.now()}")
                await safe_send(user_id, "🎥 ویدیو با موفقیت ارسال شد.")
                media_sent = True

            # ارسال همه عکس‌ها
            elif isinstance(message.photos, list) and len(message.photos) > 0:
                for photo in message.photos:
                    await bot.send_photo(
                        chat_id="@hiromce",
                        photo=InputFile(photo.file_id),
                        caption=caption
                    )
                    print(f"✅ عکس از کاربر {user_id} ارسال شد: {datetime.now()}")
                    await safe_send(user_id, "🖼️ عکس با موفقیت ارسال شد.")
                    media_sent = True

            else:
                await safe_send(user_id, "⚠️ لطفاً فقط عکس یا ویدیو همراه با متن ارسال کنید.")

        except Exception as e:
            print(f"❌ خطا در ارسال رسانه: {e}")
            await safe_send(user_id, "⚠️ خطا در ارسال رسانه.")

        # حذف از صف زمان‌بندی‌شده
        scheduled_queue = deque([
            (msg, time) for msg, time in scheduled_queue if msg.message_id != message.message_id
        ])

# سرور جعلی برای جلوگیری از قطع شدن ربات
def fake_server():
    PORT = 8080
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()

threading.Thread(target=fake_server, daemon=True).start()

# پینگ داخلی برای فعال نگه‌داشتن سرور
async def keep_alive():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                await session.get("http://localhost:8080")
                print("🔁 پینگ داخلی برای فعال نگه‌داشتن سرور ارسال شد.")
        except Exception as e:
            print(f"⚠️ خطا در پینگ داخلی: {e}")
        await asyncio.sleep(600)  # هر 10 دقیقه

if __name__ == "__main__":
    print("🤖 ربات در حال اجرا و فقط به پیام‌های شخصی از @heroderact پاسخ می‌دهد...")
    bot.run()
