#!/usr/bin/env python3
"""D1 harmonic pattern scanner. GitHub Actions cron harian."""

import sys

import _bootstrap  # noqa: F401
from lib.scanner import run_scan

if __name__ == "__main__":
    sys.exit(run_scan("D1"))
