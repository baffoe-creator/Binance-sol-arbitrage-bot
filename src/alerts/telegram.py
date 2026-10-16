import logging
import os

import requests

logger = logging.getLogger("bot.alerts")


def send_alert(message: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(url, data={"chat_id": chat_id, "text": message}, timeout=5)
        if response.status_code != 200:
            logger.error(f"Telegram alert failed ({response.status_code}): {response.text}")
    except requests.RequestException as e:
        logger.error(f"Telegram alert request failed: {e}")