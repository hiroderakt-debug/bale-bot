from datetime import datetime, timedelta
import asyncio

# صف زمان‌بندی پیام‌ها
scheduled_queue = []
delay_minutes = 20  # مقدار پیش‌فرض تأخیر بین ارسال‌ها

# تابع ارسال امن
async def safe_send(user_id, content):
    try:
        # اینجا تابع ارسال پیام به کاربر رو قرار بده
        print(f"ارسال به {user_id}: {content}")
    except Exception as e:
        print(f"خطا در ارسال: {e}")

# تابع اصلی دریافت پیام
async def on_message(message):
    global delay_minutes

    content = message.content.strip()
    user_id = message.author.user_id

    # تغییر زمان تأخیر
    if content.startswith("تغییر زمان"):
        try:
            new_delay = int(content.split(" ")[-1])
            if new_delay <= 0:
                await safe_send(user_id, "⚠️ لطفاً عددی بزرگ‌تر از صفر وارد کنید.")
                return
            delay_minutes = new_delay
            await safe_send(user_id, f"⏱️ زمان تأخیر بین ارسال‌ها به {new_delay} دقیقه تغییر کرد.")
        except ValueError:
            await safe_send(user_id, "⚠️ فرمت صحیح نیست. مثال: تغییر زمان 30")
        return

    # لغو همه پیام‌های زمان‌بندی‌شده
    if content == "لغو":
        scheduled_queue[:] = [item for item in scheduled_queue if item["user_id"] != user_id]
        await safe_send(user_id, "❌ همه پیام‌های زمان‌بندی‌شده شما لغو شدند.")
        return

    # نمایش زمان پیام‌های زمان‌بندی‌شده
    if content == "زمان":
        user_messages = [item for item in scheduled_queue if item["user_id"] == user_id]
        if not user_messages:
            await safe_send(user_id, "⏳ هیچ پیام زمان‌بندی‌شده‌ای ندارید.")
        else:
            times = "\n".join([f"- {item['time'].strftime('%H:%M')} → {item['content']}" for item in user_messages])
            await safe_send(user_id, f"🕒 پیام‌های زمان‌بندی‌شده:\n{times}")
        return

    # حذف آخرین پیام زمان‌بندی‌شده
    if content == "حذف":
        for i in range(len(scheduled_queue) - 1, -1, -1):
            if scheduled_queue[i]["user_id"] == user_id:
                removed = scheduled_queue.pop(i)
                await safe_send(user_id, f"🗑️ پیام '{removed['content']}' حذف شد.")
                return
        await safe_send(user_id, "⚠️ پیام زمان‌بندی‌شده‌ای برای حذف وجود ندارد.")
        return

    # زمان‌بندی پیام جدید
    user_messages = [item for item in scheduled_queue if item["user_id"] == user_id]
    if user_messages:
        last_scheduled_time = user_messages[-1]["time"]
        scheduled_time = last_scheduled_time + timedelta(minutes=delay_minutes)
    else:
        scheduled_time = datetime.now() + timedelta(minutes=delay_minutes)

    scheduled_queue.append({
        "user_id": user_id,
        "content": content,
        "time": scheduled_time
    })

    await safe_send(user_id, f"✅ پیام شما برای ساعت {scheduled_time.strftime('%H:%M')} زمان‌بندی شد.")

# حلقه بررسی ارسال پیام‌ها
async def scheduler_loop():
    while True:
        now = datetime.now()
        to_send = [item for item in scheduled_queue if item["time"] <= now]

        for item in to_send:
            await safe_send(item["user_id"], f"📩 پیام زمان‌بندی‌شده:\n{item['content']}")
            scheduled_queue.remove(item)

        await asyncio.sleep(10)  # بررسی هر ۱۰ ثانیه

# اجرای حلقه اصلی
async def main():
    asyncio.create_task(scheduler_loop())

    # شبیه‌سازی دریافت پیام‌ها
    class DummyMessage:
        def __init__(self, content, user_id):
            self.content = content
            self.author = type("Author", (), {"user_id": user_id})

    # تست دستی
    await on_message(DummyMessage("سلام", "user1"))
    await on_message(DummyMessage("تغییر زمان 5", "user1"))
    await on_message(DummyMessage("چطوری؟", "user1"))
    await on_message(DummyMessage("زمان", "user1"))

    # اجرای دائمی
    while True:
        await asyncio.sleep(1)

# شروع برنامه
asyncio.run(main())
