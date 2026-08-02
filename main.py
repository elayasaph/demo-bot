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
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Bots Lab_Demo Bot")
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
def get_google_sheet(worksheet_name=None):
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
    spreadsheet = client.open(SPREADSHEET_NAME)
    
    if worksheet_name:
        return spreadsheet.worksheet(worksheet_name)
    return spreadsheet.sheet1

# Вспомогательные функции для работы со слотами
def get_free_dates():
    try:
        sheet = get_google_sheet("Слоты")
        records = sheet.get_all_records()
        dates = sorted(list(set([r['Дата'] for r in records if str(r['Статус']).strip().lower() == 'свободно'])))
        return dates
    except Exception as e:
        logging.error(f"Error fetching free dates: {e}")
        return []

def get_free_times(selected_date):
    try:
        sheet = get_google_sheet("Слоты")
        records = sheet.get_all_records()
        times = [r['Время'] for r in records if str(r['Дата']) == str(selected_date) and str(r['Статус']).strip().lower() == 'свободно']
        return times
    except Exception as e:
        logging.error(f"Error fetching free times: {e}")
        return []

def book_slot(selected_date, selected_time, user_info):
    try:
        sheet = get_google_sheet("Слоты")
        records = sheet.get_all_records()
        
        # Находим нужную строку (учитываем +2 из-за заголовка и 1-based индексации)
        for i, r in enumerate(records):
            if str(r['Дата']) == str(selected_date) and str(r['Время']) == str(selected_time):
                if str(r['Статус']).strip().lower() == 'свободно':
                    row_number = i + 2
                    sheet.update_cell(row_number, 3, "Занято")
                    sheet.update_cell(row_number, 4, user_info)
                    return True
                else:
                    return False
        return False
    except Exception as e:
        logging.error(f"Error booking slot: {e}")
        return False

# --- BOT CONVERSATION STATES ---
NAME, PHONE, DIRECTION, SELECT_DATE, SELECT_TIME, OTHER_INPUT = range(6)

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
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
        
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

# --- CALLBACKS ДЛЯ НАВИГАЦИИ НАЗАД ---
async def back_to_name_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Возвращаемся назад.\n\nКак к вам обращаться? (Введите ваше имя)")
    return NAME

async def back_to_phone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_name")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Возвращаемся назад.\n\nУкажите ваш номер телефона для связи:", reply_markup=reply_markup)
    return PHONE

# --- ОБРАБОТКА НАПРАВЛЕНИЯ ---
async def get_direction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "dir_other":
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_direction")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Опишите ваш запрос или напишите ваш вариант:", reply_markup=reply_markup)
        return OTHER_INPUT

    if data == "dir_consult":
        dates = get_free_dates()
        if not dates:
            await query.edit_message_text(
                "К сожалению, сейчас нет свободных окон для записи на консультацию. 😔\n"
                "Мы свяжемся с вами для уточнения времени!"
            )
            return await finish_submission(update, context, "Консультация (без даты)")
        
        keyboard = [[InlineKeyboardButton(f"📅 {d}", callback_data=f"date_{d}")] for d in dates]
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_direction")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text("Выберите удобную дату для консультации:", reply_markup=reply_markup)
        return SELECT_DATE

    directions_map = {"dir_bot": "Разработка бота"}
    direction = directions_map.get(data, data)
    return await finish_submission(update, context, direction)

# --- ВЫБОР ДАТЫ И ВРЕМЕНИ ДЛЯ КОНСУЛЬТАЦИИ ---
async def select_date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    selected_date = query.data.replace("date_", "")
    context.user_data['selected_date'] = selected_date
    
    times = get_free_times(selected_date)
    if not times:
        await query.edit_message_text("На эту дату свободные окна закончились. Выберите другую дату.")
        return SELECT_DATE
        
    keyboard = [[InlineKeyboardButton(f"⏰ {t}", callback_data=f"time_{t}")] for t in times]
    keyboard.append([InlineKeyboardButton("⬅️ Назад к датам", callback_data="back_to_dates")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(f"Выбрана дата: **{selected_date}**\nВыберите удобное время:", reply_markup=reply_markup, parse_mode='Markdown')
    return SELECT_TIME

async def select_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    selected_time = query.data.replace("time_", "")
    selected_date = context.user_data.get('selected_date')
    
    user_name = context.user_data.get('name', 'Не указано')
    user_phone = context.user_data.get('phone', 'Не указано')
    user_obj = query.from_user
    username = f"@{user_obj.username}" if user_obj.username else "Нет юзернейма"
    
    user_info = f"{user_name} ({user_phone}, {username})"
    
    # Бронируем слот
    is_booked = book_slot(selected_date, selected_time, user_info)
    
    if is_booked:
        direction_text = f"Консультация: {selected_date} в {selected_time}"
        return await finish_submission(update, context, direction_text)
    else:
        await query.edit_message_text("Упс! Это время только что кто-то занял. Пожалуйста, выберите другое время.")
        return await get_direction_callback(update, context)

# --- ИТОГОВОЕ СОХРАНЕНИЕ И ОТПРАВКА ---
async def finish_submission(update: Update, context: ContextTypes.DEFAULT_TYPE, direction_text: str):
    user_name = context.user_data.get('name', 'Не указано')
    user_phone = context.user_data.get('phone', 'Не указано')
    
    if update.message:
        user_obj = update.message.from_user
    else:
        user_obj = update.callback_query.from_user

    username = f"@{user_obj.username}" if user_obj.username else "Нет юзернейма"

    # Запись в основную вкладку Google Таблицы
    try:
        sheet = get_google_sheet()
        sheet.append_row([user_name, user_phone, direction_text, username])
    except Exception as e:
        logging.error(f"Error writing to main Google Sheet: {e}")

    keyboard = [
        [InlineKeyboardButton("🔄 Подать новую заявку", callback_data="start_menu")],
        [InlineKeyboardButton("🌐 Наш Instagram", url=INSTAGRAM_URL)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    final_text = (
        "Спасибо! Ваша заявка успешно записана в Google Таблицу. ✨\n\n"
        "Мы свяжемся с вами в ближайшее время!"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(final_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(final_text, reply_markup=reply_markup)

    # Уведомление админу / менеджеру
    admin_message = (
        f"📥 **Новая заявка из демо-бота!**\n\n"
        f"👤 **Имя:** {user_name}\n"
        f"📞 **Телефон:** {user_phone}\n"
        f"🎯 **Направление / Запись:** {direction_text}\n"
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

async def get_other_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    custom_direction = f"Другое: {update.message.text}"
    return await finish_submission(update, context, custom_direction)

async def back_to_direction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await get_phone(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Заполнение заявки отменено.", reply_markup=ReplyKeyboardRemove())
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
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone),
                CallbackQueryHandler(back_to_name_callback, pattern="^back_to_name$")
            ],
            DIRECTION: [
                CallbackQueryHandler(get_direction_callback, pattern="^dir_"),
                CallbackQueryHandler(back_to_phone_callback, pattern="^back_to_phone$")
            ],
            SELECT_DATE: [
                CallbackQueryHandler(select_date_callback, pattern="^date_"),
                CallbackQueryHandler(back_to_direction_callback, pattern="^back_to_direction$")
            ],
            SELECT_TIME: [
                CallbackQueryHandler(select_time_callback, pattern="^time_"),
                CallbackQueryHandler(get_direction_callback, pattern="^back_to_dates$")
            ],
            OTHER_INPUT: [
                CallbackQueryHandler(back_to_direction_callback, pattern="^back_to_direction$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_other_text)
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
