import logging
import logging.handlers
import base64
import io
import requests
import os
import asyncio
from datetime import datetime, timedelta
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

# Импорт менеджера платежей
from payment_manager import PaymentManager

# Создаем директорию для логов, если её нет
os.makedirs('logs', exist_ok=True)

# Настройка логирования с записью в файл и консоль
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Формат логирования
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Обработчик для консоли
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

# Обработчик для файла с ротацией (максимум 10MB, хранить 5 файлов)
file_handler = logging.handlers.RotatingFileHandler(
    'logs/bot.log',
    maxBytes=10*1024*1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

# Добавляем обработчики к логгеру
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# Настраиваем root logger для других модулей
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[console_handler, file_handler]
)

# Токены из переменных окружения
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# URL для OpenAI API
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

class CalorieAnalyzerBot:
    def __init__(self):
        self.application = None
        self.subscription_manager = SubscriptionManager()
        self.payment_manager = PaymentManager()
        
        # Настройки платежей
        self.SUBSCRIPTION_PRICE_STARS = 1  # 1 звезда за месяц подписки
        self.SUBSCRIPTION_PRICE_RUB = float(os.getenv("SUBSCRIPTION_PRICE_RUB", "150.00"))
        
        # Хранилище для отслеживания платежей YooKassa
        # payment_id -> {'user_id': int, 'created_at': datetime, 'notified': bool}
        self.pending_payments = {}
        
        # Настройки проверки платежей
        self.PAYMENT_CHECK_INTERVAL = int(os.getenv("PAYMENT_CHECK_INTERVAL", "60"))  # секунды
        self.PAYMENT_TIMEOUT = int(os.getenv("PAYMENT_TIMEOUT", "3600"))  # 1 час по умолчанию
        
        # Задача периодической проверки
        self.payment_check_task = None
    
    async def check_user_access(self, user_id: int) -> bool:
        """Проверяет доступ пользователя к боту"""
        return self.subscription_manager.has_access(user_id)
    
    async def send_subscription_offer(self, update: Update):
        """Отправляет предложение оформить подписку с выбором способа оплаты"""
        keyboard = [
            [InlineKeyboardButton("⭐ Telegram Stars (1 ⭐)", callback_data="payment_method_stars")],
            [InlineKeyboardButton("💳 Банковская карта (150 ₽)", callback_data="payment_method_card")]
        ]
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
        
        # Выбор способа оплаты
        if query.data == "payment_method_stars":
            await self.send_stars_invoice(update, context)
        elif query.data == "payment_method_card":
            await self.send_card_payment_link(update, context)
        # Старая кнопка для обратной совместимости
        elif query.data == "buy_subscription":
            await self.show_payment_methods(update, context)
    
    async def show_payment_methods(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает выбор способа оплаты"""
        keyboard = [
            [InlineKeyboardButton("⭐ Telegram Stars (1 ⭐)", callback_data="payment_method_stars")],
            [InlineKeyboardButton("💳 Банковская карта (150 ₽)", callback_data="payment_method_card")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            SUBSCRIPTION_MESSAGES['payment_method_selection'],
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def send_stars_invoice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет счёт для оплаты подписки через Telegram Stars"""
        try:
            chat_id = update.effective_chat.id
            
            # Удаляем предыдущее сообщение с кнопками
            try:
                await update.callback_query.message.delete()
            except:
                pass
            
            # Создаём счёт для Telegram Stars
            await context.bot.send_invoice(
                chat_id=chat_id,
                title="Подписка на Анализатор Калорий",
                description="Подписка на 30 дней для анализа калорий в фотографиях еды",
                payload="subscription_1_month_stars",
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
            logger.error(f"Ошибка отправки счёта Telegram Stars: {e}")
            await update.effective_chat.send_message(SUBSCRIPTION_MESSAGES['payment_error'])
    
    async def send_card_payment_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Создаёт и отправляет ссылку для оплаты через YooMoney (карта)"""
        try:
            user_id = update.effective_user.id
            
            # Проверяем, доступна ли оплата через YooKassa
            if not self.payment_manager.is_enabled():
                await update.callback_query.edit_message_text(
                    SUBSCRIPTION_MESSAGES['yoomoney_not_configured'],
                    parse_mode='Markdown'
                )
                return
            
            # Удаляем предыдущее сообщение с кнопками
            try:
                await update.callback_query.message.delete()
            except:
                pass
            
            # Создаём платеж
            bot_username = (await context.bot.get_me()).username
            return_url = f"https://t.me/{bot_username}"
            
            payment_data = self.payment_manager.create_payment(
                amount=self.SUBSCRIPTION_PRICE_RUB,
                description="Подписка на Анализатор Калорий - 30 дней",
                user_id=user_id,
                return_url=return_url
            )
            
            if payment_data and payment_data.get('confirmation_url'):
                # Сохраняем информацию о платеже
                payment_id = payment_data['id']
                self.pending_payments[payment_id] = {
                    'user_id': user_id,
                    'created_at': datetime.now(),
                    'notified': False
                }
                
                # Отправляем ссылку на оплату
                keyboard = [[InlineKeyboardButton("💳 Перейти к оплате", url=payment_data['confirmation_url'])]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.effective_chat.send_message(
                    SUBSCRIPTION_MESSAGES['card_payment_created'],
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                logger.info(f"Payment link created for user {user_id}, payment_id: {payment_id}")
            else:
                await update.effective_chat.send_message(SUBSCRIPTION_MESSAGES['payment_error'])
                
        except Exception as e:
            logger.error(f"Ошибка создания платежа через YooKassa: {e}")
            await update.effective_chat.send_message(SUBSCRIPTION_MESSAGES['payment_error'])
    
    async def send_invoice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет счёт для оплаты подписки через Telegram Stars (старый метод)"""
        await self.send_stars_invoice(update, context)
    
    async def precheckout_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик предварительной проверки платежа"""
        query = update.pre_checkout_query
        
        # Проверяем корректность платежа для Telegram Stars
        if query.invoice_payload in ["subscription_1_month", "subscription_1_month_stars"]:
            await query.answer(ok=True)
        else:
            await query.answer(ok=False, error_message="Некорректный платёж")
    
    async def successful_payment_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик успешного платежа через Telegram Stars"""
        payment = update.message.successful_payment
        user_id = update.effective_user.id
        
        if payment.invoice_payload in ["subscription_1_month", "subscription_1_month_stars"]:
            # Добавляем подписку на 30 дней
            success = self.subscription_manager.add_subscription(user_id, 30)
            
            if success:
                await update.message.reply_text(SUBSCRIPTION_MESSAGES['payment_success'])
                logger.info(f"Подписка активирована для пользователя {user_id} (Telegram Stars)")
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
    
    async def check_payment_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверяет статус платежей пользователя (для отладки)"""
        user_id = update.effective_user.id
        
        # Проверяем, есть ли активные платежи для пользователя
        active_payments = [pid for pid, data in self.pending_payments.items() if data['user_id'] == user_id]
        
        if not active_payments:
            await update.message.reply_text("У вас нет активных платежей.")
            return
        
        # Проверяем статус каждого платежа
        for payment_id in active_payments:
            payment_status = self.payment_manager.get_payment_status(payment_id)
            
            if payment_status:
                if payment_status['paid']:
                    # Активируем подписку
                    success = self.subscription_manager.add_subscription(user_id, 30)
                    
                    if success:
                        # Удаляем из pending
                        del self.pending_payments[payment_id]
                        await update.message.reply_text(SUBSCRIPTION_MESSAGES['payment_success'])
                        logger.info(f"Подписка активирована для пользователя {user_id} (YooMoney, payment_id: {payment_id})")
                    else:
                        await update.message.reply_text(SUBSCRIPTION_MESSAGES['payment_error'])
                elif payment_status['status'] == 'pending':
                    await update.message.reply_text(SUBSCRIPTION_MESSAGES['card_payment_pending'])
                elif payment_status['status'] in ['canceled', 'failed']:
                    # Удаляем из pending
                    del self.pending_payments[payment_id]
                    await update.message.reply_text("Платеж был отменен или не прошел.")
    
    async def periodic_payment_check(self):
        """Периодически проверяет статус всех незавершенных платежей"""
        logger.info("Starting periodic payment verification task")
        
        while True:
            try:
                await asyncio.sleep(self.PAYMENT_CHECK_INTERVAL)
                
                if not self.pending_payments:
                    continue
                
                logger.info(f"Checking {len(self.pending_payments)} pending payment(s)")
                
                # Создаем копию ключей для безопасной итерации
                payment_ids = list(self.pending_payments.keys())
                
                for payment_id in payment_ids:
                    if payment_id not in self.pending_payments:
                        continue
                    
                    payment_info = self.pending_payments[payment_id]
                    user_id = payment_info['user_id']
                    created_at = payment_info['created_at']
                    notified = payment_info['notified']
                    
                    # Проверяем таймаут
                    time_elapsed = (datetime.now() - created_at).total_seconds()
                    if time_elapsed > self.PAYMENT_TIMEOUT:
                        logger.info(f"Payment {payment_id} timed out after {time_elapsed:.0f} seconds")
                        del self.pending_payments[payment_id]
                        
                        # Уведомляем пользователя только если еще не уведомили
                        if not notified:
                            try:
                                await self.application.bot.send_message(
                                    chat_id=user_id,
                                    text="⏰ Время ожидания оплаты истекло. Если вы хотите оформить подписку, создайте новый платеж командой /subscribe",
                                    parse_mode='Markdown'
                                )
                            except Exception as e:
                                logger.error(f"Failed to send timeout notification to user {user_id}: {e}")
                        continue
                    
                    # Проверяем статус платежа
                    try:
                        payment_status = self.payment_manager.get_payment_status(payment_id)
                        
                        if not payment_status:
                            logger.warning(f"Could not get status for payment {payment_id}")
                            continue
                        
                        if payment_status['paid']:
                            # Активируем подписку
                            success = self.subscription_manager.add_subscription(user_id, 30)
                            
                            if success:
                                # Удаляем из pending
                                del self.pending_payments[payment_id]
                                
                                # Отправляем уведомление пользователю только если еще не уведомили
                                if not notified:
                                    try:
                                        await self.application.bot.send_message(
                                            chat_id=user_id,
                                            text=SUBSCRIPTION_MESSAGES['payment_success'],
                                            parse_mode='Markdown'
                                        )
                                        logger.info(f"Subscription activated for user {user_id} (payment_id: {payment_id})")
                                    except Exception as e:
                                        logger.error(f"Failed to send success notification to user {user_id}: {e}")
                            else:
                                logger.error(f"Failed to activate subscription for user {user_id}")
                        
                        elif payment_status['status'] in ['canceled', 'failed']:
                            logger.info(f"Payment {payment_id} was {payment_status['status']}")
                            del self.pending_payments[payment_id]
                            
                            # Уведомляем пользователя только если еще не уведомили
                            if not notified:
                                try:
                                    await self.application.bot.send_message(
                                        chat_id=user_id,
                                        text=f"❌ Платеж был отменен или не прошел. Попробуйте снова с помощью команды /subscribe",
                                        parse_mode='Markdown'
                                    )
                                except Exception as e:
                                    logger.error(f"Failed to send cancellation notification to user {user_id}: {e}")
                        
                        else:
                            # Платеж все еще в процессе
                            logger.debug(f"Payment {payment_id} status: {payment_status['status']}")
                    
                    except Exception as e:
                        logger.error(f"Error checking payment {payment_id}: {e}")
                        
            except asyncio.CancelledError:
                logger.info("Payment verification task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in periodic payment check: {e}")
                # Продолжаем работу даже при ошибке
    
    async def handle_yoomoney_webhook(self, webhook_data: dict) -> bool:
        """
        Обработчик webhook уведомлений от YooMoney
        
        Args:
            webhook_data: Данные от YooMoney webhook
            
        Returns:
            True если обработка успешна, False в противном случае
        """
        try:
            # Проверяем webhook
            if not self.payment_manager.verify_webhook_notification(webhook_data):
                logger.warning("Webhook verification failed or payment not succeeded")
                return False
            
            # Получаем данные платежа
            payment_obj = webhook_data.get("object", {})
            payment_id = payment_obj.get("id")
            
            # Проверяем, есть ли этот платеж в наших записях
            if payment_id not in self.pending_payments:
                logger.warning(f"Payment {payment_id} not found in pending payments")
                return False
            
            payment_info = self.pending_payments[payment_id]
            user_id = payment_info['user_id']
            
            # Активируем подписку
            success = self.subscription_manager.add_subscription(user_id, 30)
            
            if success:
                # Удаляем из pending
                del self.pending_payments[payment_id]
                
                # Отправляем уведомление пользователю
                try:
                    await self.application.bot.send_message(
                        chat_id=user_id,
                        text=SUBSCRIPTION_MESSAGES['payment_success'],
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Failed to send notification to user {user_id}: {e}")
                
                logger.info(f"Подписка активирована для пользователя {user_id} через webhook (payment_id: {payment_id})")
                return True
            else:
                logger.error(f"Failed to activate subscription for user {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error handling YooMoney webhook: {e}")
            return False
    
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
        self.application.add_handler(CommandHandler("check_payment", self.check_payment_command))
        
        # Обработчики сообщений
        self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        
        # Обработчики платежей
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))
        self.application.add_handler(PreCheckoutQueryHandler(self.precheckout_callback))
        self.application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, self.successful_payment_callback))
        
        # Обработчик ошибок
        self.application.add_error_handler(self.error_handler)
    
    async def post_init(self, application: Application) -> None:
        """Вызывается после инициализации приложения"""
        # Запускаем задачу периодической проверки платежей
        if self.payment_manager.is_enabled():
            self.payment_check_task = asyncio.create_task(self.periodic_payment_check())
            logger.info(f"Periodic payment check started (interval: {self.PAYMENT_CHECK_INTERVAL}s, timeout: {self.PAYMENT_TIMEOUT}s)")
        else:
            logger.info("Payment manager is not enabled, skipping periodic payment check")
    
    async def post_shutdown(self, application: Application) -> None:
        """Вызывается перед остановкой приложения"""
        # Останавливаем задачу периодической проверки
        if self.payment_check_task and not self.payment_check_task.done():
            self.payment_check_task.cancel()
            try:
                await self.payment_check_task
            except asyncio.CancelledError:
                pass
            logger.info("Periodic payment check stopped")
    
    def run(self):
        """Запуск бота"""
        # Создаем приложение
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(self.post_init).post_shutdown(self.post_shutdown).build()
        
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
