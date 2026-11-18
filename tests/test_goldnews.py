from datetime import date, datetime, timezone

from goldnews.sessions import classify, due_slots, session_window, slot_id
from goldnews.telegram import format_briefing

UTC = timezone.utc


def keys(now):
    return [s.key for s, _ in due_slots(now)]


def test_slots_winter():
    # 18 Nov 2026 (Rabu) — London & NY sudah musim dingin
    assert keys(datetime(2026, 11, 17, 23, 30, tzinfo=UTC)) == ["pre_asia"]      # 06:30 WIB
    assert keys(datetime(2026, 11, 18, 7, 25, tzinfo=UTC)) == ["pre_london"]     # 14:25 WIB
    assert keys(datetime(2026, 11, 18, 12, 20, tzinfo=UTC)) == ["pre_ny"]        # 19:20 WIB
    assert keys(datetime(2026, 11, 18, 14, 0, tzinfo=UTC))[0] == "post_us"       # 21:00 WIB
    assert keys(datetime(2026, 11, 18, 3, 0, tzinfo=UTC)) == []


def test_slots_summer_shift_one_hour():
    # Juli: London BST, NY EDT → slot 1 jam lebih awal dalam WIB
    assert keys(datetime(2026, 7, 15, 6, 30, tzinfo=UTC)) == ["pre_london"]      # 13:30 WIB
    assert keys(datetime(2026, 7, 15, 11, 30, tzinfo=UTC)) == ["pre_ny"]         # 18:30 WIB


def test_weekend():
    assert keys(datetime(2026, 11, 20, 23, 30, tzinfo=UTC)) == ["weekly"]        # Sabtu 06:30 WIB
    assert keys(datetime(2026, 11, 21, 23, 30, tzinfo=UTC)) == []                # Minggu
    assert keys(datetime(2026, 11, 22, 23, 30, tzinfo=UTC)) == ["pre_asia"]      # Senin 06:30 WIB


def test_slot_id_uses_wib_date():
    s, t = due_slots(datetime(2026, 11, 17, 23, 30, tzinfo=UTC))[0]
    assert slot_id(s, t) == "2026-11-18_pre_asia"


def test_session_windows_winter():
    a, b = session_window("london", date(2026, 11, 18))
    assert (a.hour, b.hour) == (8, 13)
    a, b = session_window("ny", date(2026, 11, 18))
    assert (a.hour, b.hour) == (13, 22)


def test_classify():
    assert classify(100, 112, 99, 111, 20) == "bullish"
    assert classify(100, 101, 88, 89, 20) == "bearish"
    assert classify(100, 103, 97, 101, 20) == "sideways"           # gerak kecil
    assert classify(100, 120, 85, 105, 20) == "sideways"           # naik tapi close tengah


def test_format_briefing_short():
    rep = {
        "slot_label": "Pra-London", "t": 1795000000, "target_label": "Sesi London",
        "price": {"last": 3766.8},
        "sessions": [{"name": "Asia", "complete": True, "label": "bullish", "change": 12.3,
                      "range": 20.0, "range_vs_adr": 0.4}],
        "prev_eval": None,
        "key_news": [{"t": 1795000000, "title": "Gold <rises>", "effect": "bullish", "why": "dolar melemah"}],
        "analysis": {"headline": "Emas menguat", "bias": {"direction": "bearish", "confidence": "sedang",
                                                           "reason": "x"},
                     "event_risks": [], "levels": {"support": [3750.0], "resistance": [3780.0]},
                     "scenarios": [{"if_": "a", "then": "b"}]},
    }
    txt = format_briefing(rep, "https://x/#r=1")
    assert "&lt;rises&gt;" in txt and "BEARISH" in txt and len(txt) < 4000
