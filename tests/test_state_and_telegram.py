import os

from lib import state
from lib.scanner import analyze_candles, is_forex_closed
from lib.telegram import format_signal
from tests.fixtures import synthetic_bat
from datetime import datetime, timezone


def test_memory_state_roundtrip(monkeypatch):
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    state._redis = None
    state._memory.clear()
    c = analyze_candles("EUR/USD", "H4", synthetic_bat())[0]
    assert state.backend_name() == "memory"
    assert not state.is_already_signaled(c)
    state.mark_signaled(c)
    assert state.is_already_signaled(c)
    assert state.signal_key("EUR/USD", "H4", "Deep Crab", "20260601") == "signal:EUR_USD:H4:DeepCrab:20260601:in_prz"


def test_format_signal_contains_levels():
    c = analyze_candles("EUR/USD", "H4", synthetic_bat())[0]
    c["htf_alignment"] = "aligned"
    grade = {"grade": "A", "reasoning": ["Bat rapi <2%", "HTF aligned"], "entry_model": "Scaled",
             "invalidation": "close < X", "warnings": ["NFP Jumat"], "source": "claude"}
    msg = format_signal(c, grade)
    assert "EUR/USD" in msg and "Bat BULL" in msg and "LONG" in msg
    assert "TP1" in msg and "SL" in msg and "Grade: <b>A</b>" in msg
    assert "NFP" in msg
    assert "Analisis edukatif" in msg


def test_forex_closed_schedule():
    assert is_forex_closed(datetime(2026, 9, 12, 10, tzinfo=timezone.utc))      # Sabtu
    assert is_forex_closed(datetime(2026, 9, 13, 10, tzinfo=timezone.utc))      # Minggu pagi
    assert not is_forex_closed(datetime(2026, 9, 13, 23, tzinfo=timezone.utc))  # Minggu 23 UTC
    assert is_forex_closed(datetime(2026, 9, 11, 23, tzinfo=timezone.utc))      # Jumat 23 UTC
    assert not is_forex_closed(datetime(2026, 9, 9, 12, tzinfo=timezone.utc))   # Rabu


def test_chart_renders_png_and_caption_short():
    from lib.chart import render_signal_chart
    from lib.telegram import format_caption
    c = analyze_candles("EUR/USD", "H4", synthetic_bat())[0]
    c["htf_alignment"] = "aligned"
    grade = {"grade": "A", "entry_model": "Scaled", "reasoning": [], "source": "claude"}
    png = render_signal_chart(c, synthetic_bat(), grade)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 20_000
    assert len(format_caption(c, grade)) < 1024


def test_send_signal_sends_photo_then_text(monkeypatch):
    from lib import telegram
    calls = []
    monkeypatch.setattr(telegram, "send_photo", lambda png, cap: calls.append(("photo", len(png))))
    monkeypatch.setattr(telegram, "send_message", lambda text: calls.append(("text", len(text))))
    c = analyze_candles("EUR/USD", "H4", synthetic_bat())[0]
    grade = {"grade": "B", "entry_model": "Conservative", "reasoning": ["x"], "source": "rule"}
    monkeypatch.delenv("SIGNAL_VERBOSE", raising=False)
    telegram.send_signal(c, grade, synthetic_bat())
    assert [k for k, _ in calls] == ["photo"]          # ringkas: satu pesan (foto + caption)
    # tanpa candles → teks ringkas saja
    calls.clear()
    telegram.send_signal(c, grade)
    assert [k for k, _ in calls] == ["text"]
    # verbose → foto + teks panjang
    calls.clear()
    monkeypatch.setenv("SIGNAL_VERBOSE", "true")
    telegram.send_signal(c, grade, synthetic_bat())
    assert [k for k, _ in calls] == ["photo", "text"]


def test_chart_img_request_shape_and_fallback(monkeypatch):
    from lib import chart_img, telegram
    c = analyze_candles("EUR/USD", "H4", synthetic_bat())[0]
    grade = {"grade": "A", "entry_model": "Scaled", "reasoning": [], "source": "rule"}
    body = chart_img.build_request(c, grade)
    assert body["symbol"] == "OANDA:EURUSD" and body["interval"] == "4h"
    names = [d["name"] for d in body["drawings"]]
    assert names.count("Trend Line") == 4 and "Rectangle" in names and names.count("Horizontal Line") == 5
    assert all(d["input"].get("startDatetime", "Z").endswith("Z") for d in body["drawings"] if d["name"] == "Trend Line")

    # key ada tapi API error → fallback matplotlib, sinyal tetap terkirim
    monkeypatch.setenv("CHART_IMG_API_KEY", "dummy")
    class R:
        status_code = 500; text = "boom"; headers = {"content-type": "text/plain"}; content = b""
    monkeypatch.setattr(chart_img.requests, "post", lambda *a, **k: R())
    calls = []
    monkeypatch.setattr(telegram, "send_photo", lambda png, cap: calls.append(("photo", png[:4])))
    monkeypatch.setattr(telegram, "send_message", lambda text: calls.append(("text", None)))
    telegram.send_signal(c, grade, synthetic_bat())
    assert calls[0][0] == "photo" and calls[0][1] == b"\x89PNG" and c["chart_source"] == "matplotlib"

    # key ada dan API sukses → pakai chart-img
    class OK:
        status_code = 200; headers = {"content-type": "image/png"}; content = b"\x89PNGfake"; text = ""
    monkeypatch.setattr(chart_img.requests, "post", lambda *a, **k: OK())
    calls.clear()
    telegram.send_signal(c, grade, synthetic_bat())
    assert calls[0] == ("photo", b"\x89PNG") and c["chart_source"].startswith("chart-img")


def test_layout_chart_preferred_when_layout_id_set(monkeypatch):
    from lib import chart_img, telegram
    c = analyze_candles("GBP/USD", "H4", synthetic_bat())[0]
    grade = {"grade": "A", "entry_model": "Scaled", "reasoning": [], "source": "rule"}
    monkeypatch.setenv("CHART_IMG_API_KEY", "dummy")
    monkeypatch.setenv("CHART_IMG_LAYOUT_ID", "abc123")
    seen = []
    class OK:
        status_code = 200; headers = {"content-type": "image/png"}; content = b"\x89PNGlayout"; text = ""
    def fake_post(url, json=None, headers=None, timeout=None):
        seen.append((url, json)); return OK()
    monkeypatch.setattr(chart_img.requests, "post", fake_post)
    calls = []
    monkeypatch.setattr(telegram, "send_photo", lambda png, cap: calls.append(cap))
    monkeypatch.setattr(telegram, "send_message", lambda text: None)
    telegram.send_signal(c, grade, synthetic_bat())
    assert seen[0][0].endswith("/layout-chart/abc123")
    assert seen[0][1]["symbol"] == "OANDA:GBPUSD" and seen[0][1]["interval"] == "4h"
    assert c["chart_source"].startswith("TradingView layout") and "PRZ:" in calls[0]


def test_compact_formats_have_only_key_levels():
    from lib.telegram import format_compact
    c = analyze_candles("EUR/USD", "H4", synthetic_bat())[0]
    grade = {"grade": "A", "entry_model": "Scaled", "reasoning": ["panjang"], "source": "claude"}
    msg = format_compact(c, grade)
    assert msg.count("\n") <= 7 and len(msg) < 1024
    for key in ("PRZ:", "SL:", "TP1:", "TP2:", "LONG", "Grade"):
        assert key in msg
    assert "TP3" not in msg and "Ratios" not in msg and "Reasoning" not in msg
