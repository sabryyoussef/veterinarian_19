#!/usr/bin/env python3
"""Deploy PetSpot El Sahel landing page to remote Odoo (petspot.odoo.com)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from deploy import main  # noqa: E402

if __name__ == "__main__":
    if "--target" not in sys.argv:
        sys.argv.extend(["--target", "remote"])
    raise SystemExit(main())
