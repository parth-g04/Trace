"""
Pytest configuration for TRACE backend test suite.
Ensures repository root is in sys.path so 'backend.app' imports resolve cleanly.
"""
import sys
from pathlib import Path

# Add repository root (Trace/) to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
