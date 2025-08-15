import asyncio
from datetime import datetime
from bale import Bot, Message, InputFile
import bale.error

bot = Bot(token="347447058:s19i9J3UPZLUrprUqrH12UYD1lDGcPPi1ulV9iFL")

# صف ارسال پیام‌ها
send_queue = asyncio.Queue()

async def safe_send(chat_id: int, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except bale.error.Forbidden:
        print(f"❌ ارسال پیام به کاربر {chat_id} ممکن نیست.")

@bot.event
async def on_ready():
    print("✅ ربات آماده است.")
    # راه‌اندازی پردازش صف
    asyncio.create_task(process_queue())

@bot.event
async def on_message(message: Message):
    # فقط پیام‌های شخصی را پردازش کن
    if getattr(message.chat, "type", None) != "private":
        return

    # فقط از کاربر خاص
    if message.author.username != "heroderact":
        return

    # افزودن پیام به صف
    await send_queue.put(message)

async def process_queue():
    while True:
        message = await send_queue.get()
        user_id = message.author.user_id
        caption = message.content or ""

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
                last_photo = message.photos[-1]
                await bot.send_photo(
                    chat_id="@amar_tabliq_hiromce",
                    photo=InputFile(last_photo.file_id),
                    caption=caption
                )
                print(f"✅ عکس از کاربر {user_id} ارسال شد: {datetime.now()}")
                await safe_send(user_id, "🖼️ عکس با موفقیت ارسال شد.")

            else:
                await safe_send(user_id, "⚠️ لطفاً فقط عکس یا ویدیو همراه با متن ارسال کنید.")

        except Exception as e:
            print(f"❌ خطا در ارسال رسانه: {e}")
            await safe_send(user_id, "⚠️ خطا در ارسال رسانه.")

        # ⏳ تأخیر ۵۰ ثانیه‌ای بین هر ارسال
        await asyncio.sleep(50)

# راه‌اندازی سرور جعلی برای جلوگیری از قطع شدن ربات در برخی هاست‌ها
import threading
import http.server
import socketserver

def fake_server():
    PORT = 8080
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()

threading.Thread(target=fake_server, daemon=True).start()

if __name__ == "__main__":
    print("🤖 ربات در حال اجرا و فقط به پیام‌های شخصی از @heroderact پاسخ می‌دهد...")
    bot.run()
