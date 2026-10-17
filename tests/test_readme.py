"""README.md cites only numbers from claims.json and tables generated from the code."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_is_in_sync_with_claims_and_code():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "readme_sync.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
