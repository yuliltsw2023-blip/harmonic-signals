"""Smart Money Concepts mekanis untuk rencana trading XAU.

Alur user: LIQUIDITY → STRUCTURE → POI → ENTRY (konfirmasi).
TF: bias & liquidity besar H1, struktur + POI M15, konfirmasi MSS/CHoCH M5.

Semua fungsi murni di atas candle [[epoch, o, h, l, c], ...] (lama → baru),
dipakai briefing (goldnews/trade.py) DAN backtest (scripts/backtest_smc.py),
supaya aturan yang diuji = aturan yang dikirim.

Definisi (sengaja sederhana & bisa diuji):
- Swing: fractal k bar kiri-kanan.
- BOS: close menembus swing terakhir searah tren. CHoCH: close menembus swing
  berlawanan tren (tren berbalik). MSS: CHoCH dengan displacement (body ≥ 1×ATR
  atau meninggalkan FVG).
- Liquidity: swing high/low yang belum diambil (BSL di atas / SSL di bawah),
  equal highs/lows, PDH/PDL, high/low Asia. Sweep: wick menembus level tapi close
  kembali di sisi semula (dan tidak close di luar dalam 2 bar berikutnya).
- POI: FVG belum terisi penuh, Order Block (candle berlawanan terakhir sebelum
  pergerakan yang membuat BOS/CHoCH), Breaker (OB yang ditembus close → berbalik
  fungsi), Supply/Demand (OB diperlebar sampai ujung swing asal).
"""

from __future__ import annotations

from dataclasses import dataclass, field



def atr(bars: list, n: int = 14) -> list[float]:
    out, a, prev = [], None, None
    for t, o, h, l, c in bars:
        tr = h - l if prev is None else max(h - l, abs(h - prev), abs(l - prev))
        a = tr if a is None else (a * (n - 1) + tr) / n
        out.append(a)
        prev = c
    return out


@dataclass
class Event:
    kind: str      # BOS / CHoCH / MSS
    dir: str       # bull / bear
    i: int         # index bar penembus
    t: int
    level: float
    swing_i: int   # index swing yang ditembus


@dataclass
class Zone:
    kind: str      # FVG / OB / BREAKER / SUPPLY / DEMAND
    dir: str       # bull (tempat buy) / bear (tempat sell)
    lo: float
    hi: float
    i: int
    t: int
    status: str = "fresh"   # fresh / tersentuh / terisi
    tf: str = ""


@dataclass
class Analysis:
    tf: str
    trend: str                         # bull / bear / none
    swings: list = field(default_factory=list)   # (i, t, 'H'/'L', price, label HH/LH/HL/LL)
    events: list = field(default_factory=list)
    zones: list = field(default_factory=list)
    sweeps: list = field(default_factory=list)   # (i, t, side 'BSL'/'SSL', level, name)
    pools: list = field(default_factory=list)    # (side, level, name) belum diambil
    atr: float = 0.0


# ------------------------------------------------------------------ swing & struktur

def pivots(bars: list, k: int) -> list[tuple[int, str, float]]:
    out = []
    for i in range(k, len(bars) - k):
        h, l = bars[i][2], bars[i][3]
        # kiri ketat, kanan boleh sama (puncak datar dihitung sekali, di bar pertama)
        if all(h > bars[j][2] for j in range(i - k, i)) and all(h >= bars[j][2] for j in range(i + 1, i + k + 1)):
            out.append((i, "H", h))
        if all(l < bars[j][3] for j in range(i - k, i)) and all(l <= bars[j][3] for j in range(i + 1, i + k + 1)):
            out.append((i, "L", l))
    return out


