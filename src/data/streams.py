import json
import logging
import threading
import time

import websocket

logger = logging.getLogger("bot.data")


class SolBookCache:
    def __init__(self, pairs: list[str]):
        self.pairs = list(pairs)
        self.books = {p: {"bid": None, "ask": None} for p in self.pairs}
        self._lock = threading.Lock()
        self.last_update_time = {p: time.monotonic() for p in self.pairs}

    def update(self, pair: str, bid: float, ask: float):
        with self._lock:
            self.books[pair] = {"bid": bid, "ask": ask}
            self.last_update_time[pair] = time.monotonic()

    def snapshot(self) -> dict:
        with self._lock:
            out = {}
            for pair, book in self.books.items():
                out[pair] = {
                    "bid": book["bid"],
                    "ask": book["ask"],
                    "age_s": time.monotonic() - self.last_update_time.get(pair, time.monotonic()),
                }
            return out

    def seconds_since_update(self, pair: str | None = None) -> float:
        with self._lock:
            now = time.monotonic()
            if pair is not None:
                return now - self.last_update_time.get(pair, now)
            if not self.last_update_time:
                return 0.0
            return max(now - ts for ts in self.last_update_time.values())


class BinanceBookStream:
    def __init__(self, cache: SolBookCache, reconnect_delay: float = 5.0):
        self.cache = cache
        self.reconnect_delay = reconnect_delay
        self._stop_event = threading.Event()
        self._thread = None
        self._connect_count = 0
        self._disconnect_count = 0
        self._reconnect_count = 0

    @property
    def thread(self):
        return self._thread

    @property
    def connect_count(self):
        return self._connect_count

    @property
    def disconnect_count(self):
        return self._disconnect_count

    @property
    def reconnect_count(self):
        return self._reconnect_count

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            logger.info("WebSocket thread already running; reusing it.")
            return self._thread
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="binance-book-ticker",
            daemon=True,
        )
        self._thread.start()
        return self._thread

    def stop(self):
        if self._thread is None:
            return
        logger.info("Stopping WebSocket thread...")
        self._stop_event.set()
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            logger.warning("WebSocket thread did not exit within 10s")
        self._thread = None

    def _run(self):
        while not self._stop_event.is_set():
            streams = "/".join(f"{p}@bookTicker" for p in self.cache.pairs)
            url = f"wss://stream.binance.com:9443/stream?streams={streams}"
            self._connect_count += 1
            logger.info("WebSocket connect #%s to %s", self._connect_count, url)

            def on_message(ws, message):
                data = json.loads(message)["data"]
                pair = data["s"].lower()
                self.cache.update(pair, float(data["b"]), float(data["a"]))

            def on_error(ws, error):
                logger.error("WebSocket error: %s", error)
                self._disconnect_count += 1

            def on_close(ws, code, msg):
                if msg:
                    logger.warning("WebSocket closed (code=%s): %s", code, msg)
                else:
                    logger.warning("WebSocket closed (code=%s)", code)
                self._disconnect_count += 1

            ws = websocket.WebSocketApp(
                url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            try:
                ws.run_forever(reconnect=False, ping_interval=20, ping_timeout=10)
            except Exception as exc:
                logger.exception("WebSocket runtime failed: %s", exc)

            if self._stop_event.is_set():
                logger.info("WebSocket stop requested; exiting reconnect loop.")
                break

            self._reconnect_count += 1
            logger.warning(
                "WebSocket disconnected; reconnect #%s in %.1fs",
                self._reconnect_count,
                self.reconnect_delay,
            )
            self._stop_event.wait(self.reconnect_delay)


def start_stream(cache: SolBookCache):
    stream = BinanceBookStream(cache)
    stream.start()
    return stream