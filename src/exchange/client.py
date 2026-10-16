import os
from dotenv import load_dotenv
from binance.client import Client

load_dotenv()

def get_client() -> Client:
    if os.environ.get("USE_TESTNET", "true") == "true":
        client = Client(os.environ["BINANCE_TESTNET_KEY"], os.environ["BINANCE_TESTNET_SECRET"])
        client.API_URL = "https://testnet.binance.vision/api"
    else:
        client = Client(os.environ["BINANCE_API_KEY"], os.environ["BINANCE_API_SECRET"])
    return client