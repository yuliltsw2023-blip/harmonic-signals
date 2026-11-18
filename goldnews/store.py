"""Penyimpanan berbasis file JSON di repo (di-commit oleh GitHub Actions).

Folder data = goldnews/site/data (ikut ter-deploy ke website Vercel):
  reports/<id>.json   report lengkap per briefing (history permanen di git)
  index.json          daftar ringkas semua briefing (history + marker chart + evaluasi)
  calendar.json       event kalender ForexFactory yang pernah terlihat (± 120 hari)
  state.json          last_run (batas 'berita baru') + slot yang sudah terkirim

Candle harga TIDAK disimpan (supaya repo tidak membengkak): run mengambil ulang
dari Twelve Data, website mengambil lewat /api/candles.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parent / "site" / "data"


def _dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


class Store:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("GOLDNEWS_DATA_DIR") or DEFAULT_DIR)

    # ------------------------------------------------------------ state
    def state(self) -> dict:
        return _load(self.root / "state.json", {"last_run": 0, "sent": {}})

    def was_sent(self, rid: str) -> bool:
        return rid in self.state().get("sent", {})

    def mark_sent(self, rid: str, now: float) -> None:
        st = self.state()
        sent = {k: v for k, v in st.get("sent", {}).items() if v > now - 14 * 86400}
        sent[rid] = int(now)
        st.update(last_run=int(now), sent=sent)
        _dump(self.root / "state.json", st)

    # ------------------------------------------------------------ reports
    def all_meta(self) -> list[dict]:
        return _load(self.root / "index.json", [])

    def save_meta(self, metas: list[dict]) -> None:
        metas = sorted(metas, key=lambda m: m["t"])
        _dump(self.root / "index.json", metas)

    def save_report(self, report: dict, meta: dict) -> None:
        _dump(self.root / "reports" / f"{report['id']}.json", report)
        metas = [m for m in self.all_meta() if m["id"] != meta["id"]] + [meta]
        self.save_meta(metas)

    # ------------------------------------------------------------ kalender
    def save_calendar(self, events: list[dict]) -> None:
        path = self.root / "calendar.json"
        by_id = {e["id"]: e for e in _load(path, [])}
        for e in events:
            by_id[e["id"]] = e
        keep = time.time() - 120 * 86400
        _dump(path, sorted((e for e in by_id.values() if e["t"] >= keep), key=lambda e: e["t"]))