def structure(bars: list, k: int, a: list[float]) -> tuple[str, list[Event], list]:
    piv = pivots(bars, k)
    by_conf: dict[int, list] = {}
    for p in piv:
        by_conf.setdefault(p[0] + k, []).append(p)   # baru 'diketahui' k bar kemudian
    trend = "none"
    last_h = last_l = None
    events: list[Event] = []
    labeled = []
    prev_h = prev_l = None
    for i in range(len(bars)):
        for p in by_conf.get(i, []):
            if p[1] == "H":
                lab = "HH" if prev_h is None or p[2] > prev_h else "LH"
                prev_h, last_h = p[2], p
            else:
                lab = "HL" if prev_l is None or p[2] > prev_l else "LL"
                prev_l, last_l = p[2], p
            labeled.append((p[0], bars[p[0]][0], p[1], p[2], lab))
        c, o = bars[i][4], bars[i][1]
        disp = abs(c - o) >= a[i] or _fvg_at(bars, i)
        if last_h and c > last_h[2]:
            kind = "BOS" if trend == "bull" else ("MSS" if disp else "CHoCH")
            events.append(Event(kind, "bull", i, bars[i][0], last_h[2], last_h[0]))
            trend, last_h = "bull", None
        elif last_l and c < last_l[2]:
            kind = "BOS" if trend == "bear" else ("MSS" if disp else "CHoCH")
            events.append(Event(kind, "bear", i, bars[i][0], last_l[2], last_l[0]))
            trend, last_l = "bear", None
    return trend, events, labeled


def _fvg_at(bars: list, i: int) -> bool:
    """Bar i adalah candle tengah FVG (gap antara i-1 dan i+1)."""
    if i < 1 or i + 1 >= len(bars):
        return False
    return bars[i - 1][3] > bars[i + 1][2] or bars[i - 1][2] < bars[i + 1][3]


# ------------------------------------------------------------------ POI

def fvgs(bars: list, tf: str, min_size: float) -> list[Zone]:
    out = []
    for i in range(1, len(bars) - 1):
        a, c = bars[i - 1], bars[i + 1]
        if a[3] > c[2] and a[3] - c[2] >= min_size:
            z = Zone("FVG", "bear", c[2], a[3], i, bars[i][0], tf=tf)
        elif a[2] < c[3] and c[3] - a[2] >= min_size:
            z = Zone("FVG", "bull", a[2], c[3], i, bars[i][0], tf=tf)
        else:
            continue
        _status(z, bars[i + 2:])
        if z.status != "terisi":
            out.append(z)
    return out


def _status(z: Zone, later: list) -> None:
    for b in later:
        if z.dir == "bear":
            if b[4] > z.hi or (z.kind == "FVG" and b[2] >= z.hi):
                z.status = "terisi"
                return
            if b[2] >= z.lo:
                z.status = "tersentuh"
        else:
            if b[4] < z.lo or (z.kind == "FVG" and b[3] <= z.lo):
                z.status = "terisi"
                return
            if b[3] <= z.hi:
                z.status = "tersentuh"


def order_blocks(bars: list, events: list[Event], tf: str, max_h: float = 1e9) -> list[Zone]:
    """OB + Supply/Demand dari setiap BOS/CHoCH/MSS; OB yang ditembus → Breaker."""
    out = []
    for ev in events:
        lo_i = ev.swing_i
        # asal pergerakan = swing ekstrem berlawanan sebelum penembusan
        rng = range(max(0, lo_i - 30), ev.i)
        if ev.dir == "bear":
            origin = max(rng, key=lambda j: bars[j][2])
            cand = [j for j in range(origin, ev.i) if bars[j][4] > bars[j][1]]
            j = cand[-1] if cand else origin
            ob = Zone("OB", "bear", bars[j][3], bars[j][2], j, bars[j][0], tf=tf)
            sd = Zone("SUPPLY", "bear", min(bars[j][1], bars[j][4]), bars[origin][2], origin, bars[origin][0], tf=tf)
        else:
            origin = min(rng, key=lambda j: bars[j][3])
            cand = [j for j in range(origin, ev.i) if bars[j][4] < bars[j][1]]
            j = cand[-1] if cand else origin
            ob = Zone("OB", "bull", bars[j][3], bars[j][2], j, bars[j][0], tf=tf)
            sd = Zone("DEMAND", "bull", bars[origin][3], max(bars[j][1], bars[j][4]), origin, bars[origin][0], tf=tf)
        for z in (ob, sd):
            if z.hi - z.lo > max_h:      # zona terlalu lebar bukan POI yang berguna
                continue
            _status(z, bars[ev.i + 1:])
            if z.kind == "OB" and z.status == "terisi":
                # ditembus close → breaker berbalik fungsi
                br = Zone("BREAKER", "bull" if z.dir == "bear" else "bear", z.lo, z.hi, z.i, z.t, tf=tf)
                brk = next(k for k in range(ev.i + 1, len(bars))
                           if (bars[k][4] > z.hi if z.dir == "bear" else bars[k][4] < z.lo))
                _status(br, bars[brk + 1:])
                if br.status != "terisi":
                    out.append(br)
            elif z.status != "terisi":
                out.append(z)
    return out


