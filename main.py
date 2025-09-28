import logging
import base64
import io
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import aiohttp
import aiofiles

# Импорт конфигураций
from config import (
    WELCOME_MESSAGE, HELP_MESSAGE, ANALYSIS_START_MESSAGE, ANALYSIS_COMPLETE_PREFIX,
    ERROR_MESSAGES, STARTUP_MESSAGES, TOKEN_ERROR_MESSAGES,
    FOOD_ANALYSIS_PROMPT, API_SETTINGS
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токены - замените на ваши настоящие токены
TELEGRAM_BOT_TOKEN = ""
OPENAI_API_KEY = ""  # Замените на ваш OpenAI API ключ

# URL для OpenAI API
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

class CalorieAnalyzerBot:
    def __init__(self):
        self.application = None
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        await update.message.reply_text(WELCOME_MESSAGE)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        await update.message.reply_text(HELP_MESSAGE)
    
    async def analyze_food_image(self, image_data: bytes) -> str:
        """Анализ изображения через OpenAI GPT-4 Vision API"""
        try:
            # Кодируем изображение в base64
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": API_SETTINGS['model'],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": FOOD_ANALYSIS_PROMPT
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}",
                                    "detail": API_SETTINGS['image_detail']
                                }
                            }
                        ]
                    }
                ],
                "max_completion_tokens": API_SETTINGS['max_completion_tokens'],
                "temperature": API_SETTINGS['temperature']
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(OPENAI_API_URL, json=payload, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result['choices'][0]['message']['content']
                    else:
                        error_text = await response.text()
                        logger.error(f"OpenAI API error: {response.status}, {error_text}")
                        return ERROR_MESSAGES['api_error']
                        
        except Exception as e:
            logger.error(f"Error in analyze_food_image: {str(e)}")
            return ERROR_MESSAGES['general_error']
    
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик фотографий"""
        try:
            # Отправляем сообщение о начале анализа
            analysis_message = await update.message.reply_text(ANALYSIS_START_MESSAGE)
            
            # Получаем файл фотографии
            photo = update.message.photo[-1]  # Берем самое большое разрешение
            file = await context.bot.get_file(photo.file_id)
            
            # Загружаем изображение в память
            image_data = await file.download_as_bytearray()
            
            # Анализируем изображение
            analysis_result = await self.analyze_food_image(bytes(image_data))
            
            # Обновляем сообщение с результатом
            final_message = f"{ANALYSIS_COMPLETE_PREFIX}{analysis_result}"
            await analysis_message.edit_text(final_message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in handle_photo: {str(e)}")
            await update.message.reply_text(ERROR_MESSAGES['photo_processing'])
    
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений"""
        await update.message.reply_text(ERROR_MESSAGES['not_photo_message'])
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        logger.error(f"Exception while handling an update: {context.error}")
        
        if update and update.message:
            await update.message.reply_text(ERROR_MESSAGES['unexpected_error'])
    
    def setup_handlers(self):
        """Настройка обработчиков"""
        # Команды
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # Обработчики сообщений
        self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        
        # Обработчик ошибок
        self.application.add_error_handler(self.error_handler)
    
    def run(self):
        """Запуск бота"""
        # Создаем приложение
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Настраиваем обработчики
        self.setup_handlers()
        
        logger.info(STARTUP_MESSAGES['bot_starting'])
        logger.info(STARTUP_MESSAGES['instruction'])
        
        # Запускаем бота - run_polling управляет всем жизненным циклом
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    """Главная функция"""
    # Проверяем наличие токенов
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print(TOKEN_ERROR_MESSAGES['telegram_missing'])
        return
    
    if OPENAI_API_KEY == "YOUR_OPENAI_API_KEY_HERE":
        print(TOKEN_ERROR_MESSAGES['openai_missing'])
        return
    
    # Создаем и запускаем бота
    bot = CalorieAnalyzerBot()
    
    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info(STARTUP_MESSAGES['user_stopped'])
    except Exception as e:
        logger.error(f"{TOKEN_ERROR_MESSAGES['critical_error_prefix']}{str(e)}")

if __name__ == "__main__":
    main()
