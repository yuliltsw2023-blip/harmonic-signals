"""Konfigurasi eksekutor — semua dari env / .env.executor (di root repo).
Login MT5 diisi user sendiri di file itu; tidak pernah di-commit."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _load_env() -> None:
    try:
        from dotenv import dotenv_values, load_dotenv
    except ImportError:
        return
    load_dotenv(os.path.join(ROOT, ".env"))            # Upstash / Telegram (kalau ada)
    # .env.executor menang, tapi baris yang dibiarkan kosong tidak menimpa nilai dari .env
    for k, v in dotenv_values(os.path.join(ROOT, ".env.executor")).items():
        if v is not None and v.strip():
            os.environ[k] = v.strip()


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, "").strip() or default)


def _i(name: str, default: int) -> int:
    return int(os.environ.get(name, "").strip() or default)


@dataclass
class ExecutorConfig:
    login: str = ""
    password: str = ""
    server: str = ""
    path: str = ""                       # path terminal64.exe (opsional)
    risk_pct: float = 1.0                # Grade A: % ekuitas per trade
    risk_pct_b_factor: float = 0.5       # Grade B = risk_pct × faktor (skill: size lebih kecil)
    max_open: int = 3                    # maksimal setup aktif (pending + posisi) bersamaan
    daily_loss_pct: float = 3.0          # rugi harian ≥ ini → stop pasang order sampai besok
    poll_sec: int = 20
    split_tp: bool = True                # 50% lot TP1, 50% lot TP2 (kalau lot cukup)
    symbol_suffix: str = ""              # mis. ".z" kalau broker pakai suffix
    symbol_map: dict = field(default_factory=dict)   # {"XAU/USD": "GOLD"}
    magic: int = 260917
    deviation_points: int = 20
    telegram: bool = True
    state_file: str = os.path.join(ROOT, "executor", "state.json")
    stop_file: str = os.path.join(ROOT, "executor", "STOP")

    @classmethod
    def from_env(cls) -> "ExecutorConfig":
        _load_env()
        raw_map = os.environ.get("MT5_SYMBOL_MAP", "").strip()
        return cls(
            login=os.environ.get("MT5_LOGIN", "").strip(),
            password=os.environ.get("MT5_PASSWORD", "").strip(),
            server=os.environ.get("MT5_SERVER", "").strip(),
            path=os.environ.get("MT5_PATH", "").strip(),
            risk_pct=_f("RISK_PCT", 1.0),
            risk_pct_b_factor=_f("RISK_PCT_B_FACTOR", 0.5),
            max_open=_i("MAX_OPEN_SETUPS", 3),
            daily_loss_pct=_f("DAILY_LOSS_PCT", 3.0),
            poll_sec=_i("POLL_SEC", 20),
            split_tp=os.environ.get("SPLIT_TP", "true").strip().lower() == "true",
            symbol_suffix=os.environ.get("MT5_SYMBOL_SUFFIX", "").strip(),
            symbol_map=json.loads(raw_map) if raw_map else {},
            telegram=os.environ.get("EXECUTOR_TELEGRAM", "true").strip().lower() == "true",
        )

    def risk_for_grade(self, grade: str) -> float:
        return self.risk_pct if grade == "A" else self.risk_pct * self.risk_pct_b_factor
