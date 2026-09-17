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
# entry_tol  : toleransi di luar tepi PRZ yang masih dihitung "sudah di zona"
#              (ENTRY_MODE=in_prz) — forex 8 pip di 1.0000, crypto 0.25%
ASSET_PARAMS = {
    "forex":  {"prz_band": 0.005, "approach": 0.0035, "entry_tol": 0.0008, "sl_buf_xa": 0.05, "sl_min_pct": 0.0},
    "metal":  {"prz_band": 0.006, "approach": 0.0040, "entry_tol": 0.0010, "sl_buf_xa": 0.05, "sl_min_pct": 0.0},
    "crypto": {"prz_band": 0.010, "approach": 0.0060, "entry_tol": 0.0025, "sl_buf_xa": 0.10, "sl_min_pct": 0.015},
    # Saham (data Yahoo, D1): gap & tick lebih lebar → band lebih longgar.
    "stock_us":  {"prz_band": 0.015, "approach": 0.0150, "entry_tol": 0.0050, "sl_buf_xa": 0.05, "sl_min_pct": 0.0},
    "stock_idx": {"prz_band": 0.020, "approach": 0.0200, "entry_tol": 0.0100, "sl_buf_xa": 0.05, "sl_min_pct": 0.0},
}

# Skala parameter jarak (prz_band / approach / entry_tol) per timeframe.
# Struktur XABCD di M15 jauh lebih pendek dari H4 → band 0.5% harga bakal
# "menelan" semua level Fib dan confluence jadi palsu. H1/H4/D1 tetap 1.0
# (sudah live, tidak diubah).
TF_SCALE = {"M15": 0.3, "M30": 0.4, "H1": 1.0, "H4": 1.0, "D1": 1.0}


def tf_scale(timeframe: str | None) -> float:
    return TF_SCALE.get(timeframe or "", 1.0)


def asset_params(pair: str, timeframe: str | None = None) -> dict:
    from config.pairs import asset_class
    base = ASSET_PARAMS[asset_class(pair)]
    k = tf_scale(timeframe)
    if k == 1.0:
        return base
    return {**base, "prz_band": base["prz_band"] * k, "approach": base["approach"] * k,
            "entry_tol": base["entry_tol"] * k}


# --- Tahap sinyal harmonic (dua pesan per setup, seperti POC) -----------------
# approaching : harga ≤ approach dari tepi PRZ, belum masuk → "SIAPKAN ORDER":
#               pasang limit order di mid PRZ + SL + TP, lalu tinggal.
# in_prz      : harga sudah di dalam PRZ (± entry_tol) → "MASUK ZONA":
#               limit harusnya aktif; kalau belum pasang, boleh entry sekarang.
# left        : D sudah terbentuk dan harga sudah lewat PRZ menuju TP → pesan
#               teks "jangan kejar" (hanya kalau tahap sebelumnya pernah dikirim).
# Tahap lain (far/pierced) tidak pernah dikirim. Atur lewat env SIGNAL_STAGES,
# mis. "in_prz" saja kalau cuma mau pesan saat harga sudah di zona.
SIGNAL_STAGES = tuple(
    s.strip().lower() for s in os.environ.get("SIGNAL_STAGES", "approaching,in_prz,left").split(",") if s.strip()
)


# --- Risk ---------------------------------------------------------------------
SL_BUFFER_XA = 0.05        # 5% dari panjang leg XA, beyond X (default forex)
# R:R minimum ke TP2 (harmonic) / R:R efektif (POC); di bawah ini langsung
# FAIL sebelum ke Claude. Default 2.0 (permintaan user: minimal 1:2).
MIN_RR_TP2_PREGRADE = float(os.environ.get("MIN_RR_TP2", "2.0").strip() or 2.0)

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
POC_PIVOT = {"M15": 5, "M30": 5, "H1": 5, "H4": 5, "D1": 3}
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
HTF_OF = {"M15": "1h", "M30": "4h", "H1": "4h", "H4": "1day", "D1": "1week"}
HTF_OUTPUTSIZE = 120


def env(name: str, default: str = "") -> str:
    """Baca env var dan buang spasi/enter di ujung — secret yang di-paste ke
    GitHub sering kebawa newline dan bikin 'Illegal header value'."""
    return os.environ.get(name, default).strip()
