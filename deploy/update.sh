#!/usr/bin/env bash
# Обновление бота до последней версии с GitHub:  sudo bash deploy/update.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "Запусти так: sudo bash deploy/update.sh" >&2; exit 1; }

git -C "$APP_DIR" pull --ff-only
# Установщик обновит библиотеки и службу и перезапустит бота.
# Настройки (.env) и задания он не трогает.
bash "$APP_DIR/deploy/install.sh"
