import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def root() -> Path:
    return ROOT


@pytest.fixture
def fix() -> Path:
    return FIX
