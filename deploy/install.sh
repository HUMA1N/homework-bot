#!/usr/bin/env bash
# Установка бота на сервер с Linux (Ubuntu / Debian) как systemd-службы.
#
#   sudo git clone <адрес репозитория> /opt/homework-bot
#   cd /opt/homework-bot
#   sudo bash deploy/install.sh
#
# Скрипт можно запускать повторно: он ничего не сломает и не сотрёт задания.
set -euo pipefail

SERVICE=homework-bot
APP_USER=homework
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_FILE="/etc/systemd/system/${SERVICE}.service"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "запусти скрипт от имени администратора: sudo bash deploy/install.sh"
[ -f "$APP_DIR/bot.py" ] || die "не нашёл bot.py в $APP_DIR"
case "$APP_DIR" in
    /root/* | /home/*)
        die "бот лежит в $APP_DIR, а служба не может читать домашние папки.
Перенеси его, например: sudo mv $APP_DIR /opt/homework-bot && cd /opt/homework-bot" ;;
esac
command -v systemctl >/dev/null || die "на сервере нет systemd"

say "Проверяю Python"
venv_works() {
    local tmp
    tmp="$(mktemp -d)"
    python3 -m venv "$tmp/venv" >/dev/null 2>&1
    local status=$?
    rm -rf "$tmp"
    return $status
}
if ! command -v python3 >/dev/null || ! venv_works; then
    command -v apt-get >/dev/null || die "установи python3 и модуль venv вручную"
    apt-get update
    apt-get install -y python3 python3-venv
fi
python3 -c 'import sys; assert sys.version_info >= (3, 10)' \
    || die "нужен Python 3.10 или новее, а установлен $(python3 --version)"
python3 --version

say "Создаю пользователя $APP_USER (от его имени будет работать бот)"
if id "$APP_USER" >/dev/null 2>&1; then
    echo "Уже есть."
else
    useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$APP_USER"
fi

say "Устанавливаю библиотеки в $APP_DIR/.venv"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

ENV_FILE="$APP_DIR/.env"
say "Настройки ($ENV_FILE)"
if [ ! -f "$ENV_FILE" ]; then
    cp "$APP_DIR/.env.example" "$ENV_FILE"
fi
if ! grep -Eq '^BOT_TOKEN=[0-9]+:[A-Za-z0-9_-]+' "$ENV_FILE"; then
    [ -t 0 ] || die "впиши токен в $ENV_FILE (строка BOT_TOKEN=...) и запусти скрипт снова"
    while true; do
        read -rp "Вставь токен бота от @BotFather: " token
        token="$(printf '%s' "$token" | tr -d '[:space:]')"
        [[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] && break
        echo "Не похоже на токен. Он выглядит так: 1234567890:AAH...xyz"
    done
    sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=${token}|" "$ENV_FILE"
fi
if ! grep -Eq '^TIMEZONE=.+' "$ENV_FILE"; then
    # На серверах часто стоит время UTC — без часового пояса утренний список
    # придёт не в 07:30 по-местному.
    tz="Europe/Moscow"
    if [ -t 0 ]; then
        read -rp "Часовой пояс [Europe/Moscow]: " answer
        tz="${answer:-$tz}"
    fi
    if grep -q '^TIMEZONE=' "$ENV_FILE"; then
        sed -i "s|^TIMEZONE=.*|TIMEZONE=${tz}|" "$ENV_FILE"
    else
        printf '\nTIMEZONE=%s\n' "$tz" >> "$ENV_FILE"
    fi
fi
# Токен — секрет: читать файл могут только root и бот.
chown "root:$APP_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

say "Устанавливаю службу $UNIT_FILE"
sed -e "s|/opt/homework-bot|${APP_DIR}|g" \
    -e "s|^User=.*|User=${APP_USER}|" -e "s|^Group=.*|Group=${APP_USER}|" \
    "$APP_DIR/deploy/${SERVICE}.service" > "$UNIT_FILE"

# Если раньше бот запускался вручную, перенесём старую базу с заданиями.
OLD_DB="$APP_DIR/homework.db"
NEW_DB="/var/lib/${SERVICE}/homework.db"
if [ -f "$OLD_DB" ] && [ ! -f "$NEW_DB" ]; then
    install -d -o "$APP_USER" -g "$APP_USER" "/var/lib/${SERVICE}"
    install -o "$APP_USER" -g "$APP_USER" -m 600 "$OLD_DB" "$NEW_DB"
    echo "Перенёс базу заданий в $NEW_DB"
fi

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"

sleep 3
if systemctl is-active --quiet "$SERVICE"; then
    say "Готово! Бот работает и будет запускаться сам после перезагрузки сервера."
    journalctl -u "$SERVICE" -n 5 --no-pager || true
    cat <<TXT

Полезные команды:
  sudo systemctl status $SERVICE      — работает ли бот
  sudo journalctl -u $SERVICE -f      — журнал бота (выход: Ctrl+C)
  sudo systemctl restart $SERVICE     — перезапустить (после правки .env)
  sudo bash $APP_DIR/deploy/update.sh — обновить бота до новой версии
TXT
else
    journalctl -u "$SERVICE" -n 20 --no-pager || true
    die "бот не запустился — причина в журнале выше. Исправь и запусти скрипт снова."
fi
