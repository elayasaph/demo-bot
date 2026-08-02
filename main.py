import os
import json
import logging
from flask import Flask
from threading import Thread
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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
INSTAGRAM_URL = os.environ.get("INSTAGRAM_URL", "https://instagram.com")

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
    
    google_creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    
    if google_creds_json:
        creds_dict = json.loads(google_creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        
    client = gspread.authorize(creds)
    return client.open(SPREADSHEET_NAME).sheet1

# --- BOT CONVERSATION STATES (Добавлено состояние OTHER_INPUT) ---
NAME, PHONE, DIRECTION, OTHER_INPUT = range(4)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    
    text = (
        "Здравствуйте! 👋 Это демо-бот для приёма заявок.\n\n"
        "Как к вам обращаться? (Введите ваше имя)"
    )
    
    if update.message:
        await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text)
        
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text

    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_name")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Отлично! Укажите ваш номер телефона для связи:",
        reply_markup=reply_markup
    )
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("Разработка бота", callback_data="dir_bot")],
        [InlineKeyboardButton("Консультация", callback_data="dir_consult")],
        [InlineKeyboardButton("Другое", callback_data="dir_other")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_phone")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Выберите интересующее вас направление:",
        reply_markup=reply_markup
    )
    return DIRECTION

# Callback: Нажата кнопка «Назад» на этапе ввода телефона
async def back_to_name_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "Возвращаемся назад.\n\nКак к вам обращаться? (Введите ваше имя)"
    )
    return NAME

# Callback: Нажата кнопка «Назад» на этапе выбора направления
async def back_to_phone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_name")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "Возвращаемся назад.\n\nУкажите ваш номер телефона для связи:",
        reply_markup=reply_markup
    )
    return PHONE

# Общая функция завершения заявки и сохранения данных
async def finish_submission(update: Update, context: ContextTypes.DEFAULT_TYPE, direction_text: str):
    user_name = context.user_data.get('name', 'Не указано')
    user_phone = context.user_data.get('phone', 'Не указано')
    
    if update.message:
        user_obj = update.message.from_user
    else:
        user_obj = update.callback_query.from_user

    username = f"@{user_obj.username}" if user_obj.username else "Нет юзернейма"

    # 1. Запись в Google Таблицу
    try:
        sheet = get_google_sheet()
        sheet.append_row([user_name, user_phone, direction_text, username])
    except Exception as e:
        logging.error(f"Error writing to Google Sheet: {e}")

    # 2. Финальные кнопки
    keyboard = [
        [InlineKeyboardButton("🔄 Подать новую заявку", callback_data="start_menu")],
        [InlineKeyboardButton("🌐 Наш Instagram", url=INSTAGRAM_URL)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    final_text = (
        "Спасибо! Ваша заявка успешно записана в Google Таблицу. ✨\n\n"
        "Мы свяжемся с вами в ближайшее время!"
    )

    # 3. Отправка подтверждения пользователю
    if update.callback_query:
        await update.callback_query.edit_message_text(final_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(final_text, reply_markup=reply_markup)

    # 4. Уведомление админу
    admin_message = (
        f"📥 **Новая заявка из демо-бота!**\n\n"
        f"👤 **Имя:** {user_name}\n"
        f"📞 **Телефон:** {user_phone}\n"
        f"🎯 **Направление:** {direction_text}\n"
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

# Callback: Выбрано готовое направление или нажата кнопка «Другое»
async def get_direction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    # Если выбрана кнопка "Другое" — переводим на шаг ввода текста
    if data == "dir_other":
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_direction")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "Опишите ваш запрос или напишите ваш вариант:",
            reply_markup=reply_markup
        )
        return OTHER_INPUT

    # Если вы брали стандартный вариант
    directions_map = {
        "dir_bot": "Разработка бота",
        "dir_consult": "Консультация / Аудит"
    }
    direction = directions_map.get(data, data)
    return await finish_submission(update, context, direction)

# Состояние ввода своего варианта
async def get_other_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    custom_direction = f"Другое: {update.message.text}"
    return await finish_submission(update, context, custom_direction)

# Callback: Возврат к выбору направления с экрана ввода "Другое"
async def back_to_direction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("Разработка бота", callback_data="dir_bot")],
        [InlineKeyboardButton("Консультация / Аудит", callback_data="dir_consult")],
        [InlineKeyboardButton("Другое", callback_data="dir_other")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_phone")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "Выберите интересующее вас направление:",
        reply_markup=reply_markup
    )
    return DIRECTION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Заполнение заявки отменено.", 
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def main():
    keep_alive()

    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(start, pattern="^start_menu$")
        ],
        states={
            NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)
            ],
            PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone),
                CallbackQueryHandler(back_to_name_callback, pattern="^back_to_name$")
            ],
            DIRECTION: [
                CallbackQueryHandler(get_direction_callback, pattern="^dir_"),
                CallbackQueryHandler(back_to_phone_callback, pattern="^back_to_phone$")
            ],
            OTHER_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_other_text),
                CallbackQueryHandler(back_to_direction_callback, pattern="^back_to_direction$")
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(start, pattern="^start_menu$")
        ]
    )

    app_bot.add_handler(conv_handler)
    print("Бот запущен и готов к приёму заявок...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()
