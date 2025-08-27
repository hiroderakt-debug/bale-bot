import asyncio
import os
from datetime import datetime, timedelta
from collections import deque
from bale import Bot, Message, InputFile
import bale.error
import aiohttp
from fastapi import FastAPI
import uvicorn
import threading
import time
import re

# تنظیمات اولیه
delay_minutes = 20
paused = False
edit_mode = {}  # user_id -> message_id در حال ویرایش
cancelled_messages = set()  # برای پیگیری پیام‌های لغو شده

bot = Bot(token="347447058:s19i9J3UPZLUrprUqrH12UYD1lDGcPPi1ulV9iFL")
send_queue = asyncio.Queue()
scheduled_queue = deque()  # هر آیتم: (message, scheduled_time, caption, remaining_seconds)
sent_messages = {}  # message_id: {"bale_message_id": xxx, "chat_id": "@hiromce", "views_threshold": None}
special_ads = {}  # برای تبلیغات ویژه: message_id -> {"times": 5, "sent_count": 0, "original_message": message, "forwarded_messages": []}

# وب‌سرور FastAPI
app = FastAPI()

@app.get("/")
def ping():
    return {"status": "ok"}

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

async def safe_send(chat_id: int, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except bale.error.Forbidden:
        print(f"❌ ارسال پیام به کاربر {chat_id} ممکن نیست.")

async def safe_delete(chat_id: str, message_id: int):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except Exception as e:
        print(f"❌ خطا در حذف پیام: {e}")
        return False

@bot.event
async def on_ready():
    print("✅ ربات آماده است.")
    asyncio.create_task(process_queue())
    asyncio.create_task(log_remaining_times())
    asyncio.create_task(keep_alive())
    asyncio.create_task(monitor_views())  # مانیتورینگ ویوها
    asyncio.create_task(process_special_ads())  # پردازش تبلیغات ویژه

@bot.event
async def on_message(message: Message):
    global scheduled_queue, delay_minutes, paused, edit_mode, cancelled_messages

    if getattr(message.chat, "type", None) != "private":
        # بررسی دستورات ویو در چنل (فقط ویو، لغو ویو حذف شد)
        if message.chat.type == "channel" and message.chat.username == "hiromce":
            await handle_view_commands(message)
        return
        
    if message.author.username != "heroderact":
        return

    user_id = message.author.user_id
    content = message.content.strip()

    # حالت ویرایش متن
    if user_id in edit_mode:
        target_id = edit_mode[user_id]
        for i, (msg, time, caption, remaining) in enumerate(scheduled_queue):
            if msg.message_id == target_id:
                scheduled_queue[i] = (msg, time, content, remaining)
                await safe_send(user_id, "✏️ متن پیام با موفقیت ویرایش شد.")
                del edit_mode[user_id]
                return
        await safe_send(user_id, "⚠️ پیام موردنظر برای ویرایش پیدا نشد.")
        del edit_mode[user_id]
        return

    # توقف ارسال‌ها
    if content.lower() == "توقف":
        paused = True
        # ذخیره زمان باقیمانده برای همه پیام‌ها
        now = datetime.now()
        for i, (msg, scheduled_time, caption, _) in enumerate(scheduled_queue):
            remaining_seconds = (scheduled_time - now).total_seconds()
            if remaining_seconds > 0:
                scheduled_queue[i] = (msg, scheduled_time, caption, remaining_seconds)
        await safe_send(user_id, "⛔ ارسال پیام‌ها متوقف شد.")
        return

    # ادامه ارسال‌ها
    if content.lower() == "ادامه":
        paused = False
        # به روزرسانی زمان‌های برنامه‌ریزی شده با زمان باقیمانده ذخیره شده
        now = datetime.now()
        for i, (msg, old_time, caption, remaining_seconds) in enumerate(scheduled_queue):
            if remaining_seconds is not None and remaining_seconds > 0:
                new_time = now + timedelta(seconds=remaining_seconds)
                scheduled_queue[i] = (msg, new_time, caption, None)
        await safe_send(user_id, "▶️ ارسال پیام‌ها ادامه پیدا می‌کند.")
        return

    # لغو پیام
    if message.reply_to_message and content.lower() == "لغو":
        reply_id = message.reply_to_message.message_id
        # اضافه کردن به لیست پیام‌های لغو شده
        cancelled_messages.add(reply_id)
        # حذف از صف زمان‌بندی شده
        scheduled_queue = deque([
            (msg, time, caption, remaining) for msg, time, caption, remaining in scheduled_queue if msg.message_id != reply_id
        ])
        await safe_send(user_id, "❌ پیام با موفقیت لغو شد.")
        return

    # نمایش زمان باقی‌مانده
    if message.reply_to_message and content.lower() == "زمان":
        reply_id = message.reply_to_message.message_id
        for msg, scheduled_time, _, remaining_seconds in scheduled_queue:
            if msg.message_id == reply_id:
                if paused and remaining_seconds is not None:
                    # هنگام توقف، زمان باقیمانده ثابت است
                    remaining = timedelta(seconds=remaining_seconds)
                    await safe_send(user_id, f"⏸️ زمان باقیمانده (متوقف شده): {format_remaining_time(remaining)}")
                else:
                    # هنگام اجرا، زمان باقیمانده محاسبه می‌شود
                    remaining = scheduled_time - datetime.now()
                    if remaining.total_seconds() > 0:
                        await safe_send(user_id, format_remaining_time(remaining))
                    else:
                        await safe_send(user_id, "✅ این رسانه در حال ارسال یا ارسال شده است.")
                return
        await safe_send(user_id, "❌ این پیام در صف ارسال نیست یا قبلاً ارسال شده.")
        return

    # حذف کل صف
    if content.lower() == "حذف":
        # اضافه کردن همه پیام‌های صف به لیست لغو شده
        for msg, _, _, _ in scheduled_queue:
            cancelled_messages.add(msg.message_id)
        scheduled_queue.clear()
        await safe_send(user_id, "🗑️ کل صف حذف شد.")
        return

    # تغییر زمان تأخیر
    if content.lower().startswith("تغییر زمان"):
        try:
            parts = content.split()
            if len(parts) == 3:
                delay_minutes = int(parts[2])
                await safe_send(user_id, f"⏱️ زمان تأخیر به {delay_minutes} دقیقه تغییر یافت.")
            else:
                await safe_send(user_id, "⚠️ فرمت صحیح: تغییر زمان [عدد]")
        except ValueError:
            await safe_send(user_id, "⚠️ لطفاً عدد معتبر وارد کنید.")
        return

    # ویرایش متن پیام
    if message.reply_to_message and content.lower() == "ویرایش":
        reply_id = message.reply_to_message.message_id
        for msg, _, _, _ in scheduled_queue:
            if msg.message_id == reply_id:
                edit_mode[user_id] = reply_id
                await safe_send(user_id, "📝 لطفاً متن جدید را ارسال کنید.")
                return
        await safe_send(user_id, "⚠️ این پیام در صف نیست یا قبلاً ارسال شده.")
        return

    # لغو ویو (حذف خودکار) - فقط در چت خصوصی
    if message.reply_to_message and content.lower() == "لغو ویو":
        reply_id = message.reply_to_message.message_id
        if reply_id in sent_messages:
            sent_messages[reply_id]["views_threshold"] = None
            await safe_send(user_id, "✅ تنظیمات حذف خودکار لغو شد.")
        else:
            await safe_send(user_id, "⚠️ این پیام پیدا نشد یا قبلاً حذف شده است.")
        return

    # تبلیغ ویژه (ارسال خودکار در ساعت ۱۲ شب)
    if message.reply_to_message and content.lower().startswith("تبلیغ ویژه"):
        reply_id = message.reply_to_message.message_id
        
        # استخراج تعداد دفعات از پیام
        times = 5  # مقدار پیش‌فرض
        parts = content.split()
        if len(parts) >= 3:
            try:
                times = int(parts[2])
            except ValueError:
                await safe_send(user_id, "⚠️ لطفاً عدد معتبر وارد کنید. مثال: تبلیغ ویژه 3")
                return
        
        # ذخیره پیام برای ارسال خودکار
        special_ads[reply_id] = {
            "times": times,
            "sent_count": 0,
            "original_message": message.reply_to_message,
            "caption": message.reply_to_message.content or "",
            "forwarded_messages": []  # لیست پیام‌های فوروارد شده
        }
        
        await safe_send(user_id, f"✅ تبلیغ ویژه تنظیم شد. این پیام {times} بار هر شب ساعت ۱۲ فوروارد خواهد شد و در پایان همه پیام‌ها (اصلی و فورواردها) حذف خواهند شد.")
        return

    # زمان‌بندی پیام جدید
    if scheduled_queue:
        last_scheduled_time = scheduled_queue[-1][1]
        scheduled_time = last_scheduled_time + timedelta(minutes=delay_minutes)
    else:
        scheduled_time = datetime.now() + timedelta(minutes=delay_minutes)

    scheduled_queue.append((message, scheduled_time, content, None))
    await send_queue.put(message)

async def handle_view_commands(message: Message):
    """مدیریت دستورات ویو در چنل (فقط دستور ویو، لغو ویو حذف شد)"""
    if not message.reply_to_message:
        return
        
    content = message.content.strip().lower()
    reply_id = message.reply_to_message.message_id
    
    if content.startswith("ویو"):
        try:
            # استخراج عدد از دستور (مثلاً "ویو 100")
            parts = content.split()
            if len(parts) >= 2:
                views_threshold = int(parts[1])
                
                # ذخیره تنظیمات حذف خودکار
                if reply_id in sent_messages:
                    sent_messages[reply_id]["views_threshold"] = views_threshold
                    await safe_delete(message.chat.id, message.message_id)  # حذف دستور ویو
                    await bot.send_message(chat_id=message.author.user_id, 
                                         text=f"✅ پست بعد از رسیدن به {views_threshold} ویو حذف خواهد شد.")
                else:
                    await safe_delete(message.chat.id, message.message_id)  # حذف دستور ویو
                    await bot.send_message(chat_id=message.author.user_id, 
                                         text="⚠️ پیام موردنظر پیدا نشد.")
        except ValueError:
            await safe_delete(message.chat.id, message.message_id)  # حذف دستور ویو
            await bot.send_message(chat_id=message.author.user_id, 
                                 text="⚠️ لطفاً عدد معتبر وارد کنید. مثال: ویو 100")

async def process_special_ads():
    """پردازش تبلیغات ویژه و فوروارد خودکار در ساعت ۱۲ شب"""
    while True:
        try:
            now = datetime.now()
            
            # بررسی اگر ساعت ۱۲ شب است
            if now.hour == 0 and now.minute == 0:
                ads_to_remove = []
                
                for msg_id, ad_info in list(special_ads.items()):
                    if ad_info["sent_count"] < ad_info["times"]:
                        try:
                            # فوروارد پیام از چنل
                            forwarded_msg = await bot.forward_message(
                                chat_id="@hiromce",
                                from_chat_id="@hiromce",
                                message_id=msg_id
                            )
                            
                            # ذخیره پیام فوروارد شده برای حذف بعدی
                            ad_info["forwarded_messages"].append(forwarded_msg.message_id)
                            ad_info["sent_count"] += 1
                            
                            print(f"✅ تبلیغ ویژه فوروارد شد ({ad_info['sent_count']}/{ad_info['times']})")
                            
                        except Exception as e:
                            print(f"❌ خطا در فوروارد تبلیغ ویژه: {e}")
                    
                    # اگر تعداد ارسال‌ها کامل شده، حذف همه پیام‌های فوروارد شده و پیام اصلی
                    if ad_info["sent_count"] >= ad_info["times"]:
                        # حذف همه پیام‌های فوروارد شده
                        for fwd_msg_id in ad_info["forwarded_messages"]:
                            try:
                                await safe_delete("@hiromce", fwd_msg_id)
                                print(f"✅ پیام فوروارد شده حذف شد: {fwd_msg_id}")
                            except Exception as e:
                                print(f"❌ خطا در حذف پیام فوروارد شده: {e}")
                        
                        # حذف پیام اصلی
                        try:
                            await safe_delete("@hiromce", msg_id)
                            print(f"✅ پیام اصلی حذف شد: {msg_id}")
                        except Exception as e:
                            print(f"❌ خطا در حذف پیام اصلی: {e}")
                        
                        # اطلاع به کاربر
                        try:
                            await safe_send(ad_info["original_message"].author.user_id, 
                                          f"✅ تبلیغ ویژه کامل شد. همه پیام‌ها (اصلی و فورواردها) حذف شدند.")
                        except:
                            pass
                        
                        ads_to_remove.append(msg_id)
                        print(f"✅ تبلیغ ویژه کامل شد و همه پیام‌ها حذف شدند.")
                
                # حذف تبلیغات کامل شده
                for msg_id in ads_to_remove:
                    if msg_id in special_ads:
                        del special_ads[msg_id]
        
        except Exception as e:
            print(f"❌ خطا در پردازش تبلیغات ویژه: {e}")
        
        # چک کردن هر دقیقه
        await asyncio.sleep(60)

async def process_queue():
    global scheduled_queue, paused, cancelled_messages

    while True:
        message = await send_queue.get()
        
        # بررسی لغو پیام قبل از پردازش
        if message.message_id in cancelled_messages:
            cancelled_messages.discard(message.message_id)
            continue

        user_id = message.author.user_id

        # پیدا کردن اطلاعات مربوط به پیام
        caption = ""
        scheduled_time = None
        remaining_seconds = None
        for msg, time, cap, rem in scheduled_queue:
            if msg.message_id == message.message_id:
                scheduled_time = time
                caption = cap
                remaining_seconds = rem
                break

        if scheduled_time:
            now = datetime.now()
            
            if remaining_seconds is not None and paused:
                # اگر توقف فعال است و زمان باقیمانده ذخیره شده است
                wait_seconds = remaining_seconds
            else:
                # محاسبه زمان باقیمانده معمولی
                wait_seconds = (scheduled_time - now).total_seconds()
            
            # اگر پیام لغو شده باشد، منتظر نمان
            if wait_seconds > 0:
                while wait_seconds > 0 and message.message_id not in cancelled_messages:
                    # چک کردن وضعیت توقف هر 1 ثانیه
                    await asyncio.sleep(min(1, wait_seconds))
                    
                    if paused:
                        # اگر توقف فعال است، زمان باقیمانده را ذخیره و منتظر بمان
                        for i, (msg, time, cap, rem) in enumerate(scheduled_queue):
                            if msg.message_id == message.message_id:
                                scheduled_queue[i] = (msg, time, cap, wait_seconds)
                                break
                        # منتظر بمان تا توقف غیرفعال شود
                        while paused and message.message_id not in cancelled_messages:
                            await asyncio.sleep(1)
                        # اگر پیام لغو شده باشد، پردازش نکن
                        if message.message_id in cancelled_messages:
                            break
                    else:
                        # کاهش زمان باقیمانده
                        now = datetime.now()
                        wait_seconds = (scheduled_time - now).total_seconds()
                
                # اگر پیام لغو شده باشد، پردازش نکن
                if message.message_id in cancelled_messages:
                    cancelled_messages.discard(message.message_id)
                    continue

        # اگر pause فعال باشد، منتظر بمان
        while paused and message.message_id not in cancelled_messages:
            await asyncio.sleep(1)
        
        # اگر پیام لغو شده باشد، پردازش نکن
        if message.message_id in cancelled_messages:
            cancelled_messages.discard(message.message_id)
            continue
            
        # ارسال پیام
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

        # حذف پیام از صف بدون توجه به اینکه ارسال شده یا نه
        scheduled_queue = deque([
            (msg, time, cap, rem) for msg, time, cap, rem in scheduled_queue if msg.message_id != message.message_id
        ])

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
        for msg, scheduled_time, _, remaining_seconds in scheduled_queue:
            if paused and remaining_seconds is not None:
                print(f"⏸️ پیام {msg.message_id} از کاربر {msg.author.user_id} متوقف شده است. زمان باقیمانده: {remaining_seconds} ثانیه")
            else:
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
        except Exception as e:
            print(f"⚠️ خطا در پینگ داخلی: {e}")
        
        await asyncio.sleep(20*60)

if __name__ == "__main__":
    print("🤖 ربات در حال اجرا...")
    threading.Thread(target=run_web_server).start()
    bot.run()

