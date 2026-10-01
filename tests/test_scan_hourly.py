"""Penjadwal stateful scripts/scan_hourly.py: H4/D1 mengejar scan yang terlewat."""

import importlib.util
import os
import pathlib
import sys
from datetime import datetime, timezone

from lib import state


def _load():
    scripts = pathlib.Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts))
    env_before = dict(os.environ)      # _bootstrap memuat .env asli → jangan bocor ke test lain
    try:
        spec = importlib.util.spec_from_file_location("scan_hourly_mod", scripts / "scan_hourly.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.environ.clear()
        os.environ.update(env_before)
    return mod


def test_bucket_follows_candle_close():
    m = _load()
    t = lambda h, mi=0: datetime(2026, 10, 1, h, mi, tzinfo=timezone.utc)
    # candle 4h tutup jam 01/05/09…: 01:55 dan 04:39 masih bucket yang sama, 05:00 bucket baru
    assert m.tf_bucket("H4", t(1, 55)) == m.tf_bucket("H4", t(4, 39))
    assert m.tf_bucket("H4", t(5, 0)) != m.tf_bucket("H4", t(4, 39))
    assert m.tf_bucket("H4", t(0, 30)) != m.tf_bucket("H4", t(1, 0))
    assert m.tf_bucket("D1", t(1, 55)) == "2026-10-01"


def test_due_stateful_catches_up_and_dedups(monkeypatch):
    m = _load()
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    state._redis = None
    state._memory.clear()
    now = datetime(2026, 10, 1, 9, 44, tzinfo=timezone.utc)     # jam "acak" ala GitHub
    assert m.due_stateful(now) == ["H1", "H4", "D1"]            # belum pernah di-scan → kejar dua-duanya
    state.set_value("scan:last:H4", m.tf_bucket("H4", now))
    state.set_value("scan:last:D1", m.tf_bucket("D1", now))
    assert m.due_stateful(now) == ["H1"]
    later = datetime(2026, 10, 1, 14, 33, tzinfo=timezone.utc)  # candle H4 baru sudah close (13:00)
    assert m.due_stateful(later) == ["H1", "H4"]
    tomorrow = datetime(2026, 10, 2, 4, 39, tzinfo=timezone.utc)
    assert m.due_stateful(tomorrow) == ["H1", "H4", "D1"]


def test_main_marks_only_real_runs(monkeypatch):
    m = _load()
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    monkeypatch.delenv("SCAN_FORCE", raising=False)
    state._redis = None
    state._memory.clear()
    ran = []
    monkeypatch.setattr(m, "run_scan", lambda tf: ran.append(tf) or 0)
    monkeypatch.setenv("DRY_RUN", "true")
    assert m.main() == 0 and ran == ["H1", "H4", "D1"]
    assert state.get_value("scan:last:H4") is None              # dry run tidak menandai
    ran.clear()
    monkeypatch.setenv("DRY_RUN", "false")
    assert m.main() == 0 and ran == ["H1", "H4", "D1"]
    assert state.get_value("scan:last:H4") and state.get_value("scan:last:D1")
    ran.clear()
    assert m.main() == 0 and ran == ["H1"]                      # run berikutnya di candle yang sama
