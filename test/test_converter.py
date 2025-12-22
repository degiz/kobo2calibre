import json
import pathlib
import sys
import unittest

# Add parent directory to path to import modules
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import converter
import db


class TestConverter(unittest.TestCase):
    """Test the converter module using real Kobo and Calibre highlight data."""

    TEST_CONFIGS = [
        {
            "name": "old_kte",
            "highlights_file": "highlights_old_kte.json",
            "epub_file": "jung.epub",
            "kepub_format": "old",
        },
        {
            "name": "new_native",
            "highlights_file": "highlights_new_native.json",
            "epub_file": "jung.epub",
            "kepub_format": "new",
        },
    ]

    def test_kobo_to_calibre_conversion(self):
        """Test the actual CFI conversion from Kobo to Calibre format.

        This is the core integration test that verifies the complete conversion pipeline.
        Tests via the high-level process_calibre_epub_from_kobo function.
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

                # Create KoboSourceHighlight objects from test data
                kobo_highlights = []
                for joined in joined_highlights:
                    kobo_h = joined["kobo"]
                    content_id = kobo_h["ContentID"]
                    parts = content_id.split("!")
                    content_path = "/".join(parts[1:])

                    kobo_highlights.append(
                        db.KoboSourceHighlight(
                            start_path=kobo_h["StartContainerPath"],
                            end_path=kobo_h["EndContainerPath"],
                            start_offset=kobo_h["StartOffset"],
                            end_offset=kobo_h["EndOffset"],
                            text=kobo_h["Text"],
                            content_path=content_path,
                            color=kobo_h["Color"],
                        )
                    )

                # Call the high-level function
                calibre_highlights = converter.process_calibre_epub_from_kobo(
                    epub_path,
                    book_id=408,
                    highlights=kobo_highlights,
                    kepub_format=config["kepub_format"],
                )

                self.assertEqual(len(calibre_highlights), len(joined_highlights))

                # Verify each highlight
                for i, joined in enumerate(joined_highlights):
                    expected = joined["expected"]
                    result = calibre_highlights[i]

                    with self.subTest(
                        format=config["name"],
                        text=joined["kobo"]["Text"][:30],
                    ):
                        result_data = result.highlight

                        # Verify CFI matches
                        self.assertEqual(
                            result_data["start_cfi"],
                            expected["start_cfi"],
                            f"Start CFI mismatch for '{joined['kobo']['Text'][:30]}...'",
                        )
                        self.assertEqual(
                            result_data["end_cfi"],
                            expected["end_cfi"],
                            f"End CFI mismatch for '{joined['kobo']['Text'][:30]}...'",
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
        Tests via the high-level process_calibre_epub_from_calibre function.
        """
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

                # Create CalibreSourceHighlight objects from test data
                calibre_highlights = []
                for joined in joined_highlights:
                    calibre_h = joined["expected"]
                    calibre_highlights.append(
                        db.CalibreSourceHighlight(
                            start_cfi=calibre_h["start_cfi"],
                            end_cfi=calibre_h["end_cfi"],
                            spine_name=calibre_h["spine_name"],
                            highlighted_text=calibre_h["highlighted_text"],
                            color=calibre_h["color"],
                        )
                    )

                # Call the high-level function
                kobo_highlights = converter.process_calibre_epub_from_calibre(
                    epub_path,
                    "test.kepub.epub",
                    calibre_highlights,
                    kepub_format=config["kepub_format"],
                )

                self.assertEqual(len(kobo_highlights), len(joined_highlights))

                # Verify each highlight
                for i, joined in enumerate(joined_highlights):
                    kobo_h = joined["kobo"]
                    result = kobo_highlights[i]

                    with self.subTest(
                        format=config["name"],
                        text=joined["expected"]["highlighted_text"][:30],
                    ):
                        # Verify paths match Kobo format
                        self.assertEqual(
                            result.start_path,
                            kobo_h["StartContainerPath"],
                            f"Start path mismatch for '{joined['expected']['highlighted_text'][:30]}...'",
                        )
                        self.assertEqual(
                            result.end_path,
                            kobo_h["EndContainerPath"],
                            f"End path mismatch for '{joined['expected']['highlighted_text'][:30]}...'",
                        )

                        # Verify offsets match
                        self.assertEqual(
                            result.start_offset,
                            kobo_h["StartOffset"],
                            f"Start offset mismatch for '{joined['expected']['highlighted_text'][:30]}...'",
                        )
                        self.assertEqual(
                            result.end_offset,
                            kobo_h["EndOffset"],
                            f"End offset mismatch for '{joined['expected']['highlighted_text'][:30]}...'",
                        )


if __name__ == "__main__":
    unittest.main()
