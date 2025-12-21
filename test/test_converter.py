import json
import pathlib
import sys
import tempfile
import unittest
import zipfile

# Add parent directory to path to import modules
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import converter
import db


class TestConverter(unittest.TestCase):
    """Test the converter module using real Kobo and Calibre highlight data."""

    @classmethod
    def setUpClass(cls):
        """Load test data once for all tests."""
        test_dir = pathlib.Path(__file__).parent
        project_dir = test_dir.parent

        # Load joined highlights file (combines Kobo input + Calibre expected output)
        with open(test_dir / "highlights_old_kte.json") as f:
            cls.joined_highlights = json.load(f)

        # Path to test EPUB (old KTE format)
        cls.epub_path = project_dir / "test" / "old_kte.epub"

    def test_kobo_color_to_calibre_color(self):
        """Test color conversion from Kobo to Calibre format."""
        # Based on actual data in test files
        self.assertEqual(converter.kobo_color_to_calibre_color(0), "yellow")
        self.assertEqual(converter.kobo_color_to_calibre_color(1), "purple")
        self.assertEqual(converter.kobo_color_to_calibre_color(2), "blue")
        self.assertEqual(converter.kobo_color_to_calibre_color(3), "green")
        # Default case
        self.assertEqual(converter.kobo_color_to_calibre_color(99), "yellow")

    def test_calibre_color_to_kobo_color(self):
        """Test color conversion from Calibre to Kobo format."""
        self.assertEqual(converter.calibre_color_to_kobo_color("yellow"), 0)
        self.assertEqual(converter.calibre_color_to_kobo_color("purple"), 1)
        self.assertEqual(converter.calibre_color_to_kobo_color("blue"), 2)
        self.assertEqual(converter.calibre_color_to_kobo_color("green"), 3)
        # Default case
        self.assertEqual(converter.calibre_color_to_kobo_color("unknown"), 0)

    def test_kobo_to_calibre_conversion(self):
        """Test the actual CFI conversion from Kobo to Calibre format.

        This is the core integration test that verifies the complete conversion pipeline:
        1. Loads the old KTE format EPUB (old_kte.epub)
        2. Converts each Kobo highlight (from kobo_highlights_backup_old.json)
        3. Compares generated CFIs against expected values (from calibre_highlights_backup_old.json)

        This tests the full path: Kobo span#kobo.X.Y format → HTML parsing → Calibre CFI encoding
        """
        if not self.epub_path.exists():
            self.skipTest(f"Test EPUB not found: {self.epub_path}")

        # Create spine index map
        with tempfile.TemporaryDirectory() as tmpdirname:
            with zipfile.ZipFile(self.epub_path, "r") as zip_ref:
                zip_ref.extractall(tmpdirname)

            spine_index_map, _, _ = converter.get_spine_index_map(
                pathlib.Path(tmpdirname)
            )

            # Test each joined highlight (Kobo → Calibre conversion)
            for joined in self.joined_highlights:
                kobo_h = joined["kobo"]
                expected = joined["calibre_annot_data"]

                with self.subTest(text=kobo_h["Text"]):
                    # Extract content path from ContentID
                    # Format: "/mnt/onboard/...epub!OEBPS!chapter1.xhtml"
                    content_id = kobo_h["ContentID"]
                    parts = content_id.split("!")
                    # Join OEBPS/chapter1.xhtml
                    content_path = "/".join(parts[1:])

                    # Create KoboSourceHighlight
                    kobo_highlight = db.KoboSourceHighlight(
                        start_path=kobo_h["StartContainerPath"],
                        end_path=kobo_h["EndContainerPath"],
                        start_offset=kobo_h["StartOffset"],
                        end_offset=kobo_h["EndOffset"],
                        text=kobo_h["Text"],
                        content_path=content_path,
                        color=kobo_h["Color"],
                    )

                    # Convert using old KTE format
                    result = converter.parse_kobo_highlights(
                        tmpdirname,
                        kobo_highlight,
                        book_id=401,
                        spine_index_map=spine_index_map,
                        kepub_format="old",
                    )

                    # Verify conversion succeeded
                    self.assertIsNotNone(
                        result, f"Conversion failed for: {kobo_h['Text']}"
                    )

                    # Parse result highlight JSON
                    result_data = result.highlight

                    # Verify CFI matches
                    self.assertEqual(
                        result_data["start_cfi"],
                        expected["start_cfi"],
                        f"Start CFI mismatch for '{kobo_h['Text'][:30]}...'",
                    )
                    self.assertEqual(
                        result_data["end_cfi"],
                        expected["end_cfi"],
                        f"End CFI mismatch for '{kobo_h['Text'][:30]}...'",
                    )

                    # Verify text matches
                    self.assertEqual(result_data["highlighted_text"], kobo_h["Text"])

                    # Verify color matches
                    expected_color = converter.kobo_color_to_calibre_color(
                        kobo_h["Color"]
                    )
                    self.assertEqual(result_data["style"]["which"], expected_color)

                    # Verify spine info matches
                    self.assertEqual(result_data["spine_name"], expected["spine_name"])
                    self.assertEqual(
                        result_data["spine_index"], expected["spine_index"]
                    )


if __name__ == "__main__":
    unittest.main()
