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

# --- Risk ---------------------------------------------------------------------
SL_BUFFER_XA = 0.05        # 5% dari panjang leg XA, beyond X
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
HTF_OF = {"H4": "1day", "D1": "1week"}
HTF_OUTPUTSIZE = 120
