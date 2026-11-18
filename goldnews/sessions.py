"""Jadwal slot notifikasi & hasil sesi Asia / London / NY.

Semua jam dihitung lewat zoneinfo, jadi pergantian DST Eropa/AS otomatis:
  pre_asia   06:30 WIB (Asia/Jakarta, tanpa DST)      → outlook sesi Asia
  pre_london 07:30 waktu London (14:30 WIB musim dingin) → outlook London
  pre_ny     07:30 waktu New York (19:30 WIB musim dingin) → outlook NY
  post_us    09:00 waktu New York (21:00 WIB musim dingin) → reaksi data AS
  weekly     Sabtu 06:30 WIB → rekap mingguan + outlook minggu depan

Sesi (tidak tumpang tindih, supaya labelnya jelas):
  asia   00:00 UTC (07:00 WIB, Tokyo buka) → London buka 08:00 London
  london 08:00 London → NY buka 08:00 New York
  ny     08:00 New York → 17:00 New York (penutupan harian)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
WIB = ZoneInfo("Asia/Jakarta")
LDN = ZoneInfo("Europe/London")
NYC = ZoneInfo("America/New_York")

SESSION_NAMES = {"asia": "Asia", "london": "London", "ny": "New York"}


@dataclass(frozen=True)
class SlotDef:
    key: str
    tz: ZoneInfo
    at: time
    weekdays: tuple[int, ...]   # weekday() di zona slot (0 = Senin)
    target: str                 # sesi yang di-outlook-kan
    label: str


SLOTS = (
    SlotDef("pre_asia", WIB, time(6, 30), (0, 1, 2, 3, 4), "asia", "Pra-Asia"),
    SlotDef("weekly", WIB, time(6, 30), (5,), "week", "Rekap Mingguan"),
    SlotDef("pre_london", LDN, time(7, 30), (0, 1, 2, 3, 4), "london", "Pra-London"),
    SlotDef("pre_ny", NYC, time(7, 30), (0, 1, 2, 3, 4), "ny", "Pra-New York"),
    SlotDef("post_us", NYC, time(9, 0), (0, 1, 2, 3, 4), "ny", "Reaksi Data AS"),
)
SLOT_BY_KEY = {s.key: s for s in SLOTS}

# Run boleh datang sedikit lebih awal (cron cadangan GitHub di menit :20) atau
# terlambat (antrean GitHub bisa 5–60 menit).
EARLY = timedelta(minutes=25)
LATE = timedelta(minutes=150)


def slot_time(slot: SlotDef, day: date) -> datetime:
    """Jam slot (UTC) untuk tanggal lokal `day` di zona slot."""
    return datetime.combine(day, slot.at, tzinfo=slot.tz).astimezone(UTC)


def slot_id(slot: SlotDef, when_utc: datetime) -> str:
    local = when_utc.astimezone(WIB)
    return f"{local:%Y-%m-%d}_{slot.key}"


def due_slots(now: datetime) -> list[tuple[SlotDef, datetime]]:
    """Slot yang jendela waktunya mencakup `now` (urut terbaru dulu)."""
    now = now.astimezone(UTC)
    out = []
    for slot in SLOTS:
        for delta in (-1, 0, 1):
            day = now.astimezone(slot.tz).date() + timedelta(days=delta)
            if day.weekday() not in slot.weekdays:
                continue
            t = slot_time(slot, day)
            if t - EARLY <= now <= t + LATE:
                out.append((slot, t))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def session_window(name: str, day: date) -> tuple[datetime, datetime]:
    """Jendela UTC sesi untuk 'hari trading' `day` (= tanggal UTC sesi Asia)."""
    ldn_open = datetime.combine(day, time(8, 0), tzinfo=LDN).astimezone(UTC)
    ny_open = datetime.combine(day, time(8, 0), tzinfo=NYC).astimezone(UTC)
    ny_close = datetime.combine(day, time(17, 0), tzinfo=NYC).astimezone(UTC)
    if name == "asia":
        return datetime.combine(day, time(0, 0), tzinfo=UTC), ldn_open
    if name == "london":
        return ldn_open, ny_open
    if name == "ny":
        return ny_open, ny_close
    raise ValueError(name)


def wib(dt: datetime) -> str:
    return dt.astimezone(WIB).strftime("%H:%M")


def session_hours_wib(name: str, day: date) -> str:
    a, b = session_window(name, day)
    return f"{wib(a)}–{wib(b)} WIB"


# ---------------------------------------------------------------- statistik

def adr(candles: list[list[float]], days: int = 20) -> float:
    """Rata-rata range harian (per tanggal UTC, hari kerja) dari candle 15m."""
    by_day: dict[str, list[float]] = {}
    for t, o, h, l, c in candles:
        d = datetime.fromtimestamp(t, UTC)
        if d.weekday() >= 5:
            continue
        k = d.strftime("%Y-%m-%d")
        hi_lo = by_day.setdefault(k, [h, l])
        hi_lo[0] = max(hi_lo[0], h)
        hi_lo[1] = min(hi_lo[1], l)
    ranges = [hl[0] - hl[1] for k, hl in sorted(by_day.items())][-(days + 1):-1]
    return sum(ranges) / len(ranges) if ranges else 0.0


def classify(o: float, h: float, l: float, c: float, ref_range: float) -> str:
    """Bullish / Bearish / Sideways dari satu sesi.

    Arah dianggap jelas kalau perubahan open→close ≥ 20% ADR DAN close berada
    di 40% teratas (bullish) / terbawah (bearish) range sesi. Sisanya Sideways
    (termasuk sesi lebar yang bolak-balik)."""
    rng = h - l
    if rng <= 0 or ref_range <= 0:
        return "sideways"
    chg = c - o
    pos = (c - l) / rng
    if abs(chg) < 0.2 * ref_range:
        return "sideways"
    if chg > 0 and pos >= 0.6:
        return "bullish"
    if chg < 0 and pos <= 0.4:
        return "bearish"
    return "sideways"


def session_stats(candles: list[list[float]], name: str, day: date,
                  now: datetime, ref_range: float) -> dict | None:
    a, b = session_window(name, day)
    if now <= a:
        return None
    ta, tb, tn = a.timestamp(), b.timestamp(), now.timestamp()
    bars = [x for x in candles if ta <= x[0] < tb and x[0] + 900 <= tn]
    if not bars:
        return None
    o, c = bars[0][1], bars[-1][4]
    h = max(x[2] for x in bars)
    l = min(x[3] for x in bars)
    return {
        "session": name,
        "name": SESSION_NAMES[name],
        "day": day.isoformat(),
        "start": int(ta),
        "end": int(tb),
        "hours_wib": session_hours_wib(name, day),
        "complete": bars[-1][0] + 900 >= tb,
        "open": o, "high": h, "low": l, "close": c,
        "change": c - o,
        "change_pct": (c - o) / o * 100 if o else 0.0,
        "range": h - l,
        "range_vs_adr": (h - l) / ref_range if ref_range else 0.0,
        "label": classify(o, h, l, c, ref_range),
    }


def recent_sessions(candles: list[list[float]], now: datetime, count: int = 6) -> list[dict]:
    """Sesi terakhir (selesai atau sedang berjalan), urut lama → baru."""
    ref = adr(candles)
    out: list[dict] = []
    day = now.astimezone(UTC).date()
    for back in range(0, 10):
        d = day - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        for name in ("ny", "london", "asia"):
            s = session_stats(candles, name, d, now, ref)
            if s:
                out.append(s)
        if len(out) >= count:
            break
    out.sort(key=lambda s: s["start"])
    return out[-count:]
