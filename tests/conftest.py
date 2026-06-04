"""Make the package importable when running pytest from the project root."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_configure(config):
    """Register custom markers (no pytest.ini/pyproject in this repo)."""
    config.addinivalue_line(
        "markers",
        "integration: tests that boot the real app or touch external resources",
    )
