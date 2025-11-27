#!/usr/bin/env python3
"""
Entry point for memaflowmon application
"""

import sys
from pathlib import Path
import importlib.util

# Add the src directory to Python path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

# Import and run the main application


# Load the memaflowmon module from src directory
spec = importlib.util.spec_from_file_location(
    "memaflowmon", src_path / "memaflowmon.py"
)
if spec is None or spec.loader is None:
    raise ImportError("Could not load memaflowmon module")

memaflowmon_module = importlib.util.module_from_spec(spec)
sys.modules["memaflowmon"] = memaflowmon_module
spec.loader.exec_module(memaflowmon_module)

if __name__ == "__main__":
    memaflowmon_module.main()
