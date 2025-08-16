import asyncio
import json
from datetime import datetime, timedelta
from collections import deque
from bale import Bot, Message, InputFile
import bale.error

bot = Bot(token="347447058:s19i9J3UPZLUrprUqrH12UYD1lDGcPPi1ulV9iFL")

send_queue = asyncio.Queue()
scheduled_queue = deque()
cancelled_messages = set()

def save_queue_to_file():
    with open("scheduled_queue.json", "w", encoding="utf-8") as f:
        data = [
            {
                "message_id": msg.message_id,
                "user_id": msg.author.user_id,
                "content": msg.content,
                "video": msg.video["file_id"] if msg.video else None,
                "photos": [photo.file_id for photo in msg.photos] if msg.photos else [],
                "scheduled_time": time.isoformat()
            }
            for msg, time in scheduled_queue
        ]
        json.dump(data, f)

def load_queue_from_file():
    try:
        with open("scheduled_queue.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                FakeMessage = type("FakeMessage", (), {})
                FakeAuthor = type("FakeAuthor", (), {})
                FakePhoto = type("FakePhoto", (), {})

                msg = FakeMessage()
                msg.message_id = item["message_id"]
                msg.content = item["content"]
                msg.video = {"file_id": item["video"]} if item["video"] else None
                msg.photos = [FakePhoto() for _ in item["photos"]]
                for i, pid in enumerate(item["photos"]):
                    msg.photos[i].file_id = pid

                msg.author = FakeAuthor()
                msg.author.user_id = item["user_id"]

                time = datetime.fromisoformat(item["scheduled_time"])
                scheduled_queue.append((msg, time))
    except FileNotFoundError:
        pass

def save_cancelled_to_file():
    with open("cancelled.json", "w", encoding="utf-8") as f:
        json.dump(list(cancelled_messages), f)

def load_cancelled_from_file():
    global cancelled_messages
    try:
        with open("cancelled.json", "r", encoding="utf-8") as f:
            cancelled_messages = set(json.load(f))
    except FileNotFoundError:
        pass

async def safe_send(chat_id: int, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except bale.error.Forbidden:
        print(f"❌ ارسال پیام به کاربر {chat_id} ممکن نیست.")

@bot.event
async def on_ready():
    print("✅ ربات آماده است.")
    load_queue_from_file()
    load_cancelled_from_file()
    asyncio.create_task(process_queue())
    asyncio.create_task(log_remaining_times())

@bot.event
async def on_message(message: Message):
    global scheduled_queue  # ✅ رفع خطای UnboundLocalError

    if getattr(message.chat, "type", None) != "private":
        return
    if message.author.username != "heroderact":
        return

    # لغو پیام زمان‌بندی‌شده
    if message.reply_to_message and message.content.strip().lower() == "لغو":
        reply_id = message.reply_to_message.message_id
        for original_msg, _ in scheduled_queue:
            if original_msg.message_id == reply_id:
                cancelled_messages.add(reply_id)
                scheduled_queue = deque([
                    (msg, time) for msg, time in scheduled_queue if msg.message_id != reply_id
                ])
                save_queue_to_file()
                save_cancelled_to_file()
                await safe_send(message.author.user_id, "❌ پیام با موفقیت لغو شد و دیگر ارسال نمی‌شود.")
                return
        await safe_send(message.author.user_id, "⚠️ این پیام در صف نبود یا قبلاً ارسال شده.")
        return

    # بررسی زمان باقی‌مانده
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

    # زمان‌بندی جدید
    if scheduled_queue:
        last_scheduled_time = scheduled_queue[-1][1]
        scheduled_time = last_scheduled_time + timedelta(minutes=20)
    else:
        scheduled_time = datetime.now() + timedelta(minutes=20)

    scheduled_queue.append((message, scheduled_time))
    await send_queue.put(message)
    save_queue_to_file()

async def process_queue():
    global scheduled_queue

    while True:
        message = await send_queue.get()

        if message.message_id in cancelled_messages:
            print(f"🚫 پیام {message.message_id} لغو شده و ارسال نمی‌شود.")
            continue

        user_id = message.author.user_id
        caption = message.content or ""
        media_sent = False

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
                media_sent = True

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

        scheduled_queue = deque([
            (msg, time) for msg, time in scheduled_queue if msg.message_id != message.message_id
        ])
        save_queue_to_file()

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

if __name__ == "__main__":
    print("🤖 ربات در حال اجرا و فقط به پیام‌های شخصی از @heroderact پاسخ می‌دهد...")
    bot.run()
