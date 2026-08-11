import sys
from pathlib import Path

# Make the "src" package importable as `src.app` / `src.storage` regardless
# of where pytest is invoked from.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
