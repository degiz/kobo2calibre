# AGENTS.md

Technical reference for AI coding agents working on kobo2calibre.

---

## Code Philosophy

Write only minimal, necessary code. Avoid over-engineering.

### Guidelines

- **Solve the immediate problem** - Don't add features, abstractions, or "improvements" beyond what's requested
- **Keep it simple** - Three similar lines of code is better than a premature abstraction
- **No speculative code** - Don't design for hypothetical future requirements
- **Trust the internals** - Only validate at system boundaries (user input, external APIs), not internal code
- **Delete unused code** - No backwards-compatibility shims or commented-out code
- **Minimal comments** - Only where logic isn't self-evident; no redundant docstrings
- **No gold-plating** - A bug fix doesn't need surrounding code cleaned up

### Project Context

This is a Kobo-Calibre highlights sync tool. Key files:
- `converter.py` - Highlight format conversion (Kobo ↔ Calibre CFI)
- `db.py` - Database operations for both systems
- `plugin.py` - Calibre GUI plugin
- `kobo2calibre.py` - CLI interface

---

## Commands

### Build
```bash
make build
```
Creates `Kobo2Calibre.zip` plugin package containing all required files.

### Run & Debug
```bash
make run      # Install plugin and launch Calibre
make debug    # Install plugin and launch Calibre in debug mode
```

### Testing
```bash
# Run all tests
make test
# Equivalent to: calibre-debug test/run_tests.py

# Run single test file
calibre-debug test/test_converter.py

# Run specific test class or method
calibre-debug -e "import sys, pathlib, unittest; sys.path.insert(0, str(pathlib.Path.cwd())); from test.test_converter import TestConverter; suite = unittest.TestLoader().loadTestsFromTestCase(TestConverter); unittest.TextTestRunner(verbosity=2).run(suite)"
```

### Linting & Formatting
```bash
make lint      # Run ruff check + mypy
make format    # Run ruff format (auto-fix)
```

---

## Python Environment

- **Target version**: Python 3.8+ (specified in pyproject.toml)
- **Project uses**: calibre_3.12 (from .python-version)
- **Type checking**: mypy with `--explicit-package-bases --namespace-packages`

---

## Code Style

### Imports

**Order**: stdlib → third-party → local modules

```python
import logging
import pathlib
from datetime import datetime
from typing import Dict, List, Optional

import bs4  # type: ignore
from bs4 import BeautifulSoup

from db import KoboTargetHighlight
```

**Calibre/PyQt imports**: Always add `# type: ignore` comment
```python
from calibre.gui2.actions import InterfaceAction  # type: ignore
from PyQt6 import QtCore, QtGui, QtWidgets
```

**Dual import pattern** (plugin vs CLI):
```python
try:
    # For calibre gui plugin
    from calibre_plugins.kobo2calibre import converter  # type: ignore
    from calibre_plugins.kobo2calibre import db  # type: ignore
except ImportError:
    # For cli
    import converter  # type: ignore
    import db  # type: ignore
```

### Type Hints

- **Required** on all function signatures
- Use `typing` module: `Optional`, `List`, `Dict`, `Tuple`
- Return types required, including `None`

```python
def process_highlights(
    book_path: pathlib.Path,
    highlights: List[db.KoboSourceHighlight],
    kepub_format: str = "new",
) -> List[db.CalibreTargetHighlight]:
```

### Formatting

- **Line length**: 88 characters (Black-compatible)
- **Tool**: Ruff (configured in pyproject.toml)
- **Ignore codes**: D100, D104, E203
- **Special case**: converter.py ignores E231 for alignment

### Naming Conventions

- **Functions/variables**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private**: `_leading_underscore`
- **Named tuples**: Use for data structures (see examples below)

```python
# Constants
BLOCK_TAGS = frozenset(("p", "ol", "ul", "table", "h1", "h2", "h3"))

# Named tuples for data
KoboSourceHighlight = namedtuple(
    "KoboSourceHighlight",
    ["start_path", "end_path", "start_offset", "end_offset", "text", "content_path", "color"],
)
```

### Error Handling

Follow the **trust the internals** principle:

