#!/usr/bin/env python
"""便捷入口：python run.py [--title 片名] [--force]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from moviestory.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
