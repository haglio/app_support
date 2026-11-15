from __future__ import annotations

import sys

from app_support.conflict_markers import refuse_a_staged_leftover
from app_support.sanitize.guard import main

raise SystemExit(refuse_a_staged_leftover(sys.argv[1:]) or main())
