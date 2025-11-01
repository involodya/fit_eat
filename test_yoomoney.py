"""
Тестовый скрипт для проверки интеграции YooMoney

Этот скрипт проверяет:
1. Наличие необходимых зависимостей
2. Корректность credentials YooMoney
3. Возможность создания тестового платежа
4. Корректность конфигурации
"""

import os
import sys
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

def check_dependencies():
    """Проверка установленных зависимостей"""
    print("🔍 Проверка зависимостей...")
    
    required_packages = [
        'telegram',
        'yookassa',
        'aiohttp',
        'dotenv'
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package)
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ❌ {package} - не установлен")
            missing.append(package)
    
    if missing:
        print(f"\n⚠️  Установите недостающие пакеты: pip install -r requirements.txt")
        return False
    
    return True


def check_env_variables():
    """Проверка переменных окружения"""
    print("\n🔍 Проверка переменных окружения...")
    
    required_vars = {
        'TELEGRAM_BOT_TOKEN': 'Telegram Bot Token',
        'OPENAI_API_KEY': 'OpenAI API Key'
    }
    
    optional_vars = {
        'YOOKASSA_SHOP_ID': 'YooKassa Shop ID',
        'YOOKASSA_SECRET_KEY': 'YooKassa Secret Key',
        'YOOKASSA_TEST_MODE': 'YooKassa Test Mode',
        'SUBSCRIPTION_PRICE_RUB': 'Subscription Price (RUB)'
    }
    
    # Проверяем обязательные переменные
    all_ok = True
    for var, name in required_vars.items():
        value = os.getenv(var)
        if value:
            masked = value[:8] + '...' if len(value) > 8 else value
            print(f"  ✅ {name}: {masked}")
        else:
            print(f"  ❌ {name} - не установлен")
            all_ok = False
    
    # Проверяем опциональные переменные
    print("\n  Опциональные переменные (YooMoney):")
    yoomoney_configured = True
    for var, name in optional_vars.items():
        value = os.getenv(var)
        if value:
            if 'SECRET' in var or 'KEY' in var:
                masked = value[:8] + '...' if len(value) > 8 else value
                print(f"    ✅ {name}: {masked}")
            else:
                print(f"    ✅ {name}: {value}")
        else:
            print(f"    ⚠️  {name} - не установлен")
            yoomoney_configured = False
    
    if not yoomoney_configured:
        print("\n  ℹ️  YooMoney не настроен - оплата картами будет недоступна")
        print("     Для настройки см. YOOMONEY_INTEGRATION.md")
    
    return all_ok


def test_yoomoney_connection():
    """Тестирование подключения к YooMoney"""
    print("\n🔍 Проверка подключения к YooMoney...")
    
    try:
        from payment_manager import PaymentManager
        
        payment_manager = PaymentManager()
        
        if not payment_manager.is_enabled():
            print("  ⚠️  YooMoney не активирован (credentials не настроены)")
            return True  # Это не ошибка, просто не настроено
        
        print("  ✅ PaymentManager инициализирован")
        print(f"  ℹ️  Тестовый режим: {payment_manager.test_mode}")
        
        # Пробуем создать тестовый платеж (без фактической отправки)
        print("\n  Проверка создания платежа...")
        try:
            # Это фактически создаст платеж в YooKassa (в тестовом режиме)
            # Если не хотите создавать платеж, закомментируйте следующие строки
            
            print("  ⚠️  Внимание: сейчас будет создан тестовый платеж в YooKassa")
            print("     Если не хотите, нажмите Ctrl+C")
            
            import time
            time.sleep(2)
            
            payment_data = payment_manager.create_payment(
                amount=1.0,
                description="Test payment from setup script",
                user_id=123456789,
                return_url="https://t.me/test"
            )
            
            if payment_data:
                print(f"  ✅ Тестовый платеж создан успешно")
                print(f"     Payment ID: {payment_data['id']}")
                print(f"     Status: {payment_data['status']}")
                print(f"     Test mode: {payment_data['test']}")
                return True
            else:
                print("  ❌ Ошибка создания платежа")
                return False
                
        except KeyboardInterrupt:
            print("\n  ⚠️  Создание тестового платежа отменено")
            return True
        except Exception as e:
            print(f"  ❌ Ошибка при создании платежа: {e}")
            return False
            
    except ImportError as e:
        print(f"  ❌ Ошибка импорта: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Ошибка: {e}")
        return False


def check_subscription_manager():
    """Проверка менеджера подписок"""
    print("\n🔍 Проверка менеджера подписок...")
    
    try:
        from subscription_manager import SubscriptionManager
        
        sub_manager = SubscriptionManager()
        print("  ✅ SubscriptionManager инициализирован")
        
        # Проверяем наличие файлов
        import os
        
        if os.path.exists('whitelist.txt'):
            print("  ✅ whitelist.txt найден")
        else:
            print("  ⚠️  whitelist.txt не найден (будет создан автоматически)")
        
        if os.path.exists('subscriptions.json'):
            print("  ✅ subscriptions.json найден")
        else:
            print("  ⚠️  subscriptions.json не найден (будет создан автоматически)")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Ошибка: {e}")
        return False


def main():
    """Главная функция"""
    print("=" * 60)
    print("🧪 Тест интеграции YooMoney для Fit Eat бота")
    print("=" * 60)
    
    # Проверяем зависимости
    if not check_dependencies():
        sys.exit(1)
    
    # Проверяем переменные окружения
    if not check_env_variables():
        print("\n❌ Не все обязательные переменные окружения настроены")
        print("   Создайте .env файл на основе .env.example")
        sys.exit(1)
    
    # Проверяем менеджер подписок
    if not check_subscription_manager():
        print("\n❌ Ошибка при инициализации менеджера подписок")
        sys.exit(1)
    
    # Проверяем YooMoney (опционально)
    test_yoomoney_connection()
    
    print("\n" + "=" * 60)
    print("✅ Проверка завершена!")
    print("=" * 60)
    print("\n📝 Следующие шаги:")
    print("   1. Запустите бота: python main.py или ./run_bot.sh")
    print("   2. (Опционально) Запустите webhook сервер: python webhook_server.py")
    print("   3. Проверьте работу в Telegram")
    print("\n📚 Документация:")
    print("   - YooMoney: YOOMONEY_INTEGRATION.md")
    print("   - Общая: README.md")
    print("   - Quick Start: QUICK_START.md")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Тест прерван пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

