"""The Monday, Wednesday and Friday panels shown by ``panels_page``.

The detailed Monday and Friday reports (``?classic=1``) import nothing here.
"""
from pathlib import Path
import sys

# The Friday package lives under sources/friday (app.py adds the same path).
_FRIDAY = Path(__file__).resolve().parents[1] / "sources" / "friday"
if str(_FRIDAY) not in sys.path:
    sys.path.insert(0, str(_FRIDAY))
