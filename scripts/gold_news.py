"""Entry point briefing emas: python scripts/gold_news.py (lihat goldnews/run.py)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from goldnews.run import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
