"""
Менеджер платежей для работы с YooKassa (YooMoney)
"""

import os
import uuid
import logging
import logging.handlers
from typing import Optional, Dict, Any
from datetime import datetime
from yookassa import Configuration, Payment

# Создаем директорию для логов, если её нет
os.makedirs('logs', exist_ok=True)

# Настройка логирования
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
    'logs/payments.log',
    maxBytes=10*1024*1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

# Добавляем обработчики
logger.addHandler(console_handler)
logger.addHandler(file_handler)


class PaymentManager:
    """Класс для управления платежами через YooKassa"""
    
    def __init__(self):
        """Инициализация менеджера платежей"""
        self.shop_id = os.getenv("YOOKASSA_SHOP_ID")
        self.secret_key = os.getenv("YOOKASSA_SECRET_KEY")
        self.test_mode = os.getenv("YOOKASSA_TEST_MODE", "True").lower() == "true"
        
        # Проверка наличия необходимых ключей
        if not self.shop_id or not self.secret_key:
            logger.warning("YooKassa credentials not found in environment variables")
            self.enabled = False
        else:
            # Конфигурация YooKassa
            Configuration.account_id = self.shop_id
            Configuration.secret_key = self.secret_key
            self.enabled = True
            logger.info(f"YooKassa initialized (test_mode: {self.test_mode})")
    
    def is_enabled(self) -> bool:
        """Проверяет, доступны ли платежи через YooKassa"""
        return self.enabled
    
    def create_payment(
        self, 
        amount: float, 
        description: str,
        user_id: int,
        return_url: str = "https://t.me/your_bot"
    ) -> Optional[Dict[str, Any]]:
        """
        Создает платеж в YooKassa
        
        Args:
            amount: Сумма платежа в рублях
            description: Описание платежа
            user_id: ID пользователя Telegram
            return_url: URL для возврата после оплаты
            
        Returns:
            Словарь с данными платежа или None в случае ошибки
        """
        if not self.enabled:
            logger.error("YooKassa is not enabled")
            return None
        
        try:
            # Генерируем уникальный ключ идемпотентности
            idempotence_key = str(uuid.uuid4())
            
            # Создаем платеж
            payment = Payment.create({
                "amount": {
                    "value": f"{amount:.2f}",
                    "currency": "RUB"
                },
                "payment_method_data": {
                    "type": "bank_card"
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": return_url
                },
                "description": description,
                "metadata": {
                    "user_id": str(user_id),
                    "platform": "telegram",
                    "timestamp": datetime.now().isoformat()
                },
                "test": self.test_mode
            }, idempotence_key)
            
            # Извлекаем нужные данные
            payment_data = {
                "id": payment.id,
                "status": payment.status,
                "amount": float(payment.amount.value),
                "currency": payment.amount.currency,
                "confirmation_url": payment.confirmation.confirmation_url if payment.confirmation else None,
                "created_at": payment.created_at,
                "test": payment.test,
                "paid": payment.paid
            }
            
            logger.info(f"Payment created: {payment.id} for user {user_id}, amount: {amount} RUB")
            return payment_data
            
        except Exception as e:
            logger.error(f"Error creating payment: {e}")
            return None
    
    def get_payment_status(self, payment_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает статус платежа
        
        Args:
            payment_id: ID платежа в YooKassa
            
        Returns:
            Словарь с данными платежа или None
        """
        if not self.enabled:
            logger.error("YooKassa is not enabled")
            return None
        
        try:
            payment = Payment.find_one(payment_id)
            
            payment_data = {
                "id": payment.id,
                "status": payment.status,
                "amount": float(payment.amount.value),
                "currency": payment.amount.currency,
                "paid": payment.paid,
                "test": payment.test,
                "created_at": payment.created_at,
                "metadata": payment.metadata if payment.metadata else {}
            }
            
            if payment.paid:
                payment_data["captured_at"] = payment.captured_at
            
            return payment_data
            
        except Exception as e:
            logger.error(f"Error getting payment status: {e}")
            return None
    
    def verify_webhook_notification(self, notification_data: Dict[str, Any]) -> bool:
        """
        Проверяет webhook уведомление от YooKassa
        
        Args:
            notification_data: Данные уведомления
            
        Returns:
            True если платеж успешен, False в противном случае
        """
        try:
            event = notification_data.get("event")
            payment_obj = notification_data.get("object")
            
            if not payment_obj:
                logger.error("No payment object in notification")
                return False
            
            payment_id = payment_obj.get("id")
            status = payment_obj.get("status")
            paid = payment_obj.get("paid", False)
            
            logger.info(f"Webhook notification: event={event}, payment_id={payment_id}, status={status}, paid={paid}")
            
            # Проверяем статус платежа
            if event == "payment.succeeded" and status == "succeeded" and paid:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error verifying webhook notification: {e}")
            return False
    
    def extract_user_id_from_payment(self, payment_data: Dict[str, Any]) -> Optional[int]:
        """
        Извлекает user_id из метаданных платежа
        
        Args:
            payment_data: Данные платежа
            
        Returns:
            user_id или None
        """
        try:
            metadata = payment_data.get("metadata", {})
            user_id_str = metadata.get("user_id")
            
            if user_id_str:
                return int(user_id_str)
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting user_id from payment: {e}")
            return None
    
    @staticmethod
    def format_price(amount: float) -> str:
        """
        Форматирует цену для отображения
        
        Args:
            amount: Сумма в рублях
            
        Returns:
            Отформатированная строка
        """
        return f"{amount:.2f} ₽"

