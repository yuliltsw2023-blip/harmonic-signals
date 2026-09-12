#!/usr/bin/env python3
"""H1 harmonic pattern scanner (universe terbatas, lihat config.pairs.H1_SYMBOLS).
GitHub Actions cron tiap jam."""

import sys

import _bootstrap  # noqa: F401
from lib.scanner import run_scan

if __name__ == "__main__":
    sys.exit(run_scan("H1"))
