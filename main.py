import logging
import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters, CallbackQueryHandler, ConversationHandler
)
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID")

POST_CONTENT, POST_TIME, POST_REPLY = range(3)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

conn = sqlite3.connect("posts.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    content TEXT,
    media TEXT,
    post_time TEXT,
    replies TEXT
)''')
conn.commit()

scheduler = BackgroundScheduler()
scheduler.start()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Hello! Your Telegram ID is {update.effective_user.id}")

async def new_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return
    context.user_data.clear()
    await update.message.reply_text("Send me the post text or media.")
    return POST_CONTENT

async def receive_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data['media'] = file_id
        context.user_data['content'] = update.message.caption or ""
    else:
        context.user_data['media'] = None
        context.user_data['content'] = update.message.text
    keyboard = [[InlineKeyboardButton("Pick Date", callback_data="calendar")]]
    await update.message.reply_text("Now choose the post time:", reply_markup=InlineKeyboardMarkup(keyboard))
    return POST_TIME

async def calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Send the datetime like 2025-06-08 10:00")
    return POST_TIME

async def receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dt = datetime.strptime(update.message.text, "%Y-%m-%d %H:%M")
    except ValueError:
        await update.message.reply_text("Invalid format. Use YYYY-MM-DD HH:MM")
        return POST_TIME
    context.user_data['post_time'] = dt.isoformat()
    await update.message.reply_text("Add comment replies (one per message). Send /done when finished.")
    context.user_data['replies'] = []
    return POST_REPLY

async def receive_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['replies'].append(update.message.text)
    return POST_REPLY

async def done_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("INSERT INTO posts (content, media, post_time, replies) VALUES (?, ?, ?, ?)", (
        context.user_data['content'],
        context.user_data['media'],
        context.user_data['post_time'],
        "||".join(context.user_data['replies'])
    ))
    conn.commit()
    post_id = cursor.lastrowid
    dt = datetime.fromisoformat(context.user_data['post_time'])
    scheduler.add_job(post_to_channel, 'date', run_date=dt, args=[post_id])
    await update.message.reply_text(f"Scheduled post #{post_id} at {dt}.")
    return ConversationHandler.END

async def post_to_channel(post_id: int):
    cursor.execute("SELECT content, media FROM posts WHERE id=?", (post_id,))
    row = cursor.fetchone()
    if not row:
        return
    content, media = row
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    async with app:
        if media:
            await app.bot.send_photo(chat_id=CHANNEL_ID, photo=media, caption=content)
        else:
            await app.bot.send_message(chat_id=CHANNEL_ID, text=content)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Post creation cancelled.")
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("newpost", new_post)],
        states={
            POST_CONTENT: [MessageHandler(filters.TEXT | filters.PHOTO, receive_content)],
            POST_TIME: [MessageHandler(filters.TEXT, receive_time), CallbackQueryHandler(calendar_callback)],
            POST_REPLY: [MessageHandler(filters.TEXT, receive_reply), CommandHandler("done", done_reply)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()
