import json
import logging
import threading
import time

import websocket

logger = logging.getLogger("bot.data")


class SolBookCache:
    def __init__(self, pairs: list[str]):
        self.pairs = pairs  # ["solbtc", "btcusdt", "solusdt"]
        self.books = {p: {"bid": None, "ask": None} for p in pairs}
        self._lock = threading.Lock()
        self.last_update_time = time.time()

    def update(self, pair: str, bid: float, ask: float):
        with self._lock:
            self.books[pair] = {"bid": bid, "ask": ask}
            self.last_update_time = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.books)

    def seconds_since_update(self) -> float:
        with self._lock:
            return time.time() - self.last_update_time


def start_stream(cache: SolBookCache):
    streams = "/".join(f"{p}@bookTicker" for p in cache.pairs)
    url = f"wss://stream.binance.com:9443/stream?streams={streams}"

    def on_message(ws, message):
        data = json.loads(message)["data"]
        pair = data["s"].lower()
        cache.update(pair, float(data["b"]), float(data["a"]))

    def on_error(ws, error):
        logger.error(f"WebSocket error: {error}")

    def on_close(ws, code, msg):
        logger.warning(f"WebSocket closed ({code}); reconnect logic should restart this")

    ws = websocket.WebSocketApp(url, on_message=on_message, on_error=on_error, on_close=on_close)
    ws.run_forever(reconnect=5)