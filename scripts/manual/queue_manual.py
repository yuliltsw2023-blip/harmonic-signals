#!/usr/bin/env python3
"""Kirim setup yang dikonfirmasi MANUAL ke antrean EA MT5 (Upstash mt5:queue).

Tanpa --send = pratinjau saja (tidak ada yang dikirim). Contoh XAU (lihat
docs/XAU-STRATEGI-2026-09-28.md):

  # long setelah rejection M15 di PRZ Gartley, limit di 4120, SL 4111
  # long setelah rejection M15 di PRZ Gartley: limit 4120, SL 4108 → TP otomatis 2R (4144), BE di +1R
  python scripts/manual/queue_manual.py XAU/USD buy --entry 4120 --sl 4108
  # kirim sungguhan, market (entry = harga sekarang untuk guard slippage)
  python scripts/manual/queue_manual.py XAU/USD buy --entry 4121.5 --sl 4108 --order market --send

Default XAU: risiko 1,5%, SL maks 15 poin, TP = 2R, SL→BE di +1R (butuh EA v1.3).
EA: risk_pct menimpa grade (maks InpMaxRiskPct); lot < 0,01 → EA menolak.
XAU di HFM: 0,01 lot = $1 per $1 gerak harga.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap_manual  # noqa: F401,E402

from lib import state  # noqa: E402
from lib.orders import manual_event  # noqa: E402

# nilai $ per 1.0 gerak harga untuk 0,01 lot (HFM); simbol lain: isi --usd-per-point
USD_PER_POINT_MIN_LOT = {"XAU/USD": 1.0}
# default per simbol (keputusan user 28 Sep 2026, simulasi scripts/sim_ltf_zone.py --cap 15):
# XAU risiko 1,5% (EA v1.3 risk_pct), SL maks 15 poin, TP 2R + SL→BE di +1R
SYMBOL_DEFAULTS = {"XAU/USD": {"risk_pct": 1.5, "max_sl": 15.0, "exit_mode": "tpbe"}}

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("symbol")
ap.add_argument("side", choices=["buy", "sell"])
ap.add_argument("--entry", type=float, required=True, help="harga limit, atau harga sekarang kalau --order market")
ap.add_argument("--sl", type=float, required=True)
ap.add_argument("--tp1", type=float, help="default = entry ± tp-r × risiko")
ap.add_argument("--tp-r", type=float, default=2.0)
ap.add_argument("--tp2", type=float)
ap.add_argument("--tf", default="M15", choices=["M15", "M30", "H1", "H4", "D1"],
                help="TF struktur entry (juga TF trailing kalau --exit trail)")
ap.add_argument("--setup", default="GartleyD1", help="nama setup untuk label/id")
ap.add_argument("--order", default="limit", choices=["limit", "market"])
ap.add_argument("--exit", dest="exit_mode", choices=["tp", "tpbe", "trail"], help="default per simbol, lainnya tp")
ap.add_argument("--be-r", type=float, default=1.0, help="tpbe: SL→BE setelah +N R")
ap.add_argument("--grade", default="A", choices=["A", "B"])
ap.add_argument("--expires", type=float, help="jam sebelum pending dibatalkan EA (default per TF)")
ap.add_argument("--equity", type=float, default=1000.0, help="ekuitas akun untuk cek lot minimal")
ap.add_argument("--risk", type=float, default=1.0, help="InpRiskPct di EA")
ap.add_argument("--risk-pct", type=float, help="risiko khusus event (EA v1.3), default per simbol")
ap.add_argument("--max-sl", type=float, help="jarak SL maksimal (poin), default per simbol")
ap.add_argument("--usd-per-point", type=float)
ap.add_argument("--min-rr", type=float, default=2.0)
ap.add_argument("--send", action="store_true", help="RPUSH ke mt5:queue (tanpa ini = pratinjau)")
a = ap.parse_args()
d = SYMBOL_DEFAULTS.get(a.symbol, {})
a.exit_mode = a.exit_mode or d.get("exit_mode", "tp")
a.risk_pct = a.risk_pct if a.risk_pct is not None else d.get("risk_pct")
a.max_sl = a.max_sl if a.max_sl is not None else d.get("max_sl")
if a.tp1 is None:
    a.tp1 = a.entry + (1 if a.side == "buy" else -1) * a.tp_r * abs(a.entry - a.sl)

try:
    ev = manual_event(a.symbol, a.side, a.entry, a.sl, a.tp1, a.tp2, a.tf, a.setup,
                      order=a.order, exit_mode=a.exit_mode, grade=a.grade, expires_hours=a.expires,
                      risk_pct=a.risk_pct, be_r=a.be_r)
except ValueError as e:
    sys.exit(f"❌ {e}")

risk_pts = abs(a.entry - a.sl)
rr1 = abs(a.tp1 - a.entry) / risk_pts
risk_pct = a.risk_pct or (a.risk if a.grade == "A" else a.risk / 2)
budget = a.equity * risk_pct / 100
upp = a.usd_per_point or USD_PER_POINT_MIN_LOT.get(a.symbol)

print(json.dumps(ev, indent=2, ensure_ascii=False))
print(f"\nRisiko {risk_pts:.2f} poin · R:R TP1 {rr1:.2f}" + (f" · TP2 {abs(a.tp2 - a.entry) / risk_pts:.2f}" if a.tp2 else ""))
problems = []
if a.max_sl and risk_pts > a.max_sl:
    problems.append(f"SL {risk_pts:.1f} poin > batas {a.max_sl:g} poin untuk {a.symbol}")
if rr1 < a.min_rr:
    problems.append(f"R:R ke TP1 {rr1:.2f} < {a.min_rr}")
if upp:
    loss_min_lot = risk_pts * upp
    print(f"Rugi di lot minimal: ${loss_min_lot:.2f} · anggaran risiko {risk_pct:g}%: ${budget:.2f}")
    if loss_min_lot > budget:
        problems.append(f"SL {risk_pts:.1f} poin > {budget / upp:.1f} poin maksimal → EA akan menolak (lot < minimal)")
else:
    print("(nilai per poin tidak diketahui untuk simbol ini — cek lot minimal sendiri)")

if problems:
    print("\n⛔ " + "\n⛔ ".join(problems))
    sys.exit(1)

if not a.send:
    print("\nPratinjau saja. Tambah --send untuk mengirim ke antrean EA.")
    sys.exit(0)

r = state._client()
if r is None:
    sys.exit("❌ UPSTASH_REDIS_REST_URL/TOKEN tidak ada di .env")
halt = r.get(state.HALT_KEY)
if halt:
    print(f"⚠️ mt5:halt = {halt} — EA akan SKIP event ini sampai /on")
state.push_order_event(ev)
print(f"✅ terkirim ke {state.ORDER_QUEUE} (panjang antrean sekarang {r.llen(state.ORDER_QUEUE)}). "
      "EA polling tiap ~20 detik; hasilnya muncul sebagai pesan '🤖 MT5 EA' di Telegram.")
