"""Preview editions of the Monday, Wednesday and Friday panels.

Nothing here is imported by the live Monday/Friday tabs. The preview tabs
render only when the app is opened with ``?preview=1``.
"""
from pathlib import Path
import sys

# The Friday package lives under sources/friday (app.py adds the same path).
_FRIDAY = Path(__file__).resolve().parents[1] / "sources" / "friday"
if str(_FRIDAY) not in sys.path:
    sys.path.insert(0, str(_FRIDAY))
