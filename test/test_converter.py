import json
import pathlib
import sys
import unittest

import bs4
import bs4.element

# Add parent directory to path to import modules
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
# flake8: noqa: E402
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
        {
            "name": "new_native_delta0",
            "highlights_file": "highlights_delta0.json",
            "epub_file": "delta0.epub",
            "kepub_format": "new",
        },
    ]

    def test_kobo_to_calibre_conversion(self):
        """Test the actual CFI conversion from Kobo to Calibre format.

        This is the core integration test that verifies the complete
        conversion pipeline. Tests via the high-level
        process_calibre_epub_from_kobo function.
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
                            color=kobo_h.get("Color", 0),
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
                            f"Start CFI mismatch for "
                            f"'{joined['kobo']['Text'][:30]}...'",
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

        Uses the same test data but in reverse: takes Calibre CFI and
        converts to Kobo path. Tests via the high-level
        process_calibre_epub_from_calibre function.
        """
        test_dir = pathlib.Path(__file__).parent
        project_dir = test_dir.parent

        for config in self.TEST_CONFIGS:
            with self.subTest(format=config["name"]):
                epub_path = project_dir / "test" / config["epub_file"]
                if not epub_path.exists():
                    self.skipTest(f"Test EPUB not found: {epub_path}")
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
                            f"Start path mismatch for "
                            f"'{joined['expected']['highlighted_text'][:30]}"
                            f"...'",
                        )
                        self.assertEqual(
                            result.end_path,
                            kobo_h["EndContainerPath"],
                            f"End path mismatch for "
                            f"'{joined['expected']['highlighted_text'][:30]}"
                            f"...'",
                        )

                        # Verify offsets match
                        self.assertEqual(
                            result.start_offset,
                            kobo_h["StartOffset"],
                            f"Start offset mismatch for "
                            f"'{joined['expected']['highlighted_text'][:30]}"
                            f"...'",
                        )
                        self.assertEqual(
                            result.end_offset,
                            kobo_h["EndOffset"],
                            f"End offset mismatch for "
                            f"'{joined['expected']['highlighted_text'][:30]}"
                            f"...'",
                        )

                        # Verify color is converted correctly
                        expected_color = kobo_h.get("Color", 0)
                        self.assertEqual(
                            result.color,
                            expected_color,
                            f"Color mismatch for "
                            f"'{joined['expected']['highlighted_text'][:30]}"
                            f"...'",
                        )


