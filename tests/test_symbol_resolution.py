import unittest

import scanner


class FakeExchange:
    def __init__(self, working_symbol):
        self.working_symbol = working_symbol
        self.ohlcv_calls = []
        self.ticker_calls = []

    def fetch_ohlcv(self, symbol, **kwargs):
        self.ohlcv_calls.append(symbol)
        if symbol != self.working_symbol:
            raise RuntimeError(f"unknown symbol: {symbol}")
        return [[1, 1, 1, 1, 1, 1]]

    def fetch_ticker(self, symbol):
        self.ticker_calls.append(symbol)
        if symbol != self.working_symbol:
            raise RuntimeError(f"unknown symbol: {symbol}")
        return {"last": 123.0}


class SymbolResolutionTests(unittest.TestCase):
    def test_perpetual_alias_is_tried_before_spot_alias(self):
        self.assertEqual(
            scanner.exchange_symbol_candidates("HYPE/USDT"),
            ["HYPE/USDT:USDT", "HYPE/USDT"],
        )

    def test_ohlcv_uses_perpetual_alias(self):
        exchange = FakeExchange("HYPE/USDT:USDT")
        candles = scanner.fetch_exchange_ohlcv(exchange, "HYPE/USDT")
        self.assertEqual(candles[0][4], 1)
        self.assertEqual(exchange.ohlcv_calls, ["HYPE/USDT:USDT"])

    def test_ticker_falls_back_when_exchange_has_no_settlement_alias(self):
        exchange = FakeExchange("HYPE/USDT")
        ticker = scanner.fetch_exchange_ticker(exchange, "HYPE/USDT")
        self.assertEqual(ticker["last"], 123.0)
        self.assertEqual(
            exchange.ticker_calls,
            ["HYPE/USDT:USDT", "HYPE/USDT"],
        )


if __name__ == "__main__":
    unittest.main()
