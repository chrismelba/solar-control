"""
Shared pytest configuration and fixtures for the solar-control test suite.

Sets up the Python path so that source modules can be imported, and provides
common fixtures used across multiple test modules.
"""

import sys
import os
import tempfile
import shutil

import pytest

# Set environment variables before any source module is imported, since
# several modules call setup_logging() at module level which reads DATA_DIR.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="solar_control_test_")
os.environ.setdefault("DATA_DIR", _TEST_DATA_DIR)
os.environ.setdefault("SUPERVISOR_TOKEN", "test-token")
os.environ.setdefault("HASS_URL", "http://test-hass")

# Make source files importable
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "rootfs", "usr", "bin"),
)


@pytest.fixture()
def tmp_data_dir(tmp_path):
    """Return a temporary directory that acts as DATA_DIR for a single test."""
    old = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(tmp_path)
    yield tmp_path
    if old is None:
        del os.environ["DATA_DIR"]
    else:
        os.environ["DATA_DIR"] = old
