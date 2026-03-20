# AGENTS.md

Technical reference for AI coding agents working on kobo2calibre.

---

## Code Philosophy

Write minimal, necessary code. Solve the immediate problem, keep it simple, no speculative features or abstractions. Only validate at system boundaries (user input, external APIs, file I/O), not internal code. Minimal comments, delete unused code, no gold-plating.

**Key files**: `converter.py` (Kobo↔Calibre CFI conversion), `db.py` (database ops), `plugin.py` (GUI), `kobo2calibre.py` (CLI)

---

## Commands

```bash
make build     # Create Kobo2Calibre.zip plugin package
make run       # Install plugin and launch Calibre
make debug     # Install plugin and launch Calibre in debug mode
make test      # Run all tests (calibre-debug test/run_tests.py)
make lint      # Run ruff check + mypy
make format    # Run ruff format (auto-fix)
make dedup     # Remove duplicate highlights and tombstones from Calibre DB

# Run single test file
calibre-debug test/test_converter.py

# Run specific test class
calibre-debug -e "import sys, pathlib, unittest; sys.path.insert(0, str(pathlib.Path.cwd())); from test.test_converter import TestConverter; suite = unittest.TestLoader().loadTestsFromTestCase(TestConverter); unittest.TextTestRunner(verbosity=2).run(suite)"
```

**Python**: 3.8+ target, calibre_3.12 runtime, mypy with `--explicit-package-bases --namespace-packages`

---

## Code Style

**Dual import pattern** (plugin vs CLI):
```python
try:
    from calibre_plugins.kobo2calibre import converter  # type: ignore
except ImportError:
    import converter  # type: ignore
```

---

## Project Patterns

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

**Framework**: unittest with calibre-debug runner

**Path setup**: Tests must add parent directory to path:
```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
```

**Parameterized tests**: Use `subTest` for multiple test cases

---

## Troubleshooting

### Debugging Highlight Conversions

**Problem**: Kobo highlights regularly transfer to Calibre with incorrect CFI positions, causing highlights to appear in wrong locations or with wrong text.

**Solution**: Use the `debug-highlights` skill for systematic diagnosis.

The skill provides an interactive 6-phase workflow that:
- Identifies the problematic book and highlights
- Runs conversion with full diagnostic logging
- Compares expected vs actual results in both databases
- Maps issues to specific code locations in `converter.py`
- Provides fix recommendations and testing guidance

**Load the skill**:
```bash
skill({ name: "debug-highlights" })
```

See `.agents/skills/debug-highlights/SKILL.md` for detailed workflow documentation, database schemas, root cause classifications, and prevention best practices.

### Clearing Highlights

**Problem**: Need to remove all highlights for a specific book from Kobo, Calibre, or both databases (e.g., before re-running a conversion, or to clean up test data).

**Solution**: Use the `clear-highlights` skill.

**Load the skill**:
```bash
skill({ name: "clear-highlights" })
```

See `.agents/skills/clear-highlights/SKILL.md` for the workflow.
