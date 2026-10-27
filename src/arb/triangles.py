TRIANGLES = [
    {
        "name": "USDT-BTC-SOL-USDT",
        # (pair, side, book_field, resulting_asset)
        # start with 1 USDT:
        #   USDT -> BTC via BTCUSDT ask
        #   BTC -> SOL via SOLBTC ask
        #   SOL -> USDT via SOLUSDT bid
        "legs": [
            ("btcusdt", "BUY", "ask", "BTC"),
            ("solbtc", "BUY", "ask", "SOL"),
            ("solusdt", "SELL", "bid", "USDT"),
        ],
    },
    {
        "name": "USDT-SOL-BTC-USDT",
        # start with 1 USDT:
        #   USDT -> SOL via SOLUSDT ask
        #   SOL -> BTC via SOLBTC bid
        #   BTC -> USDT via BTCUSDT bid
        "legs": [
            ("solusdt", "BUY", "ask", "SOL"),
            ("solbtc", "SELL", "bid", "BTC"),
            ("btcusdt", "SELL", "bid", "USDT"),
        ],
    },
]