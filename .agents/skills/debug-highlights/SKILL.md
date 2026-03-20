---
name: debug-highlights
description: Debug incorrect Kobo→Calibre highlight conversions via ground-truth comparison
compatibility: opencode
metadata:
  workflow: interactive
  destructive: true
  requires_device: true
---

# Debug Highlights Skill

Debug CFI conversion issues by creating manual ground-truth highlights in both systems and comparing converter output.

## Config

Read `paths.kobo_db` and `paths.calibre_db` from `.agents/config.yaml`. If the file is missing, ask the user for paths and create it.

- **Defaults**: Kobo `KoboReader.sqlite` on mounted volume, Calibre `metadata.db` in library dir
- Logs: `.agents/logs/debug-highlights-<timestamp>.log`
- Kepub: Always `new` format, max verbosity (`-vv`)

## Workflow

**WARNING**: Deletes all highlights for selected book (preserved in memory, but lost if skill crashes). User should have backups.

**IMPORTANT** Kobo and Calibre use different versions of the same book: Calibre has a original epub, while Kobo has a kepubified version. The source code of "kepubify" is available in "kepubify.py". If needed, lookup other source code of Calibre.

**IMPORTANT** Calibre's CFI encode/decode logic lives in `cfi.pyj`: https://raw.githubusercontent.com/kovidgoyal/calibre/master/src/pyj/read_book/cfi.pyj — key functions: `encode()`, `adjust_node_for_text_offset()`, `decode()`, `node_for_text_offset()`.

**IMPORTANT** Calibre's kepubify logic (adds kobo spans to EPUB HTML): https://raw.githubusercontent.com/kovidgoyal/calibre/master/src/calibre/ebooks/oeb/polish/kepubify.py — local copy in `kepubify.py`. Key function: `kepubify_html_data()`.

**IMPORTANT** Always run `calibre-customize -b $(pwd)` before `calibre-debug -e`. The dual import loads the installed plugin, not local files. Symptom of staleness: debug logging you added doesn't appear.

### Phase 1: Identify Book
1. Verify Kobo mounted: `test -f /Volumes/KOBOeReader/.kobo/KoboReader.sqlite`
2. Ask user for book name
3. Query: `SELECT DISTINCT VolumeID, COUNT(*) FROM Bookmark WHERE VolumeID LIKE '%?%' AND text != '' GROUP BY VolumeID`
4. User confirms which VolumeID

### Phase 2.5: Ground Truth Setup
1. User selects 1 highlight to test
2. Preserve all highlights to memory (both DBs)
3. Delete all existing highlights, including those marked as "removed": `DELETE FROM Bookmark WHERE VolumeID = ?` and `DELETE FROM annotations WHERE book = ?`
4. User creates same highlight manually on Kobo device (unmount, highlight, remount)
5. Verify: `SELECT * FROM Bookmark WHERE VolumeID = ? ORDER BY DateCreated DESC LIMIT 1`
6. User creates same highlight manually in Calibre viewer (must close viewer to save)
7. Verify: `SELECT annot_data FROM annotations WHERE book = ? LIMIT 1`
8. Display both ground truth highlights side-by-side
9. User confirms ready for conversion

### Phase 3: Run Conversion
1. Create log: `.agents/logs/debug-highlights-$(date +%Y%m%d-%H%M%S).log`
2. Extract book title from VolumeID for `--filter_bookname`
3. Run: `calibre-debug -e kobo2calibre.py -- --filter_bookname "<title>" /Volumes/KOBOeReader /Volumes/Stuff/Calibre --kepub_format new --both_ways -vv 2>&1 | tee "$LOG_FILE"`
4. Display summary (processed count, warnings, errors)

### Phase 4: Compare Ground Truth vs Converter Output
1. Query both: `SELECT annot_data, timestamp FROM annotations WHERE book = ? ORDER BY timestamp`
2. Ignore the "highlighted text" field in databse records, because it's just a copy-paste, it doesn't reflect the actual highlighed text in the book
3. Extract CFIs: ground truth (manual) and converter output
4. Display side-by-side comparison table (spine path, block path, offsets, text)
5. Classify mismatch type (see Issue Types below)
6. User confirms to proceed with root cause analysis

### Phase 5: Root Cause Analysis
1. Classify issue (see Issue Types)
2. Map to code location in `converter.py`
3. Provide investigation steps and fix suggestions
4. User decides: investigate code or end skill

---

## Issue Types

| Type | Symptom | Root Cause | Location |
|------|---------|-----------|----------|
| **A: Spine Path** | Wrong chapter in CFI | Spine ordering/path resolution | `get_spine_index_map()` |
| **B: Block Number** | CFI block ≠ Kobo block | HTML tag counting mismatch | `BLOCK_TAGS` constant |
| **C: Char Offset** ⭐ | Correct block, wrong text position | Sentence splitting differs | `get_block_offset_from_kepubify()` |
| **D: Sentence Number** | Wrong sentence in block | Sentence counting differs | `split_into_sentences()` |
| **E: Complete Failure** | Missing or error | Various | `convert_kobo_to_calibre_highlight()` |

## DB Schemas

**Kobo** (`Bookmark`): VolumeID, ContentID, Start/EndContainerPath, Start/EndOffset, Text, Color  
Format: `#kobo.{block}.{sentence}` (1-indexed)

**Calibre** (`annotations`): book (FK), annot_data (JSON)  
CFI: `/6/2[chapter1]!/4/12/1:0` = spine/DOM path/char offset

## Testing Fix

1. Convert: `calibre-debug -e kobo2calibre.py -- --filter_bookname "Book" /Volumes/KOBOeReader /Volumes/Stuff/Calibre --kepub_format new -vv`
2. Verify in Calibre GUI viewer
3. Run: `make test`
4. Add regression test to `test/test_converter.py`