class TestCFIEncoding(unittest.TestCase):
    """Unit tests for CFI encoding/decoding with edge cases."""

    def _make_soup(self, html):
        return bs4.BeautifulSoup(html, "html.parser")

    def test_encode_cfi_text_first_child(self):
        """When a text node is the first child: <p>hello <em>world</em></p>"""
        soup = self._make_soup("<html><body><p>hello <em>world</em></p></body></html>")
        text_node = list(soup.find("p").children)[0]  # "hello "
        self.assertIsInstance(text_node, bs4.element.NavigableString)
        cfi = converter.encode_cfi(text_node, 3)
        # Path: html(/2) -> body(/2) -> p(/2) -> text node 1 = /1:3
        self.assertEqual(cfi, "/2/2/2/1:3")

    def test_encode_cfi_element_first_child(self):
        """When an element is the first child: <p><em>word</em> rest</p>

        _adjust_node_for_text_offset walks back from " rest" to <em>,
        producing an even index (2) for <em> with offset unchanged.
        Calibre's encoder does the same: elements without calibreRangeWrapper
        don't contribute to offset during backward walk.
        """
        soup = self._make_soup("<html><body><p><em>word</em> rest</p></body></html>")
        p = soup.find("p")
        # Children: [<em>, " rest"]
        children = list(p.children)
        self.assertEqual(len(children), 2)

        # The text " rest" is the second child, after <em>
        text_node = children[1]
        self.assertIsInstance(text_node, bs4.element.NavigableString)
        self.assertEqual(str(text_node), " rest")

        # _adjust_node_for_text_offset walks back to <em> (index 2, even)
        # offset stays at 1 (element nodes don't add to offset)
        # Path: html(/2) -> body(/2) -> p(/2) -> <em> = /2:1
        cfi = converter.encode_cfi(text_node, 1)
        self.assertEqual(cfi, "/2/2/2/2:1")

    def test_encode_cfi_nested_elements(self):
        """<p><strong><em>bold italic</em></strong> plain</p>

        _adjust_node_for_text_offset walks back from " plain" to <strong>
        (element, no offset added). <strong> gets even index 2.
        """
        soup = self._make_soup(
            "<html><body><p><strong><em>bold italic</em></strong> plain</p></body></html>"
        )
        p = soup.find("p")
        text_node = list(p.children)[1]  # " plain"
        self.assertEqual(str(text_node), " plain")

        cfi = converter.encode_cfi(text_node, 0)
        # <strong>=2, adjustment walks back to <strong>
        # Path: html(/2) -> body(/2) -> p(/2) -> <strong> = /2:0
        self.assertEqual(cfi, "/2/2/2/2:0")

    def test_encode_decode_roundtrip(self):
        """Encoding then decoding should return the same node and offset."""
        html = "<html><body><div><h2>Title</h2><p><em>word</em> rest of text</p></div></body></html>"
        soup = self._make_soup(html)
        p = soup.find("p")
        text_node = list(p.children)[1]  # " rest of text"
        self.assertEqual(str(text_node), " rest of text")

        cfi = converter.encode_cfi(text_node, 5)
        # _adjust_node_for_text_offset walks back to <em> (index 2, even)
        # Path: html(/2) -> body(/2) -> div(/2) -> p(/4) -> <em> = /2:5
        self.assertEqual(cfi, "/2/2/2/4/2:5")

        decoded_node, decoded_offset = converter.decode_calibre_cfi(soup, cfi)
        self.assertIs(decoded_node, text_node)
        self.assertEqual(decoded_offset, 5)

    def test_decode_odd_step_selects_text_node(self):
        """Odd final step selects text nodes by index."""
        soup = self._make_soup("<html><body><p>first<em>mid</em>last</p></body></html>")
        # Children of <p>: ["first", <em>, "last"]
        # Text nodes only: ["first"=index 0, "last"=index 1]
        # Odd step 1 (index 0) -> "first", step 3 (index 1) -> "last"
        # Full path: /2(body)/2(p)/1:2 for "first" at offset 2
        #            /2(body)/2(p)/3:1 for "last" at offset 1

        node, offset = converter.decode_calibre_cfi(soup, "/2/2/2/1:2")
        self.assertEqual(str(node), "first")
        self.assertEqual(offset, 2)

        node, offset = converter.decode_calibre_cfi(soup, "/2/2/2/3:1")
        self.assertEqual(str(node), "last")
        self.assertEqual(offset, 1)

    def test_decode_even_step_selects_element(self):
        """Even final step selects element, then walks forward to find text.

        For <p><em>word</em> rest</p>, Calibre's encode produces /2:5 for
        " rest" at offset 1 (after adjustment walks back to <em>).
        Decoding: even step 2 -> <em>, then node_for_text_offset skips <em>
        (not a text node), finds " rest", returns offset 5.
        """
        soup = self._make_soup("<html><body><p><em>word</em> rest</p></body></html>")
        # CFI /2(body)/2(p)/2:1 -> <em> + walk forward, offset 1 -> " rest" at 1
        node, offset = converter.decode_calibre_cfi(soup, "/2/2/2/2:1")
        self.assertEqual(str(node), " rest")
        self.assertEqual(offset, 1)


class TestBs4NodeAtTextOffset(unittest.TestCase):
    """Unit tests for _bs4_node_at_text_offset boundary conditions."""

    def _make_body(self, html):
        soup = bs4.BeautifulSoup(html, "html.parser")
        return soup.body

    def test_offset_at_start(self):
        body = self._make_body("<html><body><p>hello</p></body></html>")
        node, off = converter._bs4_node_at_text_offset(body, 0)
        self.assertEqual(str(node), "hello")
        self.assertEqual(off, 0)

    def test_offset_in_middle(self):
        body = self._make_body("<html><body><p>hello</p></body></html>")
        node, off = converter._bs4_node_at_text_offset(body, 3)
        self.assertEqual(str(node), "hello")
        self.assertEqual(off, 3)

    def test_boundary_prefers_next_for_start(self):
        """At a boundary between nodes, start positions go to next node."""
        body = self._make_body("<html><body><p>ab</p><p>cd</p></body></html>")
        # "ab" is at offset 0-2, "cd" at offset 2-4
        # Offset 2 is the boundary — for start, should pick "cd" at offset 0
        node, off = converter._bs4_node_at_text_offset(body, 2, is_end=False)
        self.assertEqual(str(node), "cd")
        self.assertEqual(off, 0)

    def test_boundary_prefers_current_for_end(self):
        """At a boundary between nodes, end positions stay in current node."""
        body = self._make_body("<html><body><p>ab</p><p>cd</p></body></html>")
        # Offset 2 at boundary — for end, should pick "ab" at offset 2
        node, off = converter._bs4_node_at_text_offset(body, 2, is_end=True)
        self.assertEqual(str(node), "ab")
        self.assertEqual(off, 2)

    def test_end_of_document(self):
        """Offset at the very end of all text should return end of last node."""
        body = self._make_body("<html><body><p>hello</p></body></html>")
        node, off = converter._bs4_node_at_text_offset(body, 5)
        self.assertEqual(str(node), "hello")
        self.assertEqual(off, 5)

    def test_whitespace_nodes_counted(self):
        """Whitespace text nodes between elements are counted."""
        body = self._make_body("<html><body><div>\n<p>text</p>\n</div></body></html>")
        # Nodes: "\n" (len 1), "text" (len 4), "\n" (len 1)
        # Offset 1 should be start of "text"
        node, off = converter._bs4_node_at_text_offset(body, 1)
        self.assertEqual(str(node), "text")
        self.assertEqual(off, 0)


