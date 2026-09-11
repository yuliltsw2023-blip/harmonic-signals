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


# Non-forex yang ikut di-scan. Asset class menentukan desimal, lebar PRZ,
# buffer SL, round number, jam pasar, dan exchange TradingView.
EXTRA_SYMBOLS = ["XAU/USD", "BTC/USD"]
SCAN_SYMBOLS = MAJOR_PAIRS + EXTRA_SYMBOLS

ASSET_CLASS = {"XAU/USD": "metal", "BTC/USD": "crypto"}


def asset_class(pair: str) -> str:
    return ASSET_CLASS.get(pair, "forex")


def price_decimals(pair: str) -> int:
    ac = asset_class(pair)
    if ac == "crypto":
        return 1
    if ac == "metal":
        return 2
    return 3 if pair.endswith("JPY") else 5


def pip_size(pair: str) -> float:
    return 10 ** -(price_decimals(pair) - 1)


def round_step(pair: str) -> float:
    """Jarak round number psikologis untuk confluence structural."""
    ac = asset_class(pair)
    if ac == "crypto":
        return 1000.0
    if ac == "metal":
        return 50.0
    return 1.0 if pair.endswith("JPY") else 0.01


def market_247(pair: str) -> bool:
    """Crypto buka terus; forex & metal tutup weekend."""
    return asset_class(pair) == "crypto"


def tv_exchange(pair: str) -> str:
    return "BITSTAMP" if asset_class(pair) == "crypto" else "OANDA"
