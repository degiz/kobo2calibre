#!/usr/bin/env python
"""Test runner for use with calibre-debug."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
loader = unittest.TestLoader()
suite = loader.discover(str(Path(__file__).parent))
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
