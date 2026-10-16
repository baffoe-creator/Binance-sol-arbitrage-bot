import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import logging
from src.exchange.client import get_client
from src.exchange.balances import parse_sol_balance

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/heartbeat_sol.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
client = get_client()

while True:
    try:
        acct = client.get_account(recvWindow=60000)
        # Include "locked" too; an asset with only locked funds used to be hidden.
        balances = {
            b["asset"]: {"free": b["free"], "locked": b["locked"]}
            for b in acct["balances"]
            if float(b["free"]) > 0 or float(b["locked"]) > 0
        }
        logging.info(f"Balances: {balances}")
        logging.info(f"SOL breakdown: {parse_sol_balance(acct['balances']).describe()}")
    except Exception as e:
        logging.error(f"Heartbeat error: {e}")
    time.sleep(60)