import pytest
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

@pytest.fixture(autouse=True)
def _mtf_filter_off(monkeypatch):
    """Default produksi MTF_CONFLICT_FILTER=true; test lama memakai fixture tanpa data LTF
    yang konsisten → matikan kecuali test yang menyalakannya sendiri (tests/test_mtf.py)."""
    from config import settings
    monkeypatch.setattr(settings, "MTF_CONFLICT_FILTER", False)
    monkeypatch.setattr(settings, "MTF_OWN_TREND", False)
