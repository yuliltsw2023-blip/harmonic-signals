"""Pengumpul data: berita RSS, kalender ForexFactory, candle XAU, makro Yahoo.

Semua sumber gratis & tanpa login. Tiap sumber boleh gagal sendiri-sendiri —
run tetap jalan dengan sumber yang tersisa (dicatat di report["source_errors"]).
"""

from __future__ import annotations

import hashlib
import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

UTC = timezone.utc
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/140 Safari/537.36"}

GNEWS_QUERIES = (
    "gold price",
    "XAUUSD OR \"spot gold\" OR bullion",
    "Federal Reserve rate Powell",
    "Treasury yields dollar index",
    "central bank gold buying OR gold ETF",
    "geopolitical tensions safe haven",
    "US inflation CPI OR PCE OR payrolls",
)
FEEDS = {
    "investingLive": "https://investinglive.com/feed/",
    "FXStreet": "https://www.fxstreet.com/rss/news",
    "CNBC Markets": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
    "World Gold Council": "https://www.gold.org/rss.xml",
}
# Feed umum disaring kata kunci; Google News (sudah berupa query) tidak.
KEYWORDS = re.compile(
    r"\b(gold|xau|bullion|precious|silver|fed|fomc|powell|treasur|yield|dollar|dxy|"
    r"inflation|cpi|pce|ppi|payroll|nfp|jobless|jobs|unemployment|rate cut|rate hike|"
    r"central bank|pboc|ecb|boj|boe|tariff|sanction|war|missile|iran|israel|russia|"
    r"ukraine|china|geopolit|safe.haven|recession|gdp|pmi|etf|spdr|risk.off|"
    r"treasury|debt ceiling|shutdown|crude|oil)\b", re.I)


def _clean(text: str | None, limit: int = 280) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", html.unescape(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _norm_title(title: str) -> str:
    title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title)  # buang " - Reuters" Google News
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def news_id(title: str) -> str:
    return hashlib.sha1(_norm_title(title).encode()).hexdigest()[:12]


def _parse_rss(xml_bytes: bytes, source: str) -> list[dict]:
    items = []
    root = ET.fromstring(xml_bytes)
    for it in root.iter("item"):
        title = _clean(it.findtext("title"), 300)
        if not title:
            continue
        pub = it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")
        try:
            dt = parsedate_to_datetime(pub) if pub and "," in pub else datetime.fromisoformat(pub.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
        except Exception:
            continue
        src = it.findtext("source") or source
        items.append({
            "id": news_id(title),
            "title": re.sub(r"\s+-\s+[^-]{2,40}$", "", title) if source == "Google News" else title,
            "source": _clean(src, 60),
            "via": source,
            "url": (it.findtext("link") or "").strip(),
            "t": int(dt.astimezone(UTC).timestamp()),
            "summary": _clean(it.findtext("description")),
        })
    return items


def fetch_news(since: datetime, errors: list[str]) -> list[dict]:
    """Berita sejak `since`, dedup per judul, urut terbaru dulu."""
    since_ts = since.timestamp()
    raw: list[dict] = []
    for q in GNEWS_QUERIES:
        hours = max(1, int((time.time() - since_ts) / 3600) + 1)
        window = f"when:{min(hours, 72)}h" if hours <= 72 else "when:7d"
        url = (f"https://news.google.com/rss/search?q={quote_plus(q + ' ' + window)}"
               "&hl=en-US&gl=US&ceid=US:en")
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            raw += _parse_rss(r.content, "Google News")
        except Exception as e:  # noqa: BLE001
            errors.append(f"gnews '{q}': {e.__class__.__name__}")
    for name, url in FEEDS.items():
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            items = _parse_rss(r.content, name)
            if name not in ("Federal Reserve", "World Gold Council"):
                items = [x for x in items if KEYWORDS.search(x["title"] + " " + x["summary"])]
            raw += items
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e.__class__.__name__}")
    seen: dict[str, dict] = {}
    for x in raw:
        if x["t"] < since_ts or x["t"] > time.time() + 600:
            continue
        old = seen.get(x["id"])
        if old is None or (not old["summary"] and x["summary"]):
            seen[x["id"]] = x
    return sorted(seen.values(), key=lambda x: x["t"], reverse=True)


# ---------------------------------------------------------------- kalender

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
GOLD_COUNTRIES_HIGH = {"USD", "CNY", "EUR", "GBP", "JPY", "CHF", "ALL"}


def event_id(ev: dict) -> str:
    return hashlib.sha1(f"{ev['country']}|{ev['title']}|{ev['date']}".encode()).hexdigest()[:12]


