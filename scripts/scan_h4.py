#!/usr/bin/env python3
"""H4 harmonic pattern scanner. GitHub Actions cron tiap 4 jam."""

import sys

import _bootstrap  # noqa: F401
from lib.scanner import run_scan

if __name__ == "__main__":
    sys.exit(run_scan("H4"))
