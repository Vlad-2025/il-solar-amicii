import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# One throwaway SQLite database for the whole test run, set before any db module is used.
_TMP = tempfile.mkdtemp(prefix="prosumer-tests-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP}/test.db")
os.environ.setdefault("NTFY_BASE_URL", "http://127.0.0.1:9")   # never reach a real ntfy server

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def demo_data():
    from datetime import date

    from ingest.demo import generate
    return generate(date(2026, 10, 23))


@pytest.fixture(scope="session")
def db():
    from db.client import init_db
    init_db()
    return True