def gold_relevance(ev: dict) -> str:
    """tinggi / sedang / rendah — seberapa besar event biasanya menggerakkan emas."""
    title, country, impact = ev["title"].lower(), ev["country"], ev["impact"]
    big = re.search(r"cpi|pce|non-farm|nfp|employment change|unemployment|fomc|federal funds|"
                    r"powell|fed chair|gdp|ppi|retail sales|ism|jobless|jolts|core", title)
    if country == "USD":
        if impact == "High" or big:
            return "tinggi"
        if impact == "Medium":
            return "sedang"
        return "rendah"
    if country in GOLD_COUNTRIES_HIGH and impact == "High":
        return "sedang"
    return "rendah"


def fetch_calendar(errors: list[str]) -> list[dict]:
    try:
        r = requests.get(FF_URL, headers=UA, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        errors.append(f"calendar: {e.__class__.__name__}")
        return []
    out = []
    for ev in data:
        if ev.get("impact") in ("Holiday", "Non-Economic"):
            continue
        try:
            dt = datetime.fromisoformat(ev["date"])
        except Exception:
            continue
        item = {
            "id": event_id(ev),
            "title": ev["title"],
            "country": ev["country"],
            "impact": ev["impact"],
            "forecast": ev.get("forecast") or "",
            "previous": ev.get("previous") or "",
            "t": int(dt.astimezone(UTC).timestamp()),
        }
        item["gold"] = gold_relevance(item)
        out.append(item)
    return out


# ---------------------------------------------------------------- harga

def fetch_xau_15m(api_key: str, errors: list[str], outputsize: int = 5000) -> list[list[float]]:
    """Candle XAU/USD 15 menit dari Twelve Data → [[epoch, o, h, l, c], ...] lama→baru."""
    return fetch_xau(api_key, errors, "15min", outputsize)


def fetch_xau(api_key: str, errors: list[str], interval: str, outputsize: int) -> list[list[float]]:
    """Candle XAU/USD (interval Twelve Data: 5min/15min/1h/4h) → [[epoch,o,h,l,c], ...]."""
    try:
        r = requests.get("https://api.twelvedata.com/time_series", params={
            "symbol": "XAU/USD", "interval": interval, "outputsize": outputsize,
            "timezone": "UTC", "apikey": api_key}, timeout=40)
        js = r.json()
        if js.get("status") != "ok":
            raise RuntimeError(js.get("message", "status not ok"))
    except Exception as e:  # noqa: BLE001
        errors.append(f"twelvedata {interval}: {e}")
        return []
    out = []
    for v in js["values"]:
        t = datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        out.append([int(t.timestamp()), round(float(v["open"]), 2), round(float(v["high"]), 2),
                    round(float(v["low"]), 2), round(float(v["close"]), 2)])
    out.sort(key=lambda x: x[0])
    return out


def merge_candles(old: list[list[float]], new: list[list[float]], cap: int = 14000) -> list[list[float]]:
    by_t = {int(x[0]): x for x in old}
    for x in new:
        by_t[int(x[0])] = x
    return [by_t[k] for k in sorted(by_t)][-cap:]


MACRO_SYMBOLS = {
    "DXY": "DX-Y.NYB",
    "US10Y": "^TNX",
    "Minyak WTI": "CL=F",
    "S&P 500": "^GSPC",
    "Perak": "SI=F",
    "VIX": "^VIX",
}


def fetch_macro(errors: list[str]) -> dict:
    """Nilai terakhir + perubahan 1 hari & 5 hari dari Yahoo (endpoint chart v8)."""
    out = {}
    for name, sym in MACRO_SYMBOLS.items():
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote_plus(sym)}",
                             params={"interval": "1d", "range": "1mo"}, headers=UA, timeout=20)
            res = r.json()["chart"]["result"][0]
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
            last = res["meta"].get("regularMarketPrice") or closes[-1]
            prev = closes[-2] if len(closes) >= 2 else last
            wk = closes[-6] if len(closes) >= 6 else closes[0]
            out[name] = {"last": round(last, 3), "chg_1d": round(last - prev, 3),
                         "chg_1d_pct": round((last - prev) / prev * 100, 2) if prev else 0,
                         "chg_5d_pct": round((last - wk) / wk * 100, 2) if wk else 0}
        except Exception as e:  # noqa: BLE001
            errors.append(f"yahoo {name}: {e.__class__.__name__}")
    return out


def since_default(now: datetime, hours: int) -> datetime:
    return now - timedelta(hours=hours)
