"""Настройки бота из переменных окружения (или из файла .env рядом с bot.py)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, tzinfo
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    """Ошибка в настройках — сообщение показываем пользователю как есть."""


@dataclass(frozen=True)
class Settings:
    bot_token: str
    morning_time: time
    evening_time: time
    timezone: Optional[tzinfo]  # None — часовой пояс компьютера
    db_path: Path

    def now(self) -> datetime:
        if self.timezone is not None:
            return datetime.now(self.timezone)
        return datetime.now().astimezone()

    def today(self) -> date:
        return self.now().date()


def _parse_time(name: str, default: str) -> time:
    raw = os.getenv(name, "").strip() or default
    try:
        hours, minutes = raw.split(":")
        return time(int(hours), int(minutes))
    except ValueError:
        raise ConfigError(f"{name}={raw!r}: время нужно указать как ЧЧ:ММ, например 07:30") from None


def _parse_timezone() -> Optional[tzinfo]:
    raw = os.getenv("TIMEZONE", "").strip()
    if not raw:
        return None
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(
            f"TIMEZONE={raw!r}: неизвестный часовой пояс. Пример: Europe/Moscow"
        ) from None


def load_settings() -> Settings:
    # utf-8-sig — чтобы файл, сохранённый Блокнотом с BOM, тоже читался.
    # Уже заданные переменные окружения важнее файла .env.
    load_dotenv(PROJECT_DIR / ".env", encoding="utf-8-sig")

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "Не задан токен бота. Создай файл .env рядом с bot.py и впиши в него строку\n"
            "BOT_TOKEN=токен_от_BotFather\n"
            "Подробности — в README.md."
        )

    db_path = Path(os.getenv("DB_PATH", "").strip() or PROJECT_DIR / "homework.db")

    return Settings(
        bot_token=token,
        morning_time=_parse_time("MORNING_TIME", "07:30"),
        evening_time=_parse_time("EVENING_TIME", "20:00"),
        timezone=_parse_timezone(),
        db_path=db_path,
    )
