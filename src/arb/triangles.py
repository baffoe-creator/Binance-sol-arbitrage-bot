TRIANGLES = [
    {
        "name": "SOL-BTC-USDT",
        # (pair, side, book_field, resulting_asset)
        "legs": [
            ("solbtc", "SELL", "bid", "BTC"),
            ("btcusdt", "SELL", "bid", "USDT"),
            ("solusdt", "BUY", "ask", "SOL"),
        ],
    },
]