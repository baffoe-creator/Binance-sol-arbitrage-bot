import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import logging
from src.exchange.client import get_client

logging.basicConfig(
    filename="logs/heartbeat_sol.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
client = get_client()

while True:
    try:
        acct = client.get_account(recvWindow=60000)
        balances = {b["asset"]: b["free"] for b in acct["balances"] if float(b["free"]) > 0}
        logging.info(f"Balances: {balances}")
    except Exception as e:
        logging.error(f"Heartbeat error: {e}")
    time.sleep(60)