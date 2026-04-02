from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "ops" / "openclaw" / "engine.py"
SPEC = spec_from_file_location("openclaw_engine_impl", MODULE_PATH)

if SPEC is None or SPEC.loader is None:
    raise ImportError(f"Canonical engine module could not be loaded: {MODULE_PATH}")

MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

EXPORTED_NAMES = [name for name in dir(MODULE) if not name.startswith("_")]

for name in EXPORTED_NAMES:
    globals()[name] = getattr(MODULE, name)

__all__ = EXPORTED_NAMES
