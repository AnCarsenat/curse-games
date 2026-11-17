"""Entry point: `python3 -m artillery` (from games/) or `python3 games/artillery`."""
import os
import sys

if __package__ in (None, ""):    # run as a directory: make the package importable
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artillery.main import run  # noqa: E402

run()
