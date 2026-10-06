import os
import asyncio
import threading
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import asyncpg
from fastapi import FastAPI
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.request import HTTPXRequest
from telegram.error import NetworkError, TimedOut, TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

STUDENT_BOT_TOKEN = os.getenv("STUDENT_BOT_TOKEN")
TEACHER_BOT_TOKEN = os.getenv("TEACHER_BOT_TOKEN")

# Teacher နှင့် Developer Chat ID များကို သီးခြားခွဲယူခြင်း
TEACHER_CHAT_ID = int(os.getenv("TEACHER_CHAT_ID", "0"))
HEAD_TEACHER_CHAT_ID = int(os.getenv("HEAD_TEACHER_CHAT_ID", "0"))
DEVELOPER_CHAT_ID = int(os.getenv("DEVELOPER_CHAT_ID", "0"))

# Notification ပို့ရန် စုစည်းထားသော Admin စာရင်း
ADMIN_IDS = [cid for cid in (TEACHER_CHAT_ID, DEVELOPER_CHAT_ID, HEAD_TEACHER_CHAT_ID) if cid != 0]

# Supabase Credentials (.env မှတဆင့် ခေါ်ယူခြင်း)
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME", "postgres")

MM_TZ = timezone(timedelta(hours=6, minutes=30))
db_pool = None

# ================= FastAPI Dummy Server (Render Health Check အတွက်) =================

app = FastAPI()

@app.get("/")
@app.head("/")
def health_check():
    return {"status": "active", "bot": "Student Bot is running successfully!"}

def run_fastapi():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

# ================= Database Helpers =================

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        min_size=1,
        max_size=5,
    )
    print("✅ Connected to Supabase Pooler.")

async def close_db():
    global db_pool
    if db_pool:
        await db_pool.close()

# ================= Bot Commands & Handlers =================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO students (student_id, student_name)
            VALUES ($1, $2)
            ON CONFLICT (student_id) DO UPDATE SET student_name = $2;
            """,
            user.id, user.first_name
        )

    text = (
        f"မင်္ဂလာပါ {user.first_name} 🙏\n\n"
        "ဤ Bot သည် နေ့စဉ် သတိပဋ္ဌာန်နှင့် စိတ်လေ့ကျင့်မှု (Mindfulness Routine) များကို မှတ်သားပေးမည့် Bot ဖြစ်ပါသည်။\n\n"
        "• မနက်ပိုင်း (5:00 AM - 12:00 PM)\n"
        "• နေ့လည်ပိုင်း (12:00 PM - 5:00 PM)\n"
        "• ညနေပိုင်း (5:00 PM - 12:00 AM)\n\n"
        "သတ်မှတ်ချိန်များတွင် အလုပ်စာရင်းများ ပို့ပေးပါမည်။ ပြီးစီးပါက Done ခလုတ်ကို နှိပ်ပေးပါခင်ဗျာ။\n"
        "သိလိုရာမေးခွန်း သို့မဟုတ် အတွေ့အကြုံများကိုလည်း အချိန်မရွေး စာရိုက်ပို့နိုင်ပါသည်။"
    )
    await update.message.reply_text(text)

async def handle_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "already_done":
        await query.answer("ဤအလုပ်ကို ပြီးစီးကြောင်း မှတ်သားပြီးဖြစ်ပါသည်ခင်ဗျာ။", show_alert=False)
        return

    if not data.startswith("done:"):
        return

    template_id = int(data.split(":")[1])
    user_id = query.from_user.id
    user_name = query.from_user.first_name
    today = datetime.now(MM_TZ).date()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO student_daily_logs (student_id, student_name, template_id, log_date, is_done, completed_at)
            VALUES ($1, $2, $3, $4, TRUE, NOW())
            ON CONFLICT (student_id, template_id, log_date)
            DO UPDATE SET is_done = TRUE, completed_at = NOW();
            """,
            user_id, user_name, template_id, today
        )

    updated_keyboard = [
        [InlineKeyboardButton("✅ ပြီးပါပြီ", callback_data="already_done")]
    ]
    try:
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(updated_keyboard)
        )
    except Exception as e:
        print(f"Callback edit error: {e}")

async def handle_student_qa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ကျောင်းသားက စာပို့ပါက DB တွင် သိမ်းပြီး ဆရာရော Developer ဆီပါ ခလုတ်များနှင့်တကွ ပို့ဆောင်ခြင်း"""
    user = update.effective_user
    text = update.message.text
    today = datetime.now(MM_TZ).date()
    print("Student message received:", text)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO student_reflections (student_id, student_name, log_date, reflection_text)
            VALUES ($1, $2, $3, $4);
            """,
            user.id, user.first_name, today, text
        )

    await update.message.reply_text("✅ ဆရာ့ထံ အကြောင်းကြားစာ ပို့လိုက်ပါပြီခင်ဗျာ။")

    if TEACHER_BOT_TOKEN and ADMIN_IDS:
        keyboard = [
            [
                InlineKeyboardButton("🌅 မနက်ပိုင်း ပို့မည်", callback_data=f"send_routine:morning:{user.id}"),
                InlineKeyboardButton("☀️ နေ့လည်ပိုင်း ပို့မည်", callback_data=f"send_routine:afternoon:{user.id}")
            ],
            [
                InlineKeyboardButton("🌙 ညနေပိုင်း ပို့မည်", callback_data=f"send_routine:evening:{user.id}")
            ]
        ]
        
        student_username = f"@{user.username}" if user.username else "မရှိပါ"
        # Markdown Error မတက်စေရန် parse_mode ကို ဖြုတ်ထားခြင်း သို့မဟုတ် စာသားကို သတိပြုခြင်း
        alert_msg = (
            f"📩 တပည့်ထံမှ စာ/တောင်းဆိုချက် ရောက်ရှိပါသည်\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 တပည့်: {user.first_name}\n"
            f"🆔 ID: {user.id}\n"
            f"🔗 Username: {student_username}\n\n"
            f"💬 စာသား:\n\"{text}\"\n\n"
            f"👉 အောက်ပါခလုတ်ကို နှိပ်၍ အဆိုပါတပည့်ထံ Checklist ချက်ချင်း ပို့နိုင်ပါသည် (သို့မဟုတ် /reply {user.id} ဖြင့် စာပြန်နိုင်ပါသည်)။"
        )

        try:
            # Bot Session ကို async with ဖြင့် သုံးခြင်းက ပို၍ လုံခြုံပြီး error ကင်းစေပါသည်
            async with Bot(token=TEACHER_BOT_TOKEN) as teacher_bot:
                for admin_id in ADMIN_IDS:
                    try:
                        await teacher_bot.send_message(
                            chat_id=admin_id,
                            text=alert_msg,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                            # parse_mode="Markdown" ကို ခေတ္တဖြုတ်ထားပါ (Special characters ကြောင့် error မတက်စေရန်)
                        )
                    except Exception as e:
                        print(f"Failed to notify admin {admin_id}: {e}")
        except Exception as e:
            print(f"Failed to initialize teacher_bot: {e}")

