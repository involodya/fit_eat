"""
Webhook сервер для обработки уведомлений от YooMoney

Этот модуль предоставляет простой HTTP сервер для приема webhook уведомлений
от YooMoney (YooKassa) о статусе платежей.

Для работы в продакшене рекомендуется использовать nginx или другой reverse proxy.
"""

import os
import json
import logging
import logging.handlers
from aiohttp import web
from dotenv import load_dotenv
from payment_manager import PaymentManager
from subscription_manager import SubscriptionManager
from telegram import Bot

# Загружаем переменные окружения
load_dotenv()

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

# Обработчик для файла с ротацией
file_handler = logging.handlers.RotatingFileHandler(
    'logs/webhook.log',
    maxBytes=10*1024*1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

# Добавляем обработчики
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# Настраиваем root logger
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[console_handler, file_handler]
)

# Токены
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # Опциональный секретный ключ для дополнительной безопасности

# Менеджеры
payment_manager = PaymentManager()
subscription_manager = SubscriptionManager()
bot = None


async def init_bot():
    """Инициализация Telegram бота"""
    global bot
    if not bot:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return bot


async def handle_yoomoney_webhook(request):
    """
    Обработчик webhook запросов от YooMoney
    
    POST /webhook/yoomoney
    """
    try:
        # Получаем данные из запроса
        data = await request.json()
        
        logger.info(f"Received webhook: {json.dumps(data, indent=2)}")
        
        # Проверяем webhook
        if not payment_manager.verify_webhook_notification(data):
            logger.warning("Webhook verification failed or payment not succeeded")
            return web.Response(status=400, text="Invalid webhook")
        
        # Получаем данные платежа
        payment_obj = data.get("object", {})
        payment_id = payment_obj.get("id")
        metadata = payment_obj.get("metadata", {})
        user_id_str = metadata.get("user_id")
        
        if not user_id_str:
            logger.error("No user_id in payment metadata")
            return web.Response(status=400, text="No user_id in metadata")
        
        user_id = int(user_id_str)
        
        # Активируем подписку
        success = subscription_manager.add_subscription(user_id, 30)
        
        if success:
            logger.info(f"Subscription activated for user {user_id} (payment_id: {payment_id})")
            
            # Отправляем уведомление пользователю
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text="🎉 **Оплата прошла успешно!**\n\nПодписка активирована на 30 дней.\nСпасибо за поддержку проекта!",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to send notification to user {user_id}: {e}")
            
            return web.Response(status=200, text="OK")
        else:
            logger.error(f"Failed to activate subscription for user {user_id}")
            return web.Response(status=500, text="Failed to activate subscription")
            
    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook request")
        return web.Response(status=400, text="Invalid JSON")
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return web.Response(status=500, text="Internal server error")


async def health_check(request):
    """Healthcheck endpoint"""
    return web.json_response({
        "status": "ok",
        "service": "yoomoney-webhook",
        "payment_manager_enabled": payment_manager.is_enabled()
    })


async def on_startup(app):
    """Выполняется при запуске сервера"""
    await init_bot()
    logger.info("Webhook server started")
    logger.info(f"YooMoney integration: {'enabled' if payment_manager.is_enabled() else 'disabled'}")


async def on_cleanup(app):
    """Выполняется при остановке сервера"""
    logger.info("Webhook server shutting down")


def create_app():
    """Создание веб-приложения"""
    app = web.Application()
    
    # Добавляем роуты
    app.router.add_post('/webhook/yoomoney', handle_yoomoney_webhook)
    app.router.add_get('/health', health_check)
    
    # Добавляем обработчики жизненного цикла
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    return app


def main():
    """Запуск webhook сервера"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return
    
    if not payment_manager.is_enabled():
        logger.warning("YooMoney payment manager is not enabled (missing credentials)")
    
    # Настройки сервера
    host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.getenv("WEBHOOK_PORT", "8080"))
    
    logger.info(f"Starting webhook server on {host}:{port}")
    logger.info(f"Webhook URL will be: http://your-domain.com:{port}/webhook/yoomoney")
    logger.info("Remember to configure this URL in YooMoney dashboard!")
    
    app = create_app()
    web.run_app(app, host=host, port=port)


if __name__ == "__main__":
    main()

