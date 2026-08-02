import os
import logging
from flask import Flask
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIGURATION FROM ENVIRONMENT VARIABLES ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Demo_Bot_Leads")

# --- FLASK WEBSERVER FOR RENDERING / UPTIMEROBOT KEEP-ALIVE ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# --- GOOGLE SHEETS SETUP ---
def get_google_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    # Expects credentials.json in the same root folder
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    return client.open(SPREADSHEET_NAME).sheet1

# --- BOT CONVERSATION STATES ---
NAME, PHONE, DIRECTION = range(3)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Здравствуйте! 👋 Это демо-бот для приёма заявок.

"
        "Как к вам обращаться? (Введите ваше имя)"
    )
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Отлично! Укажите ваш номер телефона для связи:")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    
    reply_keyboard = [['Разработка бота', 'Консультация / Аудит', 'Другое']]
    await update.message.reply_text(
        "Выберите интересующее вас направление:",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, 
            one_time_keyboard=True, 
            resize_keyboard=True
        )
    )
    return DIRECTION

async def get_direction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = context.user_data['name']
    user_phone = context.user_data['phone']
    direction = update.message.text
    username = f"@{update.message.from_user.username}" if update.message.from_user.username else "Нет юзернейма"

    # 1. Append record into Google Sheet
    try:
        sheet = get_google_sheet()
        sheet.append_row([user_name, user_phone, direction, username])
    except Exception as e:
        logging.error(f"Error writing to Google Sheet: {e}")

    # 2. Reply to potential client
    await update.message.reply_text(
        "Спасибо! Ваша заявка успешно записана в Google Таблицу. ✨

"
        "Мы свяжемся с вами в ближайшее время!",
        reply_markup=ReplyKeyboardRemove()
    )

    # 3. Send notification to admin (You)
    admin_message = (
        f"📥 **Новая заявка из демо-бота!**

"
        f"👤 **Имя:** {user_name}
"
        f"📞 **Телефон:** {user_phone}
"
        f"🎯 **Направление:** {direction}
"
        f"💬 **Telegram:** {username}"
    )
    
    if ADMIN_CHAT_ID and ADMIN_CHAT_ID != "YOUR_TELEGRAM_CHAT_ID":
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID, 
                text=admin_message, 
                parse_mode='Markdown'
            )
        except Exception as e:
            logging.error(f"Error sending admin notification: {e}")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Заполнение заявки отменено.", 
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def main():
    # Start webserver to keep container awake & pass Render health check
    keep_alive()

    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            DIRECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_direction)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app_bot.add_handler(conv_handler)
    print("Бот запущен и готов приём заказов...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