# ------------------------------------------------------------------ liquidity

def liquidity(bars: list, k: int, a: list[float], named: dict[str, float], lookback: int) -> tuple[list, list]:
    """→ (sweeps dalam `lookback` bar terakhir, pools yang belum diambil)."""
    piv = pivots(bars, k)
    levels = [("BSL" if p[1] == "H" else "SSL", p[2], f"swing {'high' if p[1] == 'H' else 'low'}", p[0]) for p in piv]
    for name, v in named.items():
        if v:
            side = "BSL" if "high" in name.lower() or "High" in name else "SSL"
            levels.append((side, v, name, -1))
    # equal highs/lows
    tol = (a[-1] if a else 1.0) * 0.1
    hs = [p for p in piv if p[1] == "H"][-12:]
    ls = [p for p in piv if p[1] == "L"][-12:]
    for grp, side in ((hs, "BSL"), (ls, "SSL")):
        for x in range(len(grp)):
            for y in range(x + 1, len(grp)):
                if abs(grp[x][2] - grp[y][2]) <= tol:
                    levels.append((side, max(grp[x][2], grp[y][2]) if side == "BSL" else min(grp[x][2], grp[y][2]),
                                   "equal highs" if side == "BSL" else "equal lows", grp[y][0]))
    sweeps, pools = [], []
    n = len(bars)
    for side, lvl, name, start in levels:
        s = max(start + 1, 0) if start >= 0 else max(0, n - lookback * 4)
        taken = False
        for j in range(s, n):
            h, l, c = bars[j][2], bars[j][3], bars[j][4]
            pierce = h > lvl if side == "BSL" else l < lvl
            if not pierce:
                continue
            back = c < lvl if side == "BSL" else c > lvl
            nxt = bars[j + 1:j + 3]
            held = all((b[4] < lvl) if side == "BSL" else (b[4] > lvl) for b in nxt)
            if back and held and j >= n - lookback:
                sweeps.append((j, bars[j][0], side, lvl, name))
            taken = True
            break
        if not taken:
            pools.append((side, lvl, name))
    sweeps.sort(key=lambda x: x[0])
    return sweeps, pools


# ------------------------------------------------------------------ gabungan

def analyze(bars: list, tf: str, k: int, named: dict[str, float] | None = None,
            lookback: int = 48) -> Analysis:
    a = atr(bars)
    trend, events, labeled = structure(bars, k, a)
    zones = fvgs(bars, tf, 0.15 * a[-1]) + order_blocks(bars, events, tf, max_h=2.0 * a[-1])
    sweeps, pools = liquidity(bars, k, a, named or {}, lookback)
    return Analysis(tf, trend, labeled, events, zones, sweeps, pools, a[-1])


