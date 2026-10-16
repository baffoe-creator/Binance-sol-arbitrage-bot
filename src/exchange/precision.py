import math

_step_cache: dict[str, float] = {}

def get_lot_size_step(client, symbol: str) -> float:
    symbol = symbol.upper()
    if symbol not in _step_cache:
        info = client.get_symbol_info(symbol)
        step = 0.0
        for f in info["filters"]:
            if f["filterType"] == "LOT_SIZE":
                step = float(f["stepSize"])
                break
        _step_cache[symbol] = step
    return _step_cache[symbol]

def round_step_size(quantity: float, step_size: float) -> float:
    if step_size <= 0:
        return quantity
    precision = int(round(-math.log10(step_size)))
    factor = 10 ** precision
    return math.floor(quantity * factor) / factor