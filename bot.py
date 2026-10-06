"""Запуск бота: python bot.py"""

import asyncio
import logging
import sys

from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.utils.token import TokenValidationError

from homework_bot.app import main
from homework_bot.config import ConfigError, load_settings


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        settings = load_settings()
        asyncio.run(main(settings))
    except ConfigError as e:
        sys.exit(f"Ошибка настроек: {e}")
    except (TokenValidationError, TelegramUnauthorizedError):
        sys.exit(
            "Telegram не принял токен бота. Проверь BOT_TOKEN в файле .env: "
            "его нужно скопировать у @BotFather целиком, без пробелов и кавычек."
        )
    except TelegramNetworkError as e:
        sys.exit(f"Не удалось подключиться к Telegram. Проверь интернет и попробуй снова.\n({e})")
    except KeyboardInterrupt:
        print("Бот остановлен.")


if __name__ == "__main__":
    run()
