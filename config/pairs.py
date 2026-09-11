"""Forex universe yang di-scan. Format Twelve Data: "EUR/USD" (slash)."""

MAJOR_PAIRS = [
    # 7 pair dengan USD
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "NZD/USD",
    # 6 EUR crosses
    "EUR/GBP", "EUR/JPY", "EUR/CHF",
    "EUR/AUD", "EUR/CAD", "EUR/NZD",
    # 5 GBP crosses
    "GBP/JPY", "GBP/CHF", "GBP/AUD",
    "GBP/CAD", "GBP/NZD",
    # 4 AUD crosses
    "AUD/JPY", "AUD/CHF", "AUD/CAD", "AUD/NZD",
    # 3 NZD crosses
    "NZD/JPY", "NZD/CHF", "NZD/CAD",
    # 2 CAD crosses
    "CAD/JPY", "CAD/CHF",
    # 1 CHF cross
    "CHF/JPY",
]


def price_decimals(pair: str) -> int:
    """JPY pairs quoted 3 desimal, sisanya 5."""
    return 3 if pair.endswith("JPY") else 5


def pip_size(pair: str) -> float:
    return 0.01 if pair.endswith("JPY") else 0.0001
