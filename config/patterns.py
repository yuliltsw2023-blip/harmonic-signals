"""Katalog pattern harmonic (Carney school) — rasio ideal per leg.

Sumber: skill harmonic-pattern-trading (Carney Vol 1-3, Gartley 1935,
Gilmore, Oglesbee). Deviasi <2% = akurat, 2-5% = acceptable, >5% = INVALID.

Konvensi:
  - "ab_xa"  : retracement B terhadap leg XA
  - "bc_ab"  : retracement C terhadap leg AB
  - "cd_bc"  : extension D terhadap leg BC
  - "ad_xa"  : posisi D terhadap leg XA (retracement <1, extension >1)
  - Cypher beda referensi: "xc_xa" (C extension dari X) dan "d_xc" (D
    retracement dari leg XC).

Nilai berupa (lo, hi) untuk range, atau float tunggal untuk rasio fixed.
"""

TOLERANCE = 0.05          # >5% deviasi = invalid
ACCURATE_DEVIATION = 0.02  # <2% = akurat

# Reliability tier menentukan ceiling grade (weakest-link rubric).
PATTERNS = {
    "Bat": {
        "tier": "HIGH",
        "max_grade": "A",
        "ab_xa": (0.382, 0.500),
        "bc_ab": (0.382, 0.886),
        "cd_bc": (1.618, 2.618),
        "ad_xa": 0.886,
    },
    "Gartley": {
        "tier": "HIGH",
        "max_grade": "A",
        "ab_xa": 0.618,
        "bc_ab": (0.382, 0.886),
        "cd_bc": (1.13, 1.618),
        "ad_xa": 0.786,
    },
    "Crab": {
        "tier": "HIGH_RR",
        "max_grade": "A",
        "ab_xa": (0.382, 0.618),
        "bc_ab": (0.382, 0.886),
        "cd_bc": (2.618, 3.618),
        "ad_xa": 1.618,
    },
    "Butterfly": {
        "tier": "MEDIUM",
        "max_grade": "B",
        "ab_xa": 0.786,
        "bc_ab": (0.382, 0.886),
        "cd_bc": (1.618, 2.24),
        "ad_xa": 1.27,
    },
    "Deep Crab": {
        "tier": "MEDIUM",
        "max_grade": "B",
        "ab_xa": 0.886,
        "bc_ab": (0.382, 0.886),
        "cd_bc": (2.618, 3.618),
        "ad_xa": 1.618,
    },
    "Cypher": {
        "tier": "MEDIUM",
        "max_grade": "B",
        "ab_xa": (0.382, 0.618),
        "xc_xa": (1.272, 1.414),   # C diukur dari X, BUKAN via AB
        "d_xc": 0.786,             # D = 0.786 retracement leg XC
    },
}

# Shark / Stingray sengaja TIDAK di-scan: struktur 0XABC (labeling beda),
# reliability MEDIUM-LOW dan rubric menempatkannya di Grade C → tidak akan
# pernah dikirim. Lihat README "Known limitations".

# Level tambahan yang dicek untuk confluence PRZ (selain requirement utama).
AB_CD_PROJECTIONS = (1.0, 1.27, 1.618)   # AB=CD & alternate AB=CD
