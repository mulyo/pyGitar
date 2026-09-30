import os
import sys
from pathlib import Path

# Pastikan package root ada di sys.path (untuk `python -m pytest` tanpa install).
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Non-aktifkan Qt platform plugin agar tes unit berjalan tanpa display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
