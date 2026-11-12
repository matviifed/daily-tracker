#!/usr/bin/env bash
# Розгортання на Ubuntu/Debian VPS. Запуск з теки проєкту:  bash deploy/setup.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(whoami)"

sudo apt-get update -y
sudo apt-get install -y python3 python3-venv git

cd "$DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo ">>> Відкрий .env і впиши BOT_TOKEN:  nano $DIR/.env"
  echo ">>> Потім запусти знову:  bash deploy/setup.sh"
  exit 0
fi

if ! grep -Eq '^BOT_TOKEN=.+' .env; then
  echo "BOT_TOKEN порожній у .env — впиши токен і запусти скрипт ще раз."
  exit 1
fi

sed -e "s|__USER__|$RUN_USER|g" -e "s|__DIR__|$DIR|g" deploy/daily-tracker.service \
  | sudo tee /etc/systemd/system/daily-tracker.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now daily-tracker
sleep 3
sudo systemctl --no-pager status daily-tracker | head -n 12
echo
echo "Готово. Логи:  journalctl -u daily-tracker -f"
echo "Оновлення:     git pull && sudo systemctl restart daily-tracker"
