import logging
import base64
import io
import requests
import os
from datetime import datetime
from telegram import Update, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler, CallbackQueryHandler
import aiohttp
import aiofiles
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Импорт конфигураций
from config import (
    WELCOME_MESSAGE, HELP_MESSAGE, ANALYSIS_START_MESSAGE, ANALYSIS_COMPLETE_PREFIX,
    ERROR_MESSAGES, STARTUP_MESSAGES, TOKEN_ERROR_MESSAGES,
    FOOD_ANALYSIS_PROMPT, API_SETTINGS, SUBSCRIPTION_MESSAGES
)

# Импорт менеджера подписок
from subscription_manager import SubscriptionManager

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токены из переменных окружения
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# URL для OpenAI API
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

class CalorieAnalyzerBot:
    def __init__(self):
        self.application = None
        self.subscription_manager = SubscriptionManager()
        
        # Настройки платежей
        self.SUBSCRIPTION_PRICE_STARS = 1  # 1 звезда за месяц подписки
    
    async def check_user_access(self, user_id: int) -> bool:
        """Проверяет доступ пользователя к боту"""
        return self.subscription_manager.has_access(user_id)
    
    async def send_subscription_offer(self, update: Update):
        """Отправляет предложение оформить подписку"""
        keyboard = [[InlineKeyboardButton("💰 Оплатить подписку (1 ⭐)", callback_data="buy_subscription")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            SUBSCRIPTION_MESSAGES['no_access'],
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user_id = update.effective_user.id
        status = self.subscription_manager.get_user_status(user_id)
        
        # Отправляем приветственное сообщение
        await update.message.reply_text(WELCOME_MESSAGE)
        
        # Показываем статус доступа
        if status['is_whitelisted']:
            await update.message.reply_text(SUBSCRIPTION_MESSAGES['whitelist_user'])
        elif status['has_subscription']:
            expiry = status['subscription_expiry']
            expiry_str = expiry.strftime("%d.%m.%Y %H:%M") if expiry else "Неизвестно"
            await update.message.reply_text(
                SUBSCRIPTION_MESSAGES['subscription_active'].format(expiry_str)
            )
        else:
            await self.send_subscription_offer(update)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        await update.message.reply_text(HELP_MESSAGE)
    
    async def subscribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /subscribe"""
        user_id = update.effective_user.id
        status = self.subscription_manager.get_user_status(user_id)
        
        if status['is_whitelisted']:
            await update.message.reply_text(SUBSCRIPTION_MESSAGES['whitelist_user'])
        elif status['has_subscription']:
            expiry = status['subscription_expiry']
            expiry_str = expiry.strftime("%d.%m.%Y %H:%M") if expiry else "Неизвестно"
            await update.message.reply_text(
                SUBSCRIPTION_MESSAGES['subscription_active'].format(expiry_str)
            )
        else:
            await self.send_subscription_offer(update)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /status"""
        user_id = update.effective_user.id
        status = self.subscription_manager.get_user_status(user_id)
        
        if status['is_whitelisted']:
            await update.message.reply_text(SUBSCRIPTION_MESSAGES['whitelist_user'])
        elif status['has_subscription']:
            expiry = status['subscription_expiry']
            expiry_str = expiry.strftime("%d.%m.%Y %H:%M") if expiry else "Неизвестно"
            await update.message.reply_text(
                SUBSCRIPTION_MESSAGES['subscription_active'].format(expiry_str)
            )
        else:
            await self.send_subscription_offer(update)
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на inline кнопки"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "buy_subscription":
            await self.send_invoice(update, context)
    
    async def send_invoice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет счёт для оплаты подписки через Telegram Stars"""
        try:
            chat_id = update.effective_chat.id
            
            # Создаём счёт для Telegram Stars
            await context.bot.send_invoice(
                chat_id=chat_id,
                title="Подписка на Анализатор Калорий",
                description="Подписка на 30 дней для анализа калорий в фотографиях еды",
                payload="subscription_1_month",
                provider_token="",  # Пустой токен для Telegram Stars
                currency="XTR",  # Telegram Stars
                prices=[LabeledPrice("Подписка на месяц", self.SUBSCRIPTION_PRICE_STARS)],
                start_parameter="subscription",
                photo_url="https://i.ibb.co/7tQTNpb0/photo-2025-09-28-12-23-13.jpg",
                photo_size=512,
                photo_width=512,
                photo_height=512,
            )
        except Exception as e:
            logger.error(f"Ошибка отправки счёта: {e}")
            await update.effective_message.reply_text(SUBSCRIPTION_MESSAGES['payment_error'])
    
    async def precheckout_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик предварительной проверки платежа"""
        query = update.pre_checkout_query
        
        # Проверяем корректность платежа
        if query.invoice_payload == "subscription_1_month":
            await query.answer(ok=True)
        else:
            await query.answer(ok=False, error_message="Некорректный платёж")
    
    async def successful_payment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик успешного платежа"""
        payment = update.message.successful_payment
        user_id = update.effective_user.id
        
        if payment.invoice_payload == "subscription_1_month":
            # Добавляем подписку на 30 дней
            success = self.subscription_manager.add_subscription(user_id, 30)
            
            if success:
                await update.message.reply_text(SUBSCRIPTION_MESSAGES['payment_success'])
                logger.info(f"Подписка активирована для пользователя {user_id}")
            else:
                await update.message.reply_text(SUBSCRIPTION_MESSAGES['payment_error'])
                logger.error(f"Ошибка активации подписки для пользователя {user_id}")
        else:
            await update.message.reply_text(SUBSCRIPTION_MESSAGES['payment_error'])
    
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
        user_id = update.effective_user.id
        
        # Проверяем доступ пользователя
        if not await self.check_user_access(user_id):
            await self.send_subscription_offer(update)
            return
        
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
        user_id = update.effective_user.id
        
        # Проверяем доступ пользователя
        if not await self.check_user_access(user_id):
            await self.send_subscription_offer(update)
            return
        
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
        self.application.add_handler(CommandHandler("subscribe", self.subscribe_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        
        # Обработчики сообщений
        self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        
        # Обработчики платежей
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        self.application.add_handler(PreCheckoutQueryHandler(self.precheckout_callback))
        self.application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, self.successful_payment_callback))
        
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
    if not TELEGRAM_BOT_TOKEN:
        print(TOKEN_ERROR_MESSAGES['telegram_missing'])
        return
    
    if not OPENAI_API_KEY:
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