def checklist(direction: str, h1: Analysis, m15: Analysis, m5: Analysis,
              m15_bars: list, m5_bars: list, price: float, window: int = 32) -> dict:
    """Status 4 langkah (mekanis) untuk arah 'sell' atau 'buy'.
    window = berapa bar M15 ke belakang alur dianggap masih berlaku (32 = 8 jam)."""
    bear = direction == "sell"
    side = "BSL" if bear else "SSL"
    d = "bear" if bear else "bull"
    t_min = m15_bars[-window][0] if len(m15_bars) >= window else m15_bars[0][0]
    res = {"liquidity": None, "structure": None, "poi": None, "confirmation": None}

    sw = [s for s in m15.sweeps + h1.sweeps + m5.sweeps if s[2] == side and s[1] >= t_min]
    if sw:
        s = max(sw, key=lambda x: x[1])
        res["liquidity"] = {"t": s[1], "level": s[3], "name": s[4]}
    t_sweep = res["liquidity"]["t"] if res["liquidity"] else t_min

    ev = [e for e in m15.events if e.dir == d and e.t >= t_sweep]
    if ev:
        e = ev[0]
        res["structure"] = {"t": e.t, "kind": e.kind, "level": e.level}
    t_struct = res["structure"]["t"] if res["structure"] else None

    if t_struct:
        cands = [z for z in m15.zones + h1.zones if z.dir == d and z.status != "terisi"]
        touched = []
        for z in cands:
            for b in m15_bars:
                if b[0] <= t_struct:
                    continue
                inside = b[2] >= z.lo if bear else b[3] <= z.hi
                if inside and (b[3] <= z.hi if bear else b[2] >= z.lo):
                    touched.append((b[0], z))
                    break
        if touched:
            tt, z = min(touched, key=lambda x: x[0])
            res["poi"] = {"t": tt, "kind": z.kind, "tf": z.tf, "lo": z.lo, "hi": z.hi}
    if res["poi"]:
        ev5 = [e for e in m5.events if e.dir == d and e.kind in ("CHoCH", "MSS") and e.t >= res["poi"]["t"]]
        if ev5:
            res["confirmation"] = {"t": ev5[-1].t, "kind": ev5[-1].kind, "level": ev5[-1].level}

    # alur harus masih 'hidup': struktur M15 & M5 terakhir belum berbalik,
    # dan konfirmasi masih segar (≤ 6 bar M5 = 30 menit)
    stale = []
    if res["structure"] and m15.events and m15.events[-1].dir != d:
        stale.append(f"struktur M15 sudah berbalik ({m15.events[-1].kind} {m15.events[-1].dir})")
    if res["confirmation"]:
        last5 = [e for e in m5.events if e.kind in ("CHoCH", "MSS")]
        if last5 and last5[-1].dir != d:
            stale.append(f"M5 sudah berbalik ({last5[-1].kind} {last5[-1].dir})")
        if m5_bars[-1][0] - res["confirmation"]["t"] > 6 * 300:
            stale.append("konfirmasi M5 sudah > 30 menit")
    res["stale"] = stale
    res["complete"] = all(res[k] for k in ("liquidity", "structure", "poi", "confirmation")) and not stale
    return res


def fmt_ts(t: int) -> str:
    from datetime import datetime, timedelta, timezone
    return datetime.fromtimestamp(t, timezone(timedelta(hours=7))).strftime("%a %d/%m %H:%M")


def describe(an: Analysis, price: float, max_items: int = 6, zones: bool = True) -> list[str]:
    """Ringkasan teks untuk prompt Claude."""
    L = [f"### {an.tf} — tren struktur: {an.trend}, ATR {an.atr:.2f}"]
    sw = an.swings[-8:]
    L.append("Swing terakhir: " + ", ".join(f"{lab} {p:.2f} ({fmt_ts(t)})" for _, t, _, p, lab in sw))
    L.append("Event struktur: " + (", ".join(f"{e.kind} {e.dir} tembus {e.level:.2f} ({fmt_ts(e.t)})"
                                              for e in an.events[-5:]) or "-"))
    L.append("Sweep liquidity terbaru: " + (", ".join(f"{s[2]} {s[4]} {s[3]:.2f} ({fmt_ts(s[1])})"
                                                       for s in an.sweeps[-4:]) or "-"))
    above = sorted([p for p in an.pools if p[0] == "BSL" and p[1] > price], key=lambda p: p[1])[:3]
    below = sorted([p for p in an.pools if p[0] == "SSL" and p[1] < price], key=lambda p: -p[1])[:3]
    L.append("Liquidity belum diambil di atas (BSL): " + (", ".join(f"{p[1]:.2f} {p[2]}" for p in above) or "-"))
    L.append("Liquidity belum diambil di bawah (SSL): " + (", ".join(f"{p[1]:.2f} {p[2]}" for p in below) or "-"))
    if not zones:
        return L
    zs = sorted(an.zones, key=lambda z: abs((z.lo + z.hi) / 2 - price))[:max_items]
    L.append("POI terdekat: " + (", ".join(f"{z.kind} {z.dir} {z.lo:.2f}–{z.hi:.2f} [{z.status}] ({fmt_ts(z.t)})"
                                           for z in zs) or "-"))
    return L
