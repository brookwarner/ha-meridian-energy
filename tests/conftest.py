"""Shared test fixtures."""
import importlib.abc
import importlib.machinery
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


# Make the custom_components package importable as a top-level module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components"))


# --- Robust homeassistant auto-mock using MetaPathFinder ---
# Intercept any import of `homeassistant` or `homeassistant.*` and synthesize
# mock modules on-demand. This avoids fragility from hand-enumerating specific
# homeassistant symbols: any missing attribute is fabricated as a MagicMock.
#
# Rationale: The pure modules under test (statistics, auth, api) never call
# real Home Assistant code, so a mock homeassistant namespace is sufficient
# and future-proof. HA-coupled modules (__init__, coordinator, sensor,
# config_flow) are validated on a real Home Assistant instance, not in this
# unit suite.

class _MockModule(types.ModuleType):
    """A module that fabricates missing attributes as MagicMock() on-demand."""

    def __getattr__(self, name):
        # Fabricate and cache the attribute so repeated access returns the same mock.
        mock = MagicMock()
        setattr(self, name, mock)
        return mock


class _HomeAssistantMetaPathFinder(importlib.abc.MetaPathFinder):
    """Find and load homeassistant.* imports by synthesizing mock modules."""

    def find_spec(self, fullname, path, target=None):
        # Only intercept homeassistant and homeassistant.* imports.
        if fullname == "homeassistant" or fullname.startswith("homeassistant."):
            # Synthesize a loader that will create a _MockModule.
            return importlib.machinery.ModuleSpec(
                fullname,
                _HomeAssistantLoader(),
            )
        return None


class _HomeAssistantLoader(importlib.abc.Loader):
    """Loader that creates _MockModule instances for homeassistant.* imports."""

    def create_module(self, spec):
        # Return a new _MockModule with __path__ = [] so submodule imports
        # keep resolving through this finder.
        mod = _MockModule(spec.name)
        mod.__path__ = []  # Allows further submodule imports to resolve via finder
        return mod

    def exec_module(self, module):
        # No additional setup needed; __getattr__ handles everything.
        pass


# Install the finder before any meridian_energy imports.
if not any(isinstance(finder, _HomeAssistantMetaPathFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _HomeAssistantMetaPathFinder())
