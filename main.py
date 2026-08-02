import os
import json
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
BOT_TOKEN = os.environ.get("TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("TELEGRAM_ID", "YOUR_TELEGRAM_CHAT_ID")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Bots Lab_ Demo Bot")

# --- FLASK WEBSERVER FOR RENDER / UPTIMEROBOT KEEP-ALIVE ---
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
    
    # Сначала пробуем взять ключ из переменной окружения Render
    google_creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    
    if google_creds_json:
        # Для Render
        creds_dict = json.loads(google_creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        # Для локальной проверки на вашем компьютере
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
        "Здравствуйте!👋\n"
        "Это демо-бот для приёма заявок.\n"
        "Как к вам обращаться? (Введите ваше имя)"
    )
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    context.user_data['name'] = text

    # На шаге ввода телефона добавляем меню с кнопкой «Назад»
    reply_keyboard = [['⬅️ Назад']]
    await update.message.reply_text(
        "Отлично! Укажите ваш номер телефона для связи в формате +77XX XXX XX XX:",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, 
            resize_keyboard=True, 
            one_time_keyboard=True
        )
    )
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    # Если пользователь нажал «Назад» при вводе телефона
    if text == '⬅️ Назад':
        await update.message.reply_text(
            "Возвращаемся назад.\n\nКак к вам обращаться? (Введите ваше имя)",
            reply_markup=ReplyKeyboardRemove()
        )
        return NAME

    context.user_data['phone'] = text
    
    # Кнопки выбора направления + кнопка «Назад»
    reply_keyboard = [
        ['Разработка бота'],
        ['Консультация'],
        ['Другое'],
        ['⬅️ Назад']
    ]
    
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
    text = update.message.text

    # Если пользователь нажал «Назад» при выборе направления
    if text == '⬅️ Назад':
        reply_keyboard = [['⬅️ Назад']]
        await update.message.reply_text(
            "Возвращаемся назад.\n\nУкажите ваш номер телефона для связи:",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, 
                resize_keyboard=True, 
                one_time_keyboard=True
            )
        )
        return PHONE

    user_name = context.user_data.get('name', 'Не указано')
    user_phone = context.user_data.get('phone', 'Не указано')
    direction = text
    username = f"@{update.message.from_user.username}" if update.message.from_user.username else "Нет юзернейма"

    # 1. Запись в Google Таблицу
    try:
        sheet = get_google_sheet()
        sheet.append_row([user_name, user_phone, direction, username])
    except Exception as e:
        logging.error(f"Error writing to Google Sheet: {e}")

    # 2. Ответ пользователю
    await update.message.reply_text(
        "Спасибо! Ваша заявка успешно записана в Google Таблицу. ✨\n\n"
        "Мы свяжемся с вами в ближайшее время!",
        reply_markup=ReplyKeyboardRemove()
    )

    # 3. Уведомление админу
    admin_message = (
        f"📥 **Новая заявка из демо-бота!**\n\n"
        f"👤 **Имя:** {user_name}\n"
        f"📞 **Телефон:** {user_phone}\n"
        f"🎯 **Направление:** {direction}\n"
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
    # 3. Send notification to admin
    admin_message = (
        f"📥 **Новая заявка из демо-бота!**\n\n"
        f"👤 **Имя:** {user_name}\n"
        f"📞 **Телефон:** {user_phone}\n"
        f"🎯 **Направление:** {direction}\n"
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
    print("Бот запущен и готов к приёму заявок...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
