"""Реєстрація вебхука Telegram на Vercel.

  python set_webhook.py https://ваш-проєкт.vercel.app     # увімкнути вебхук
  python set_webhook.py --delete                            # вимкнути (повернутись до polling)

BOT_TOKEN і WEBHOOK_SECRET беруться з .env або змінних середовища.
"""
import asyncio
import sys

from aiogram import Bot

from bot import config


async def main(argv: list[str]) -> int:
    if not config.BOT_TOKEN:
        print("Немає BOT_TOKEN у .env")
        return 1
    bot = Bot(config.BOT_TOKEN)
    try:
        if argv and argv[0] == "--delete":
            await bot.delete_webhook()
            print("Вебхук вимкнено.")
            return 0
        if not argv or not argv[0].startswith("https://"):
            print("Вкажи https-адресу проєкту, напр.: python set_webhook.py https://my-bot.vercel.app")
            return 1
        if not config.WEBHOOK_SECRET:
            print("Немає WEBHOOK_SECRET у .env (латиниця, цифри, _ і -).")
            return 1
        url = argv[0].rstrip("/") + "/api/webhook"
        await bot.set_webhook(url, secret_token=config.WEBHOOK_SECRET,
                              allowed_updates=["message", "callback_query"])
        info = await bot.get_webhook_info()
        print(f"Вебхук: {info.url}; помилка: {info.last_error_message or 'немає'}")
        return 0
    finally:
        await bot.session.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
