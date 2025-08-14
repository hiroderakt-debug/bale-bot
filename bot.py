import asyncio
from datetime import datetime
from bale import Bot, Message, InputFile
import bale.error

bot = Bot(token="347447058:s19i9J3UPZLUrprUqrH12UYD1lDGcPPi1ulV9iFL")

user_states = {}
user_queues = {}

async def safe_send(chat_id: int, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except bale.error.Forbidden:
        print(f"❌ ارسال پیام به کاربر {chat_id} ممکن نیست.")

@bot.event
async def on_ready():
    print("✅ ربات آماده است.")
    asyncio.create_task(scheduled_sender())  # اجرای زمان‌بندی بعد از آماده شدن ربات

@bot.event
async def on_message(message: Message):
    user_id = message.author.user_id

    if message.author.username != "heroderact":
        return

    if user_id not in user_states:
        user_states[user_id] = {"state": "awaiting_media"}
        await safe_send(user_id, "🎬 لطفاً یک ویدیو یا عکس ارسال کنید:")
        return

    state = user_states[user_id]["state"]

    if state == "awaiting_media":
        if isinstance(message.video, dict) and "file_id" in message.video:
            user_states[user_id].update({
                "state": "awaiting_text",
                "media_type": "video",
                "file_id": message.video["file_id"]
            })
            await safe_send(user_id, "✅ ویدیو دریافت شد! لطفاً متن توضیحی را ارسال کنید:")

        elif isinstance(message.photos, list) and len(message.photos) > 0:
            last_photo = message.photos[-1]
            user_states[user_id].update({
                "state": "awaiting_text",
                "media_type": "photo",
                "file_id": last_photo.file_id
            })
            await safe_send(user_id, "✅ عکس دریافت شد! لطفاً متن توضیحی را ارسال کنید:")

        else:
            await safe_send(user_id, "⚠️ لطفاً فقط ویدیو یا عکس ارسال کنید!")

    elif state == "awaiting_text":
        if message.content:
            if user_id not in user_queues:
                user_queues[user_id] = []
            user_queues[user_id].append({
                "media_type": user_states[user_id]["media_type"],
                "file_id": user_states[user_id]["file_id"],
                "caption": message.content
            })
            await safe_send(user_id, "🕒 محتوا در صف ارسال قرار گرفت و با فاصله منتشر خواهد شد.")
            user_states[user_id] = {"state": "awaiting_media"}
            await safe_send(user_id, "🎬 لطفاً ویدیو یا عکس بعدی را ارسال کنید:")
        else:
            await safe_send(user_id, "⚠️ لطفاً فقط متن ارسال کنید!")

async def scheduled_sender():
    channel = "@hiromce"
    while True:
        for user_id, queue in user_queues.items():
            if queue:
                item = queue.pop(0)
                try:
                    if item["media_type"] == "video":
                        await bot.send_video(
                            chat_id=channel,
                            video=InputFile(item["file_id"]),
                            caption=item["caption"]
                        )
                    elif item["media_type"] == "photo":
                        await bot.send_photo(
                            chat_id=channel,
                            photo=InputFile(item["file_id"]),
                            caption=item["caption"]
                        )
                    print(f"✅ محتوا از کاربر {user_id} ارسال شد: {datetime.now()}")
                except Exception as e:
                    print(f"❌ خطا در ارسال محتوا: {e}")
        await asyncio.sleep(20 * 60)  # فاصله ۵ ثانیه‌ای

if __name__ == "__main__":
    print("🤖 ربات در حال اجرا و فقط به @heroderact پاسخ می‌دهد...")
    bot.run()