- **Validate** at system boundaries: user input, external APIs, file I/O
- **Don't validate** internal function calls or data passed between modules
- Use `try/except` sparingly, only where external operations can genuinely fail

```python
# Good: Handle external operation failure
try:
    spine_index_map, fixed_path, _ = get_spine_index_map(pathlib.Path(tmpdirname))
except Exception as e:
    logger.error(f"Failed to convert highlights: {e} book: {book_path}")
    
# Bad: Don't validate internal data
# if highlights is None:  # ❌ Trust caller to provide valid data
#     raise ValueError("highlights cannot be None")
```

### Comments & Docstrings

- **Minimal**: Only where logic isn't self-evident
- **Docstrings**: Only for complex/public functions
- **No redundant docstrings**: Don't explain what's obvious from the function name

```python
# Good: Complex logic explained
def get_block_offset_from_kepubify(
    raw_html: bytes, block_num: int, sentence_num: int
) -> Optional[int]:
    """Use Calibre's kepubify to find the character offset.

    Find the character offset from the start of a block to the start of a
    specific sentence. Returns the offset, or None if the span is not found.
    """

# Good: Self-evident, no docstring needed
def get_calibre_book_id(kobo_volume: pathlib.Path, lpath: str) -> int:
```

### Logging

Use module-level logger:

```python
logger = logging.getLogger(__name__)

# Usage
logger.debug(f"Spine index map: {spine_index_map}")
logger.info(f"Processing {len(highlights)} highlights")
logger.warning(f"Kepubify not available")
logger.error(f"Failed to convert: {e}")
```

---

## Project Patterns

### Database Operations

Use **named tuples** for structured data:

```python
from collections import namedtuple

KoboSourceHighlight = namedtuple(
    "KoboSourceHighlight",
    ["start_path", "end_path", "start_offset", "end_offset", "text", "content_path", "color"],
)

CalibreTargetHighlight = namedtuple(
    "CalibreTargetHighlight",
    ["book", "format", "user_type", "user", "timestamp", "annot_id", "annot_type", "highlight", "searchable_text"],
)
```

**SQL queries**: Direct SQL with sqlite3 (data is trusted internal)

```python
con = sqlite3.connect(db_path)
cur = con.cursor()
result = cur.execute("SELECT * FROM table WHERE id = ?", (book_id,)).fetchone()
con.close()
```

### File Operations

Always use `pathlib.Path`:

```python
from pathlib import Path

# Good
epub_path = Path(args.kobo_volume) / ".kobo" / "KoboReader.sqlite"

# Bad
# epub_path = os.path.join(args.kobo_volume, ".kobo", "KoboReader.sqlite")  # ❌
```

**Temporary files**: Use context managers

```python
import tempfile

with tempfile.TemporaryDirectory() as tmpdirname:
    with zipfile.ZipFile(epub_path, "r") as zip_ref:
        zip_ref.extractall(tmpdirname)
        # Process files
```

### Calibre Integration

Two entry points share core logic:

```
plugin.py (GUI)  ─┐
                  ├─→ converter.py, db.py (shared logic)
kobo2calibre.py  ─┘   (CLI)
```

Both use the dual import pattern to support running as:
- Calibre plugin (imports from `calibre_plugins.kobo2calibre`)
- Standalone CLI (imports modules directly)

---

## Testing

### Framework & Structure

- **Framework**: unittest (Calibre-compatible)
- **Runner**: calibre-debug (required for Calibre API access)
- **Test files**: `test/*.py`
- **Test data**: `test/*.json`, `test/*.epub`

### Path Setup Pattern

Tests must add parent directory to path:

```python
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
# Now can import project modules
import converter
import db
```

### Parameterized Tests

Use `subTest` for multiple test cases:

```python
TEST_CONFIGS = [
    {"name": "old_kte", "highlights_file": "highlights_old_kte.json"},
    {"name": "new_native", "highlights_file": "highlights_new_native.json"},
]

def test_conversion(self):
    for config in self.TEST_CONFIGS:
        with self.subTest(format=config["name"]):
            # Test logic here
```

### Test Data Location

- Highlight JSON: `test/highlights_*.json`
- EPUB files: `test/*.epub`
- Load relative to test file: `pathlib.Path(__file__).parent / "file.json"`
