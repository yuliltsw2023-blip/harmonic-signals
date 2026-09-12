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

# --- HTF ---------------------------------------------------------------------
# Timeframe HTF untuk alignment check, di-fetch lazy (hanya pair yang punya
# kandidat lolos pre-grade) supaya hemat budget Twelve Data.
HTF_OF = {"H1": "4h", "H4": "1day", "D1": "1week"}
HTF_OUTPUTSIZE = 120


def env(name: str, default: str = "") -> str:
    """Baca env var dan buang spasi/enter di ujung — secret yang di-paste ke
    GitHub sering kebawa newline dan bikin 'Illegal header value'."""
    return os.environ.get(name, default).strip()
