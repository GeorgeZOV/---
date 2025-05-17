import os
import logging
from datetime import datetime
import sqlite3
import json
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler
)

# Конфигурация
YANDEX_API_KEY =  "AQVN12EocUPRqdocgo5kFDa3oebDDvPPf1kiyUfB"
TELEGRAM_TOKEN = "7456934610:AAHOGF-LTEBs_ptC6liELKmvcuX3XgB5OpU"

# Состояния диалога
SELECTING_ACTION, TYPING_TEXT, CHOOSING_LANG = range(3)


class DatabaseManager:
    def __init__(self, db_name='translator_bot.db'):
        self.db_name = db_name
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS user_context
                         (user_id INTEGER PRIMARY KEY,
                          context TEXT,
                          updated_at TIMESTAMP)''')

    def get_context(self, user_id):
        with sqlite3.connect(self.db_name) as conn:
            cur = conn.execute('SELECT context FROM user_context WHERE user_id=?', (user_id,))
            result = cur.fetchone()
            return json.loads(result[0]) if result else {}

    def update_context(self, user_id, context):
        with sqlite3.connect(self.db_name) as conn:
            conn.execute('''INSERT OR REPLACE INTO user_context 
                          (user_id, context, updated_at) VALUES (?, ?, ?)''',
                         (user_id, json.dumps(context), datetime.now()))


class YandexTranslator:
    BASE_URL = "https://translate.api.cloud.yandex.net/translate/v2/translate"

    def __init__(self, api_key):
        self.api_key = api_key

    async def translate_text(self, text, target_lang):
        try:
            headers = {
                "Authorization": f"Api-Key {self.api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "texts": [text],
                "targetLanguageCode": target_lang
            }

            response = requests.post(self.BASE_URL, json=data, headers=headers)
            response.raise_for_status()

            return response.json()['translations'][0]['text']
        except Exception as e:
            logging.error(f"Translation error: {str(e)}")
            return None


# Инициализация компонентов
db = DatabaseManager()
translator = YandexTranslator(YANDEX_API_KEY)


# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    await update.message.reply_text(
        f"Привет {user.first_name}! Я бот-переводчик.\n"
        "Используйте /translate для начала перевода"
    )
    return SELECTING_ACTION


async def start_translation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите текст для перевода:")
    return TYPING_TEXT


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    # Сохраняем текст в контекст
    context_data = {'text': text}
    db.update_context(user_id, context_data)

    # Создаем клавиатуру с выбором языка
    keyboard = [
        [InlineKeyboardButton("Английский", callback_data='en'),
         InlineKeyboardButton("Немецкий", callback_data='de')],
        [InlineKeyboardButton("Французский", callback_data='fr'),
         InlineKeyboardButton("Испанский", callback_data='es')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("Выберите язык перевода:", reply_markup=reply_markup)
    return CHOOSING_LANG


async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    target_lang = query.data

    # Получаем сохраненный текст
    context_data = db.get_context(user_id)
    text = context_data.get('text', '')

    if not text:
        await query.edit_message_text("Ошибка: текст не найден. Начните заново.")
        return ConversationHandler.END

    # Выполняем перевод
    translated = await translator.translate_text(text, target_lang)
    if not translated:
        await query.edit_message_text("⚠️ Ошибка перевода. Попробуйте позже.")
        return ConversationHandler.END

    await query.edit_message_text(
        f"🔤 Оригинал: {text}\n\n"
        f"🌍 Перевод ({target_lang}): {translated}"
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Диалог прерван')
    return ConversationHandler.END


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Ошибка: {context.error}")
    await update.message.reply_text("⚠️ Произошла ошибка. Попробуйте еще раз.")


def main():
    # Настройка логгирования
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    # Создание приложения
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Диалог перевода
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('translate', start_translation)],
        states={
            TYPING_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text)],
            CHOOSING_LANG: [CallbackQueryHandler(choose_language)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Регистрация обработчиков
    application.add_handler(CommandHandler('start', start))
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    # Запуск бота
    application.run_polling()


if __name__ == '__main__':
    main()