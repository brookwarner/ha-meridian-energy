"""Shared test fixtures."""
import sys
from pathlib import Path

# Make the custom_components package importable as a top-level module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components"))
