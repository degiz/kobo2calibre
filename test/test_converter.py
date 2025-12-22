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

    TEST_CONFIGS = [
        # {
        #     "name": "old_kte",
        #     "highlights_file": "highlights_old_kte.json",
        #     "epub_file": "jung.epub",
        #     "kepub_format": "old",
        # },
        {
            "name": "new_native",
            "highlights_file": "highlights_new_native.json",
            "epub_file": "jung.epub",
            "kepub_format": "new",
        },
    ]

    def test_kobo_to_calibre_conversion(self):
        """Test the actual CFI conversion from Kobo to Calibre format.

        This is the core integration test that verifies the complete conversion pipeline:
        Tests both old KTE format and new native format EPUBs.
        """
        test_dir = pathlib.Path(__file__).parent
        project_dir = test_dir.parent

        for config in self.TEST_CONFIGS:
            with self.subTest(format=config["name"]):
                # Load test data for this config
                with open(test_dir / config["highlights_file"]) as f:
                    joined_highlights = json.load(f)

                epub_path = project_dir / "test" / config["epub_file"]
                if not epub_path.exists():
                    self.skipTest(f"Test EPUB not found: {epub_path}")

                # Create spine index map
                with tempfile.TemporaryDirectory() as tmpdirname:
                    with zipfile.ZipFile(epub_path, "r") as zip_ref:
                        zip_ref.extractall(tmpdirname)

                    spine_index_map, _, _ = converter.get_spine_index_map(
                        pathlib.Path(tmpdirname)
                    )

                    # Test each joined highlight (Kobo → Calibre conversion)
                    for joined in joined_highlights:
                        kobo_h = joined["kobo"]
                        expected = joined["expected"]

                        with self.subTest(format=config["name"], text=kobo_h["Text"]):
                            # Extract content path from ContentID
                            content_id = kobo_h["ContentID"]
                            parts = content_id.split("!")
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

                            # Convert using the specified format
                            result = converter.parse_kobo_highlights(
                                tmpdirname,
                                kobo_highlight,
                                book_id=408,
                                spine_index_map=spine_index_map,
                                kepub_format=config["kepub_format"],
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
                            self.assertEqual(
                                result_data["highlighted_text"],
                                expected["highlighted_text"],
                            )

                            # Verify color matches
                            self.assertEqual(
                                result_data["style"]["which"], expected["color"]
                            )

                            # Verify spine info matches
                            self.assertEqual(
                                result_data["spine_name"], expected["spine_name"]
                            )
                            self.assertEqual(
                                result_data["spine_index"], expected["spine_index"]
                            )

    def test_calibre_to_kobo_conversion(self):
        """Test the CFI conversion from Calibre to Kobo format.

        Uses the same test data but in reverse: takes Calibre CFI and converts to Kobo path.
        Tests both old KTE format and new native format.
        """
        from bs4 import BeautifulSoup

        test_dir = pathlib.Path(__file__).parent
        project_dir = test_dir.parent

        epub_path = project_dir / "test" / "jung.epub"
        if not epub_path.exists():
            self.skipTest(f"Test EPUB not found: {epub_path}")

        for config in self.TEST_CONFIGS:
            with self.subTest(format=config["name"]):
                # Load test data for this config
                with open(test_dir / config["highlights_file"]) as f:
                    joined_highlights = json.load(f)

                with tempfile.TemporaryDirectory() as tmpdirname:
                    with zipfile.ZipFile(epub_path, "r") as zip_ref:
                        zip_ref.extractall(tmpdirname)

                    for joined in joined_highlights:
                        kobo_h = joined["kobo"]
                        calibre_h = joined["expected"]

                        with self.subTest(
                            format=config["name"],
                            text=calibre_h["highlighted_text"][:30],
                        ):
                            # Load the HTML file for this highlight
                            spine_path = (
                                pathlib.Path(tmpdirname) / calibre_h["spine_name"]
                            )
                            with open(spine_path, "rb") as f:
                                raw_html = f.read()
                            soup = BeautifulSoup(raw_html, "html.parser")

                            # Convert start CFI
                            start_path, start_offset = (
                                converter.convert_calibre_cfi_to_kobo(
                                    soup,
                                    calibre_h["start_cfi"],
                                    raw_html=raw_html,
                                    kepub_format=config["kepub_format"],
                                )
                            )

                            # Convert end CFI
                            end_path, end_offset = (
                                converter.convert_calibre_cfi_to_kobo(
                                    soup,
                                    calibre_h["end_cfi"],
                                    raw_html=raw_html,
                                    kepub_format=config["kepub_format"],
                                )
                            )

                            # Verify paths match Kobo format
                            self.assertEqual(
                                start_path,
                                kobo_h["StartContainerPath"],
                                f"Start path mismatch for '{calibre_h['highlighted_text'][:30]}...'",
                            )
                            self.assertEqual(
                                end_path,
                                kobo_h["EndContainerPath"],
                                f"End path mismatch for '{calibre_h['highlighted_text'][:30]}...'",
                            )

                            # Verify offsets match
                            self.assertEqual(
                                start_offset,
                                kobo_h["StartOffset"],
                                f"Start offset mismatch for '{calibre_h['highlighted_text'][:30]}...'",
                            )
                            self.assertEqual(
                                end_offset,
                                kobo_h["EndOffset"],
                                f"End offset mismatch for '{calibre_h['highlighted_text'][:30]}...'",
                            )


if __name__ == "__main__":
    unittest.main()