# ================= Routine Sender Helper =================

async def broadcast_routine(app, section_name: str, header_text: str, target_chat_id=None):
    today = datetime.now(MM_TZ).date()
    
    async with db_pool.acquire() as conn:
        if target_chat_id:
            students = [{"student_id": target_chat_id}]
        else:
            students = await conn.fetch("SELECT student_id FROM students;")

        tasks = await conn.fetch(
            "SELECT id, title, description FROM routine_templates WHERE section = $1 AND status = 'active' ORDER BY task_order ASC;",
            section_name
        )

    if not tasks or not students:
        return

    for stu in students:
        chat_id = stu["student_id"]
        
        async with db_pool.acquire() as conn:
            done_rows = await conn.fetch(
                "SELECT template_id FROM student_daily_logs WHERE student_id = $1 AND log_date = $2 AND is_done = TRUE;",
                chat_id, today
            )
        done_ids = {r["template_id"] for r in done_rows}

        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"{header_text}\n\nအောက်ပါ လေ့ကျင့်မှုများကို ပြုလုပ်ပြီးပါက သက်ဆိုင်ရာခလုတ်ကို နှိပ်ပေးပါခင်ဗျာ -",
                parse_mode="Markdown"
            )

            for idx, t in enumerate(tasks, start=1):
                t_id = t["id"]
                task_text = f"📌 *{idx}။ {t['title']}*"
                if t["description"]:
                    task_text += f"\n_{t['description']}_"

                if t_id in done_ids:
                    keyboard = [[InlineKeyboardButton("✅ ပြီးပါပြီ", callback_data="already_done")]]
                else:
                    keyboard = [[InlineKeyboardButton("လုပ်ဆောင်ပြီး (Done)", callback_data=f"done:{t_id}")]]

                await app.bot.send_message(
                    chat_id=chat_id,
                    text=task_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
        except Exception as e:
            print(f"Error sending individual routines to {chat_id}: {e}")

async def handle_dismiss_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    batch_id = query.data.split(":")[1]
    chat_id = query.message.chat_id

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT message_ids FROM routine_batch_logs WHERE batch_id = $1 AND student_id = $2;",
            batch_id, chat_id
        )

        if not row or not row["message_ids"]:
            await query.edit_message_text("စာရင်းဟောင်းများကို ရှာမတွေ့တော့ပါခင်ဗျာ။")
            return

        message_ids_to_delete = row["message_ids"]

        for msg_id in message_ids_to_delete:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except TelegramError:
                pass

        await conn.execute("DELETE FROM routine_batch_logs WHERE batch_id = $1;", batch_id)

    await context.bot.send_message(
        chat_id=chat_id,
        text="🗑️ ထပ်နေသော စာရင်းကို အောင်မြင်စွာ ပယ်ဖျက်ပြီးပါပြီခင်ဗျာ။"
    )

# ================= Main Runner =================

async def post_init(application):
    await init_db()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, (NetworkError, TimedOut)):
        print(f"⚠️ Network glitch ခေတ္တဖြစ်ပေါ်ပါသည်: {err}")
    else:
        print(f"❌ Error ဖြစ်ပေါ်ပါသည်: {err}")

def main():
    # 1. FastAPI server ကို background thread ဖြင့် စတင်ခြင်း (Render အတွက် Port ဖွင့်ရန်)
    server_thread = threading.Thread(target=run_fastapi, daemon=True)
    server_thread.start()
    print("🌐 FastAPI Dummy Server started in background thread.")

    # 2. Telegram Bot တည်ဆောက်ခြင်း
    request_config = HTTPXRequest(
        connection_pool_size=8,
        read_timeout=30.0,
        write_timeout=30.0,
        connect_timeout=30.0,
        pool_timeout=30.0
    )
    
    app_bot = (
        ApplicationBuilder()
        .token(STUDENT_BOT_TOKEN)
        .request(request_config)
        .post_init(post_init)
        .build()
    )

    app_bot.add_handler(CommandHandler("start", start_command))
    app_bot.add_handler(CallbackQueryHandler(handle_done_callback, pattern=r"^(done:|already_done)"))
    app_bot.add_handler(CallbackQueryHandler(handle_dismiss_batch, pattern=r"^dismiss_batch:"))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_student_qa))
    app_bot.add_error_handler(error_handler)

    print("🚀 Student Bot is starting polling...")
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
