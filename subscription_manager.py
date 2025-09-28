"""
Менеджер подписок для управления доступом пользователей
"""

import json
import os
from datetime import datetime, timedelta
from typing import Set, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class SubscriptionManager:
    def __init__(self, whitelist_file: str = "whitelist.txt", subscriptions_file: str = "subscriptions.json"):
        self.whitelist_file = whitelist_file
        self.subscriptions_file = subscriptions_file
        self._whitelist: Set[int] = set()
        self._subscriptions: Dict[int, str] = {}
        self._load_data()
    
    def _load_data(self):
        """Загружает данные о whitelist и подписках"""
        # Загружаем whitelist
        try:
            if os.path.exists(self.whitelist_file):
                with open(self.whitelist_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            try:
                                user_id = int(line)
                                self._whitelist.add(user_id)
                            except ValueError:
                                logger.warning(f"Невалидный ID в whitelist: {line}")
        except Exception as e:
            logger.error(f"Ошибка загрузки whitelist: {e}")
        
        # Загружаем подписки
        try:
            if os.path.exists(self.subscriptions_file):
                with open(self.subscriptions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._subscriptions = data.get('subscriptions', {})
                    # Конвертируем ключи в int
                    self._subscriptions = {int(k): v for k, v in self._subscriptions.items()}
        except Exception as e:
            logger.error(f"Ошибка загрузки подписок: {e}")
    
    def _save_subscriptions(self):
        """Сохраняет данные о подписках"""
        try:
            data = {
                "subscriptions": {str(k): v for k, v in self._subscriptions.items()},
                "metadata": {
                    "version": "1.0",
                    "last_updated": datetime.now().isoformat(),
                    "description": "Storage for user subscriptions"
                }
            }
            with open(self.subscriptions_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения подписок: {e}")
    
    def is_whitelisted(self, user_id: int) -> bool:
        """Проверяет, находится ли пользователь в whitelist"""
        return user_id in self._whitelist
    
    def has_active_subscription(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя активная подписка"""
        if user_id not in self._subscriptions:
            return False
        
        try:
            expiry_date = datetime.fromisoformat(self._subscriptions[user_id])
            return datetime.now() < expiry_date
        except Exception as e:
            logger.error(f"Ошибка проверки подписки для {user_id}: {e}")
            return False
    
    def get_subscription_expiry(self, user_id: int) -> Optional[datetime]:
        """Возвращает дату окончания подписки"""
        if user_id not in self._subscriptions:
            return None
        
        try:
            return datetime.fromisoformat(self._subscriptions[user_id])
        except Exception as e:
            logger.error(f"Ошибка получения даты подписки для {user_id}: {e}")
            return None
    
    def has_access(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя доступ (whitelist или активная подписка)"""
        return self.is_whitelisted(user_id) or self.has_active_subscription(user_id)
    
    def add_subscription(self, user_id: int, days: int = 30) -> bool:
        """Добавляет или продлевает подписку на указанное количество дней"""
        try:
            # Если у пользователя уже есть подписка, продлеваем её
            if user_id in self._subscriptions and self.has_active_subscription(user_id):
                current_expiry = datetime.fromisoformat(self._subscriptions[user_id])
                new_expiry = current_expiry + timedelta(days=days)
            else:
                # Новая подписка
                new_expiry = datetime.now() + timedelta(days=days)
            
            self._subscriptions[user_id] = new_expiry.isoformat()
            self._save_subscriptions()
            logger.info(f"Подписка добавлена для {user_id} до {new_expiry}")
            return True
        except Exception as e:
            logger.error(f"Ошибка добавления подписки для {user_id}: {e}")
            return False
    
    def get_user_status(self, user_id: int) -> Dict[str, any]:
        """Возвращает статус пользователя"""
        status = {
            'has_access': self.has_access(user_id),
            'is_whitelisted': self.is_whitelisted(user_id),
            'has_subscription': self.has_active_subscription(user_id),
            'subscription_expiry': self.get_subscription_expiry(user_id)
        }
        return status
    
    def cleanup_expired_subscriptions(self):
        """Удаляет истёкшие подписки для очистки файла"""
        try:
            current_time = datetime.now()
            expired_users = []
            
            for user_id, expiry_str in self._subscriptions.items():
                try:
                    expiry_date = datetime.fromisoformat(expiry_str)
                    if current_time > expiry_date:
                        expired_users.append(user_id)
                except Exception:
                    expired_users.append(user_id)  # Удаляем некорректные записи
            
            for user_id in expired_users:
                del self._subscriptions[user_id]
            
            if expired_users:
                self._save_subscriptions()
                logger.info(f"Удалено {len(expired_users)} истёкших подписок")
        except Exception as e:
            logger.error(f"Ошибка очистки подписок: {e}")