class TestFindElementChildPath(unittest.TestCase):
    """Unit tests for _find_element_child_path."""

    def _make_soup(self, html):
        return bs4.BeautifulSoup(html, "html.parser")

    def test_direct_child_of_body(self):
        """Text directly inside body's first element child."""
        soup = self._make_soup("<html><body><p>hello</p></body></html>")
        text_node = soup.find("p").string
        path = converter._find_element_child_path(soup.body, text_node)
        self.assertEqual(path, [0])

    def test_second_child_of_body(self):
        """Text in body's second element child."""
        soup = self._make_soup("<html><body><h1>title</h1><p>text</p></body></html>")
        text_node = soup.find("p").string
        path = converter._find_element_child_path(soup.body, text_node)
        self.assertEqual(path, [1])

    def test_nested_in_wrapper_div(self):
        """Text inside body > div > p (nested structure like delta0 epub)."""
        soup = self._make_soup(
            "<html><body><div><h2>Title</h2><p>content</p></div></body></html>"
        )
        text_node = soup.find("p").string
        path = converter._find_element_child_path(soup.body, text_node)
        # body > div(0) > p(1)
        self.assertEqual(path, [0, 1])

    def test_skips_text_nodes_in_counting(self):
        """Whitespace text nodes between elements don't affect element indexing."""
        soup = self._make_soup(
            "<html><body>\n<h1>title</h1>\n<p>text</p>\n</body></html>"
        )
        text_node = soup.find("p").string
        path = converter._find_element_child_path(soup.body, text_node)
        # h1 is element child 0, p is element child 1 (whitespace nodes skipped)
        self.assertEqual(path, [1])

    def test_deeply_nested(self):
        """Text inside body > div > section > p."""
        soup = self._make_soup(
            "<html><body><div><section><p>deep</p></section></div></body></html>"
        )
        text_node = soup.find("p").string
        path = converter._find_element_child_path(soup.body, text_node)
        # body > div(0) > section(0) > p(0)
        self.assertEqual(path, [0, 0, 0])

    def test_raises_if_not_under_body(self):
        """Should raise ValueError if target_node is not a descendant of body."""
        soup = self._make_soup(
            "<html><head><title>t</title></head><body><p>x</p></body></html>"
        )
        title_text = soup.find("title").string
        with self.assertRaises(ValueError):
            converter._find_element_child_path(soup.body, title_text)


class TestComputeOffsetInParent(unittest.TestCase):
    """Unit tests for _compute_offset_in_parent."""

    def _make_soup(self, html):
        return bs4.BeautifulSoup(html, "html.parser")

    def test_single_text_node(self):
        """Offset in a simple <p>text</p> is just overall_offset."""
        soup = self._make_soup("<html><body><p>hello world</p></body></html>")
        text_node = soup.find("p").string
        result = converter._compute_offset_in_parent(text_node, 5)
        self.assertEqual(result, 5)

    def test_text_after_inline_element(self):
        """Offset accounts for text inside preceding inline elements."""
        soup = self._make_soup("<html><body><p><em>bold</em> rest</p></body></html>")
        p = soup.find("p")
        # Children: [<em>"bold"</em>, " rest"]
        text_node = list(p.children)[1]  # " rest"
        self.assertIsInstance(text_node, bs4.element.NavigableString)
        # "bold" has length 4, so offset 2 in " rest" => 4 + 2 = 6
        result = converter._compute_offset_in_parent(text_node, 2)
        self.assertEqual(result, 6)

    def test_first_text_node_zero_offset(self):
        """First text node with offset 0 returns 0."""
        soup = self._make_soup("<html><body><p><em>word</em> tail</p></body></html>")
        em = soup.find("em")
        text_node = em.string  # "word"
        result = converter._compute_offset_in_parent(text_node, 0)
        self.assertEqual(result, 0)

    def test_multiple_inline_elements(self):
        """Offset sums all preceding text in parent."""
        soup = self._make_soup("<html><body><p><b>ab</b><i>cd</i>ef</p></body></html>")
        p = soup.find("p")
        text_node = list(p.children)[2]  # "ef"
        self.assertEqual(str(text_node), "ef")
        # "ab" (2) + "cd" (2) = 4, plus offset 1 => 5
        result = converter._compute_offset_in_parent(text_node, 1)
        self.assertEqual(result, 5)


if __name__ == "__main__":
    unittest.main()
