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
# Metadata per simbol non-forex: asset class, desimal harga, jarak round number.
SYMBOL_META = {
    "XAU/USD": {"class": "metal",  "decimals": 2, "round": 50.0},
    # XAG/USD butuh Twelve Data plan Grow (berbayar) — nonaktif di free tier.
    "XAG/USD": {"class": "metal",  "decimals": 3, "round": 1.0, "enabled": False},
    "BTC/USD": {"class": "crypto", "decimals": 1, "round": 1000.0},
    "ETH/USD": {"class": "crypto", "decimals": 2, "round": 100.0},
}
# Universe H1 (day trade): hanya simbol paling likuid, supaya jatah menit
# GitHub Actions (2000/bulan repo private) & Twelve Data cukup. Crypto sengaja
# TIDAK di-scan H1 (skill: crypto minimal H4, terlalu banyak wick likuidasi).
H1_SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY", "GBP/JPY", "EUR/JPY", "GBP/AUD", "XAU/USD"]
# Universe scalping M15/M30: spread paling tipis + likuid di London/NY.
# Tiap simbol = 1 request (8 detik) per run, jadi sengaja cuma 4.
SCALP_SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]

EXTRA_SYMBOLS = [s for s, m in SYMBOL_META.items() if m.get("enabled", True)]
SCAN_SYMBOLS = MAJOR_PAIRS + EXTRA_SYMBOLS

# --- Saham (sumber data Yahoo Finance, D1 saja) -----------------------------
# Format simbol = format Yahoo: US tanpa suffix, IDX pakai ".JK".
# Skill: universe US minimal S&P 500, IDX minimal LQ45 (small cap = profile bisa
# dibentuk 1-2 broker). Tambah/kurangi di sini; tiap simbol = 1 request/hari.
STOCK_US_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    "JPM", "V", "XOM", "UNH", "COST", "NFLX", "AMD",
]
STOCK_IDX_SYMBOLS = [
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "TLKM.JK", "ASII.JK", "UNTR.JK",
    "ANTM.JK", "ADRO.JK", "PTBA.JK", "ICBP.JK", "INDF.JK", "KLBF.JK", "AMRT.JK",
    "CPIN.JK", "MDKA.JK", "BRPT.JK", "EXCL.JK", "PGAS.JK", "SMGR.JK",
]
for _s in STOCK_US_SYMBOLS:
    SYMBOL_META[_s] = {"class": "stock_us", "decimals": 2, "round": 5.0}
for _s in STOCK_IDX_SYMBOLS:
    SYMBOL_META[_s] = {"class": "stock_idx", "decimals": 0, "round": 100.0}


def symbols_for(timeframe: str) -> list[str]:
    if timeframe == "H1":
        return list(H1_SYMBOLS)
    if timeframe in ("M15", "M30"):
        return list(SCALP_SYMBOLS)
    if timeframe == "STOCK_US":
        return list(STOCK_US_SYMBOLS)
    if timeframe == "STOCK_IDX":
        return list(STOCK_IDX_SYMBOLS)
    return list(SCAN_SYMBOLS)


def data_source(pair: str) -> str:
    """'yahoo' untuk saham, 'twelvedata' untuk forex/metal/crypto."""
    return "yahoo" if asset_class(pair).startswith("stock") else "twelvedata"


def is_stock(pair: str) -> bool:
    return asset_class(pair).startswith("stock")


def asset_class(pair: str) -> str:
    return SYMBOL_META.get(pair, {}).get("class", "forex")


def price_decimals(pair: str) -> int:
    if pair in SYMBOL_META:
        return SYMBOL_META[pair]["decimals"]
    return 3 if pair.endswith("JPY") else 5


def pip_size(pair: str) -> float:
    return 10 ** -(price_decimals(pair) - 1)


def round_step(pair: str) -> float:
    """Jarak round number psikologis untuk confluence structural."""
    if pair in SYMBOL_META:
        return SYMBOL_META[pair]["round"]
    return 1.0 if pair.endswith("JPY") else 0.01


def market_247(pair: str) -> bool:
    """Crypto buka terus; forex & metal tutup weekend."""
    return asset_class(pair) == "crypto"


def tv_exchange(pair: str) -> str:
    cls = asset_class(pair)
    if cls == "crypto":
        return "BITSTAMP"
    if cls == "stock_us":
        return "NASDAQ"
    if cls == "stock_idx":
        return "IDX"
    return "OANDA"

