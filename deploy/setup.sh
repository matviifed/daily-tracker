#!/usr/bin/env bash
# Розгортання на Ubuntu/Debian (apt) або Oracle Linux/RHEL (dnf).
# Запуск з теки проєкту:  bash deploy/setup.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(whoami)"

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-venv git
elif command -v dnf >/dev/null 2>&1; then
  # python3.11 є в AppStream Oracle Linux 8/9; стандартний python3 там може бути надто старим
  sudo dnf install -y git python3.11 || sudo dnf install -y git python3.12 || sudo dnf install -y git python3
else
  echo "Невідомий менеджер пакетів — встанови python>=3.10 і git вручну." >&2
  exit 1
fi

PY=""
for cand in python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    PY="$cand"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Потрібен Python 3.10+, але його не знайдено." >&2
  exit 1
fi
echo "Використовую $($PY --version)"

cd "$DIR"
"$PY" -m venv .venv
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

# SELinux (Oracle Linux): дозволити systemd запускати python із venv у домашній теці
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce)" = "Enforcing" ]; then
  sudo chcon -R -t bin_t "$DIR/.venv/bin" || true
fi

sed -e "s|__USER__|$RUN_USER|g" -e "s|__DIR__|$DIR|g" deploy/daily-tracker.service \
  | sudo tee /etc/systemd/system/daily-tracker.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now daily-tracker
sleep 3
sudo systemctl --no-pager status daily-tracker | head -n 12 || true
echo
echo "Готово. Логи:  journalctl -u daily-tracker -f"
echo "Оновлення:     git pull && sudo systemctl restart daily-tracker"
