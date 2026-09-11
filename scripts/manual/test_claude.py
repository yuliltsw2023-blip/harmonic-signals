#!/usr/bin/env python3
"""Grade satu setup sintetis lewat Claude, cek JSON-nya valid.

python scripts/manual/test_claude.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap_manual  # noqa: F401,E402

from lib.claude_grader import grade_setup  # noqa: E402
from lib.grading import htf_alignment, rule_grade  # noqa: E402
from lib.scanner import analyze_candles  # noqa: E402
from tests.fixtures import synthetic_bat  # noqa: E402

candles = synthetic_bat(bull=True, base=1.1000, projected=True)
cands = analyze_candles("EUR/USD", "H4", candles)
assert cands, "fixture tidak menghasilkan kandidat"
cand = cands[0]
cand["htf_timeframe"] = "1day"
cand["htf_trend"] = "up"
cand["htf_alignment"] = htf_alignment(cand, "up")
rule_grade(cand)
print("rule grade:", cand["rule_grade"])
result = grade_setup(cand)
print(json.dumps(result, indent=2, ensure_ascii=False))
