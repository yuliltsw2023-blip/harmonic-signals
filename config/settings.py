"""Runtime settings — semua tunable dikumpulkan di sini."""

import os

# --- Pivot detection ---------------------------------------------------------
PIVOT_LEFT = 3
PIVOT_RIGHT = 3
# Leg minimum (dalam kelipatan ATR14) supaya noise kecil tidak jadi pivot.
MIN_LEG_ATR = 1.0

# --- Candidate filters -------------------------------------------------------
# Projected D: harga sekarang harus sudah "dekat" PRZ, dinyatakan dalam
# persen dari harga. Forex: 0.35% (~35 pip di 1.0000).
PRZ_APPROACH_PCT = 0.0035
# Completed D: pivot D harus terbentuk maksimal N bar yang lalu.
MAX_D_AGE_BARS = 6
# PRZ zone valid kalau range < 0.5% (forex). Level di luar band ini tidak
# dihitung sebagai confluence.
PRZ_BAND_PCT = 0.005
# Structural level: swing high/low sebelumnya dianggap confluence kalau
# masuk dalam PRZ band.
STRUCTURAL_LOOKBACK_PIVOTS = 12

# --- Per asset class (skill: cross-asset adjustments) ------------------------
# prz_band   : level dihitung convergent kalau dalam +/-band dari level utama
# approach   : jarak harga ke PRZ yang masih dianggap actionable
# sl_buf_xa  : buffer SL = persen panjang XA
# sl_min_pct : buffer SL minimum sebagai persen harga (crypto 1.5% beyond X)
ASSET_PARAMS = {
    "forex":  {"prz_band": 0.005, "approach": 0.0035, "sl_buf_xa": 0.05, "sl_min_pct": 0.0},
    "metal":  {"prz_band": 0.006, "approach": 0.0040, "sl_buf_xa": 0.05, "sl_min_pct": 0.0},
    "crypto": {"prz_band": 0.010, "approach": 0.0060, "sl_buf_xa": 0.10, "sl_min_pct": 0.015},
    # Saham (data Yahoo, D1): gap & tick lebih lebar → band lebih longgar.
    "stock_us":  {"prz_band": 0.015, "approach": 0.0150, "sl_buf_xa": 0.05, "sl_min_pct": 0.0},
    "stock_idx": {"prz_band": 0.020, "approach": 0.0200, "sl_buf_xa": 0.05, "sl_min_pct": 0.0},
}


def asset_params(pair: str) -> dict:
    from config.pairs import asset_class
    return ASSET_PARAMS[asset_class(pair)]


# --- Risk ---------------------------------------------------------------------
SL_BUFFER_XA = 0.05        # 5% dari panjang leg XA, beyond X (default forex)
MIN_RR_TP2_PREGRADE = 1.5  # di bawah ini langsung FAIL sebelum ke Claude

# --- Grading ------------------------------------------------------------------
GRADE_RR_A = 3.0
GRADE_RR_B = 2.0
CONFLUENCE_A = 4
CONFLUENCE_B = 3

# --- Claude ---------------------------------------------------------------------
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
CLAUDE_MAX_TOKENS = 4096

# --- POC Pullback screener (skill poc-pullback-entry) -------------------------
POC_ENABLED = os.environ.get("POC_ENABLED", "true").lower() == "true"
# Pivot N kiri/kanan per timeframe (skill: 5 untuk H1–H4, 3 untuk D1+).
POC_PIVOT = {"H1": 5, "H4": 5, "D1": 3}
POC_MIN_LEG_BARS = 8       # leg < ini → profile tidak representatif
POC_LEG_BARS_A = 10
POC_BINS = 40
POC_VA_PCT = 0.70
# Kedalaman POC relatif leg: di luar [MIN, MAX] = skip; IDEAL = Grade A
POC_DEPTH_MIN, POC_DEPTH_MAX = 0.20, 0.79
POC_DEPTH_IDEAL = (0.38, 0.62)
# Harga dianggap "mendekati" VA kalau jaraknya ke VAH/VAL <= persen ini.
POC_APPROACH_PCT = {"forex": 0.0035, "metal": 0.0040, "crypto": 0.0080,
                    "stock_us": 0.0150, "stock_idx": 0.0200}
# Buffer SL = kelipatan ATR14 (skill: forex 0.1–0.2, crypto 0.3–0.5, saham 0.3)
POC_SL_ATR = {"forex": 0.2, "metal": 0.2, "crypto": 0.4, "stock_us": 0.3, "stock_idx": 0.3}

# --- HTF ---------------------------------------------------------------------
# Timeframe HTF untuk alignment check, di-fetch lazy (hanya pair yang punya
# kandidat lolos pre-grade) supaya hemat budget Twelve Data.
HTF_OF = {"H1": "4h", "H4": "1day", "D1": "1week"}
HTF_OUTPUTSIZE = 120


def env(name: str, default: str = "") -> str:
    """Baca env var dan buang spasi/enter di ujung — secret yang di-paste ke
    GitHub sering kebawa newline dan bikin 'Illegal header value'."""
    return os.environ.get(name, default).strip()
