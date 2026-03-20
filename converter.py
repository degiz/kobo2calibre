import logging
import pathlib
import re
import tempfile
import time
import uuid
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import bs4  # type: ignore
from bs4 import BeautifulSoup

from db import KoboTargetHighlight

try:
    # For calibre gui plugin
    from calibre_plugins.kobo2calibre import db  # type: ignore
except ImportError:
    # For cli
    import db  # type: ignore

# Try to import calibre's kepubify (available when running via calibre-debug)
try:
    from calibre.ebooks.oeb.polish.kepubify import (  # type: ignore
        kepubify_html_data,
        Options as KepubifyOptions,
    )
    from calibre.spell.break_iterator import sentence_positions  # type: ignore
    from lxml import etree  # type: ignore

    HAS_KEPUBIFY = True
except ImportError:
    sentence_positions = None  # type: ignore
    HAS_KEPUBIFY = False

logger = logging.getLogger(__name__)

# Fallback regex for CLI mode (when calibre's sentence_positions is not available).
# Matches sentences terminated by . ! or ? (NOT colon — neither Calibre's ICU
# sentence breaker nor Go kepubify treat colon as a sentence terminator).
REGEX_KTE = re.compile(
    r'(\s*.*?[\.\!\?][\'"\u201c\u201d\u2018\u2019\u2026]?\s*)',
    re.UNICODE | re.MULTILINE,
)

# Block tags that increment the paragraph counter in Kobo's numbering scheme
BLOCK_TAGS = frozenset(("p", "ol", "ul", "table", "h1", "h2", "h3", "h4", "h5", "h6"))


def split_into_sentences(text: str, lang: str = "en") -> List[str]:
    """Split text into sentences using Calibre's ICU-based splitter when available."""
    if sentence_positions is not None:
        sentences = []
        for pos, sz in sentence_positions(text, lang):
            sentences.append(text[pos : pos + sz])
        return sentences
    else:
        # Fallback to regex for CLI mode
        groups = REGEX_KTE.split(text)
        return [g for g in groups if g != ""]


def get_kepubify_block_delta(root) -> int:
    """Determine the delta between kepubify block numbers and original block numbers.

    Kepubify may skip block 1 if there is whitespace text before the first
    block-level element, causing paranum to increment before any block tag is
    encountered. In that case the first kepubify block is 2 while the first
    original block is 1, giving a delta of 1.

    Returns the delta such that: original_block = kepubify_block - delta
    """
    # Find the first kobo span to determine what block number kepubify starts at
    all_spans = root.xpath('//*[starts-with(@id, "kobo.")]')
    if not all_spans:
        return 0

    first_id = all_spans[0].get("id", "")
    # Parse "kobo.N.M"
    parts = first_id.split(".")
    if len(parts) >= 2:
        first_block = int(parts[1])
        # first_block is the kepubify number for the first block element.
        # The first block element in the original document is always 1.
        # If kepubify starts at 2, delta = 1. If it starts at 1, delta = 0.
        delta = first_block - 1
        logger.debug(f"Kepubify first block: {first_block}, block delta: {delta}")
        return delta
    return 0


def _bs4_node_at_text_offset(
    soup_body, absolute_offset: int, is_end: bool = False
) -> Tuple[bs4.element.NavigableString, int]:
    """Find the bs4 NavigableString and offset within it for an absolute text position.

    Walks all NavigableString descendants of body, summing character counts,
    until the target absolute_offset falls within a node.

    When is_end=True, boundary positions (offset == cumulative + node_len)
    prefer end-of-current-node over start-of-next-node.
    """
    cumulative = 0
    last_node = None
    for node in soup_body.descendants:
        if not isinstance(node, bs4.element.NavigableString):
            continue
        if isinstance(node, bs4.element.Comment):
            continue
        text = str(node)
        node_len = len(text)
        end_pos = cumulative + node_len
        if end_pos > absolute_offset:
            offset_in_node = absolute_offset - cumulative
            return node, offset_in_node
        if is_end and end_pos == absolute_offset and node_len > 0:
            # For end positions, prefer end-of-current-node at boundaries
            return node, node_len
        last_node = node
        cumulative += node_len

    # If absolute_offset equals the total text length, return end of last node
    if last_node is not None and cumulative == absolute_offset:
        return last_node, len(str(last_node))

    raise ValueError(
        f"Absolute offset {absolute_offset} exceeds total text length {cumulative}"
    )


def kobo_span_to_calibre_cfi_via_roundtrip(
    raw_html: bytes,
    soup: BeautifulSoup,
    kobo_block: int,
    kobo_sentence: int,
    char_offset: int,
    is_end: bool = False,
) -> Optional[str]:
    """Convert a Kobo span reference to a Calibre CFI using kepubify round-trip.

    This is the most accurate conversion method. It:
    1. Kepubifies the HTML using Calibre's exact algorithm
    2. Locates the target kobo span in the kepubified tree
    3. Finds the containing element and computes the structural path
    4. Follows the same path in the original tree
    5. Finds the target text node and encodes the CFI

    Important: kepubify preserves text within elements but may add/change
    whitespace between block elements. We use per-element offsets instead
    of absolute body offsets to avoid whitespace divergence.
    """
    if not HAS_KEPUBIFY:
        return None

    # 1. Kepubify the HTML
    kepub_root = kepubify_html_data(raw_html, opts=KepubifyOptions())

    # 2. Find the target kobo span
    span_id = f"kobo.{kobo_block}.{kobo_sentence}"
    spans = kepub_root.xpath(f'//*[@id="{span_id}"]')
    if not spans:
        logger.warning(f"Span {span_id} not found in kepubified HTML")
        return None
    target_span = spans[0]

    # 3. Find the containing element and structural path.
    # Kepubify wraps body content in book-columns > book-inner.
    inner_divs = kepub_root.xpath('//*[@id="book-inner"]')
    if inner_divs:
        text_root = inner_divs[0]
    else:
        bodies = kepub_root.xpath("//body") or kepub_root.xpath(
            '//*[local-name()="body"]'
        )
        if not bodies:
            logger.warning("No body found in kepubified HTML")
            return None
        text_root = bodies[0]

    # Build path from text_root to the parent element of target_span,
    # skipping kobo span wrappers (walk up until we reach a non-koboSpan element).
    # The parent of the kobo span is a structural element (p, h2, div, etc.).
    structural_parent = target_span.getparent()
    while (
        structural_parent is not None
        and structural_parent is not text_root
        and structural_parent.get("class") == "koboSpan"
    ):
        structural_parent = structural_parent.getparent()

    # Build ancestry chain from structural_parent up to text_root
    ancestors = []
    current = structural_parent
    while current is not None and current is not text_root:
        ancestors.append(current)
        current = current.getparent()

    if current is not text_root:
        logger.warning("Could not find text_root in ancestor chain of target span")
        return None

    ancestors.reverse()  # top-down order

    # Compute 0-based element-child index path
    path = []
    parent = text_root
    for ancestor in ancestors:
        elem_children = [c for c in parent if isinstance(c, etree._Element)]
        try:
            idx = next(i for i, c in enumerate(elem_children) if c is ancestor)
            path.append(idx)
        except StopIteration:
            logger.warning("Ancestor not found among element children")
            return None
        parent = ancestor

    # Compute offset within structural_parent by walking kobo spans
    offset_in_element = 0
    for event, elem in etree.iterwalk(structural_parent, events=("start",)):
        elem_id = elem.get("id", "")
        if elem_id.startswith("kobo.") and elem.get("class") == "koboSpan":
            if elem is target_span:
                offset_in_element += char_offset
                break
            span_text = "".join(elem.itertext())
            offset_in_element += len(span_text)

    logger.debug(
        f"Kobo span {span_id} offset {char_offset} -> "
        f"path {path}, element offset {offset_in_element}"
    )

    # 4. Follow the same path in the original (bs4) tree
    current_bs4 = soup.body
    for depth, child_index in enumerate(path):
        elem_children = [
            c for c in current_bs4.children if isinstance(c, bs4.element.Tag)
        ]
        if child_index >= len(elem_children):
            logger.warning(
                f"Path index {child_index} out of range at depth {depth} "
                f"(original tree has {len(elem_children)} children)"
            )
            return None
        current_bs4 = elem_children[child_index]

    # 5. Find the text node at offset_in_element within this element
    try:
        target_node, offset_in_node = _bs4_node_at_text_offset(
            current_bs4, offset_in_element, is_end=is_end
        )
    except ValueError as e:
        logger.warning(f"Failed to find text node in original element: {e}")
        return None

    logger.debug(
        f"Original element: node={repr(str(target_node)[:40])}, offset={offset_in_node}"
    )

    # 6. Encode the CFI
    return encode_cfi(target_node, offset_in_node)


def _find_element_child_path(
    soup_body, target_node: bs4.element.NavigableString
) -> List[int]:
    """Find the path of element-child indices from soup_body to the parent of target_node.

    Returns a list of 0-based indices. For example, if target_node is inside
    body > div (0th child) > p (1st child), returns [0, 1].
    """
    # Build ancestry chain from target_node's parent up to body
    ancestors = []
    current = target_node.parent
    while current is not None and current is not soup_body:
        ancestors.append(current)
        current = current.parent

    if current is not soup_body:
        raise ValueError("Could not find body in ancestor chain of target node")

    # Reverse to get top-down order (body's child first)
    ancestors.reverse()

    # For each ancestor, find its 0-based index among element siblings
    path = []
    parent = soup_body
    for ancestor in ancestors:
        child_index = 0
        for child in parent.children:
            if isinstance(child, bs4.element.Tag):
                if child is ancestor:
                    path.append(child_index)
                    break
                child_index += 1
        parent = ancestor

    return path


def _compute_offset_in_parent(
    target_node: bs4.element.NavigableString, overall_offset: int
) -> int:
    """Compute the character offset within the parent element's text content.

    Walks all NavigableString descendants of target_node's parent element,
    summing text before target_node, then adds overall_offset.
    """
    parent = target_node.parent
    offset_in_element = 0
    for node in parent.descendants:
        if not isinstance(node, bs4.element.NavigableString):
            continue
        if isinstance(node, bs4.element.Comment):
            continue
        if node is target_node:
            break
        offset_in_element += len(str(node))
    return offset_in_element + overall_offset


def calibre_cfi_to_kobo_span_via_roundtrip(
    raw_html: bytes,
    soup: BeautifulSoup,
    target_node: bs4.element.NavigableString,
    overall_offset: int,
    is_end: bool = False,
) -> Optional[Tuple[int, int, int]]:
    """Convert a decoded Calibre CFI position to a Kobo span reference via roundtrip.

    This is the reverse of kobo_span_to_calibre_cfi_via_roundtrip:
    1. Finds the structural path from body to the target element
    2. Computes the character offset within that element
    3. Kepubifies the HTML and follows the same structural path
    4. Walks kobo spans within that element to find the right position

    Important: kepubify preserves text within elements but may add/change
    whitespace between block elements. We use per-element offsets instead
    of absolute body offsets to avoid whitespace divergence.

    Returns (block_num, sentence_num, offset_in_sentence) or None.
    """
    if not HAS_KEPUBIFY:
        return None

    # 1. Find the structural path and offset within the target element
    try:
        path = _find_element_child_path(soup.body, target_node)
    except ValueError as e:
        logger.warning(f"Could not find element path: {e}")
        return None

    element_offset = _compute_offset_in_parent(target_node, overall_offset)
    logger.debug(
        f"Target path from body: {path}, "
        f"offset {element_offset} within parent element text"
    )

    # 2. Kepubify the HTML
    kepub_root = kepubify_html_data(raw_html, opts=KepubifyOptions())

    # 3. Follow the same structural path in the kepubified tree.
    # Kepubify wraps body content in book-columns > book-inner, so
    # the children of book-inner correspond to the children of body.
    inner_divs = kepub_root.xpath('//*[@id="book-inner"]')
    if inner_divs:
        text_root = inner_divs[0]
    else:
        bodies = kepub_root.xpath("//body") or kepub_root.xpath(
            '//*[local-name()="body"]'
        )
        if not bodies:
            logger.warning("No body found in kepubified HTML")
            return None
        text_root = bodies[0]

    # Navigate the path in the kepubified tree
    current = text_root
    for depth, child_index in enumerate(path):
        elem_children = [c for c in current if isinstance(c, etree._Element)]
        if child_index >= len(elem_children):
            logger.warning(
                f"Path index {child_index} out of range at depth {depth} "
                f"(kepubified tree has {len(elem_children)} children)"
            )
            return None
        current = elem_children[child_index]

    # 4. Walk kobo spans within this element to find the right position
    cumulative = 0
    current_block = 0
    current_sentence = 0

    for event, elem in etree.iterwalk(current, events=("start",)):
        span_id = elem.get("id", "")
        if span_id.startswith("kobo.") and elem.get("class") == "koboSpan":
            parts = span_id.split(".")
            if len(parts) == 3:
                current_block = int(parts[1])
                current_sentence = int(parts[2])

                span_text = "".join(elem.itertext())
                span_len = len(span_text)

                if cumulative + span_len > element_offset:
                    offset_in_sentence = element_offset - cumulative
                    logger.debug(
                        f"Element offset {element_offset} -> "
                        f"kobo.{current_block}.{current_sentence} "
                        f"offset {offset_in_sentence}"
                    )
                    return (current_block, current_sentence, offset_in_sentence)
                if is_end and cumulative + span_len == element_offset and span_len > 0:
                    return (current_block, current_sentence, span_len)

                cumulative += span_len

    logger.warning(
        f"Could not find kobo span for element offset {element_offset} "
        f"in element at path {path}"
    )
    return None


def get_block_offset_from_kepubify(
    raw_html: bytes, block_num: int, sentence_num: int
) -> Optional[int]:
    """Use Calibre's kepubify to find the character offset.

    Find the character offset from the start of a block to the start of a
    specific sentence. Returns the offset, or None if the span is not found.
    """
    if not HAS_KEPUBIFY:
        logger.warning("Kepubify not available")
        return None

    root = kepubify_html_data(raw_html, opts=KepubifyOptions())

    # Sum text lengths of all spans before the target sentence in this block.
    # Use text_content() to include text from child elements (e.g., img alt text).
    offset = 0
    for sent in range(1, sentence_num):
        span_id = f"kobo.{block_num}.{sent}"
        spans = root.xpath(f'//*[@id="{span_id}"]')
        if spans:
            span_text = spans[0].text_content()
            offset += len(span_text)
            logger.debug(
                f"Span {span_id}: len={len(span_text)}, cumulative offset={offset}"
            )

    # Verify the target span exists
    target_span_id = f"kobo.{block_num}.{sentence_num}"
    target_spans = root.xpath(f'//*[@id="{target_span_id}"]')
    if not target_spans:
        logger.warning(f"Span {target_span_id} not found in kepubified HTML")
        return None

    logger.debug(f"Found span {target_span_id}, offset from block start: {offset}")
    return offset


def find_text_node_at_block_offset(
    soup: BeautifulSoup, target_block: int, char_offset: int
) -> Optional[Tuple[bs4.element.NavigableString, int]]:
    """Find the text node containing a character offset in a block.

    Find the text node in the original document that contains the character
    at the given offset within the specified block.
    Returns (text_node, offset_within_node) or None.
    """
    # Find the Nth block element
    block_num = 0
    target_element = None

    for elem in soup.body.descendants:
        if isinstance(elem, bs4.element.Tag):
            tagname = elem.name.lower() if elem.name else ""
            if tagname in BLOCK_TAGS:
                block_num += 1
                if block_num == target_block:
                    target_element = elem
                    break

    if target_element is None:
        logger.warning(f"Block {target_block} not found in document")
        return None

    # Now find the text node containing the character at char_offset
    # by iterating through all text descendants of this block
    cumulative_offset = 0
    for node in target_element.descendants:
        if not isinstance(node, bs4.element.NavigableString):
            continue
        if isinstance(node, bs4.element.Comment):
            continue

        text = str(node)
        node_len = len(text)

        if cumulative_offset + node_len >= char_offset:
            # This node contains our target character
            offset_in_node = char_offset - cumulative_offset
            logger.debug(
                f"Found text node at offset {char_offset}: "
                f"node_offset={offset_in_node}, text={repr(text[:50])}"
            )
            return (node, offset_in_node)

        cumulative_offset += node_len

    logger.warning(
        f"Offset {char_offset} not found in block {target_block} "
        f"(block has {cumulative_offset} chars)"
    )
    return None


def get_spine_index_map(
    root_dir: pathlib.Path,
) -> Tuple[Dict[str, int], Dict[str, str], str]:
    """Get the spine index map from the content.opf file."""
    content_file = [f for f in root_dir.rglob("*.opf")][0]
    with open(str(content_file)) as f:
        soup = bs4.BeautifulSoup(f.read(), "html.parser")

        # Read spine
        spine_ids = [
            s["idref"]
            for s in soup.package.spine.children
            if isinstance(s, bs4.element.Tag)
        ]
        spine_index = {idref: i for i, idref in enumerate(spine_ids)}

        logger.debug(f"Spine index: {spine_index}")

        # Read manifest
        hrefs = [
            s
            for s in soup.package.manifest
            if isinstance(s, bs4.element.Tag)
            and "application/xhtml" in s["media-type"]
            and (s["id"] in spine_ids)
        ]
        logger.debug(f"Found {len(hrefs)} hrefs")
        result = {}
        fixed_paths = {}
        for h in hrefs:
            final_href = h["href"]
            if not pathlib.Path(root_dir / final_href).exists():
                path = [r for r in root_dir.rglob(f"{h['href'].split('/')[-1]}")][0]
                final_href = str(path.relative_to(root_dir))
                fixed_paths[h["href"]] = final_href
            result[final_href] = spine_index[h["id"]]

        p = str(pathlib.Path(content_file).relative_to(root_dir))
        logger.debug(f"relative path: {p}")

        return (
            result,
            fixed_paths,
            str(pathlib.Path(content_file).relative_to(root_dir)),
        )


def process_calibre_epub_from_kobo(
    book_calibre_epub: pathlib.Path,
    book_id: int,
    highlights: List[db.KoboSourceHighlight],
    kepub_format: str = "new",
) -> List[db.CalibreTargetHighlight]:
    """Process a calibre epub file and return a list of highlights."""
    result = []
    with tempfile.TemporaryDirectory() as tmpdirname:
        with zipfile.ZipFile(book_calibre_epub, "r") as zip_ref:
            zip_ref.extractall(tmpdirname)

            try:
                spine_index_map, fixed_path, _ = get_spine_index_map(
                    pathlib.Path(tmpdirname)
                )

                logger.debug(f"Spine index map: {spine_index_map}")

                count = 0
                for i, h in enumerate(highlights):
                    if h.content_path in fixed_path:
                        highlights[i] = highlights[i]._replace(
                            content_path=fixed_path[h.content_path]
                        )
                    calibre_target_highlight = parse_kobo_highlights(
                        tmpdirname, h, book_id, spine_index_map, kepub_format
                    )
                    if calibre_target_highlight:
                        result.append(calibre_target_highlight)
                        logger.debug(f"Found highlight: {calibre_target_highlight}")
                        count += 1
                logger.debug(f"..found {count} highlights")
            except Exception as e:
                logger.error(
                    f"..failed to convert the highlights: {e} book: {book_calibre_epub}"
                )
    return result


def process_calibre_epub_from_calibre(
    book_calibre_epub: pathlib.Path,
    kobo_lpath: str,
    highlights: List[db.CalibreSourceHighlight],
    kepub_format: str = "new",
):
    """Process a calibre epub file and return a list of highlights."""
    result = []
    with tempfile.TemporaryDirectory() as tmpdirname:
        with zipfile.ZipFile(book_calibre_epub, "r") as zip_ref:
            zip_ref.extractall(tmpdirname)

            _, _, content_file = get_spine_index_map(pathlib.Path(tmpdirname))
            slash_count = content_file.count("/")

            for h in highlights:
                logger.debug(f"Processing spine: {h.spine_name}")
                if not h.spine_name:
                    logger.debug(
                        f"Skipping highlight without spine: {h.highlighted_text}"
                    )
                spine_path = pathlib.Path(tmpdirname) / pathlib.Path(h.spine_name)
                with open(spine_path, "rb") as f:
                    raw_html = f.read()
                soup = BeautifulSoup(raw_html, "html.parser")

                kobo_start_path, kobo_start_offset = convert_calibre_cfi_to_kobo(
                    soup, h.start_cfi, raw_html=raw_html, kepub_format=kepub_format
                )
                kobo_end_path, kobo_end_offset = convert_calibre_cfi_to_kobo(
                    soup,
                    h.end_cfi,
                    raw_html=raw_html,
                    kepub_format=kepub_format,
                    is_end=True,
                )
                logger.debug(f"Calibre CFI: {h.start_cfi}, {h.end_cfi}")
                logger.debug(
                    f"Kobo CFI: {kobo_start_path}, "
                    f"offset: {kobo_start_offset}, {kobo_end_path}, "
                    f"offset: {kobo_end_offset}"
                )
                logger.debug(f"Text: {h.highlighted_text}")

                unique_uuid = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"{h.start_cfi}*{h.end_cfi}*{h.highlighted_text})",
                    ).hex
                )

                if slash_count > 0:
                    adapted_spinename = h.spine_name.replace("/", "!", slash_count)
                else:
                    adapted_spinename = f"!{h.spine_name}"

                kobo_highlight = KoboTargetHighlight(
                    kobo_start_path,
                    kobo_end_path,
                    kobo_start_offset,
                    kobo_end_offset,
                    h.highlighted_text,
                    f"file:///mnt/onboard/{kobo_lpath}",
                    f"/mnt/onboard/{kobo_lpath}!{adapted_spinename}",
                    calibre_color_to_kobo_color(h.color),
                    unique_uuid,
                )
                result.append(kobo_highlight)

    return result


def calibre_color_to_kobo_color(color: str) -> int:
    """Convert a calibre color to a kobo color."""
    if color == "green":
        return 3
    if color == "yellow":
        return 0
    if color == "blue":
        return 2
    if color == "purple":
        return 1
    return 0


def kobo_color_to_calibre_color(color: int) -> str:
    """Convert a kobo color to a calibre color."""
    if color == 3:
        return "green"
    if color == 0:
        return "yellow"
    if color == 2:
        return "blue"
    if color == 1:
        return "purple"
    return "yellow"


def _cfi_index_for_child(children, sentinel) -> int:
    """Compute the EPUB CFI index for a child node among its siblings.

    Uses Calibre's bitwise indexing scheme (matching cfi.pyj encode()):
      - Elements get EVEN numbers (2, 4, 6, ...)
      - Text/other nodes get ODD numbers (1, 3, 5, ...)

    The algorithm walks children using:
      index |= 1       -> if even, bump to next odd (text-node slot)
      if is_element:
          index += 1   -> elements get one more, landing on even
    """
    index = 0
    for child in children:
        index |= 1  # ensure odd (next text-node slot)
        if isinstance(child, bs4.element.Tag):
            index += 1  # elements land on even numbers
        if child is sentinel:
            return index
    raise ValueError("Sentinel node not found among children")


def _adjust_node_for_text_offset(
    target_node: bs4.element.NavigableString, target_offset: int
) -> Tuple[Any, int]:
    """Adjust a text node position by walking backward through previous siblings.

    Mirrors Calibre's adjust_node_for_text_offset() from cfi.pyj:
    walks backward through previousSibling, accumulating text lengths from
    text node siblings, until reaching the first node in the sequence.
    This causes the CFI to be encoded relative to the earliest node,
    which may be an element (like <span>) that precedes the text node.

    Returns (adjusted_node, adjusted_offset).
    """
    node = target_node
    additional_offset = 0
    adjusted = False

    while True:
        prev = node.previous_sibling
        if prev is None:
            break
        # In Calibre's JS: if p.nodeType > Node.COMMENT_NODE: break
        # COMMENT_NODE = 8, ELEMENT_NODE = 1, TEXT_NODE = 3
        # In bs4: Tags and NavigableStrings (excluding Comments) have
        # nodeType equivalents ≤ 8, so we only break on unusual node types.
        # In practice, bs4 children are Tags, NavigableStrings, or Comments.
        if isinstance(prev, bs4.element.Comment):
            break
        if isinstance(prev, bs4.element.NavigableString):
            additional_offset += len(str(prev))
        # Element nodes without calibreRangeWrapper are just skipped
        # (no offset added, but we still move past them)
        node = prev
        adjusted = True

    if adjusted:
        target_offset += additional_offset

    return node, target_offset


def encode_cfi(target_node, target_offset) -> str:
    """Encode a CFI for Calibre using the same algorithm as Calibre's viewer.

    Calibre's CFI scheme (from src/pyj/read_book/cfi.pyj):
    - Intermediate steps: even numbers index element children (2, 4, 6, ...)
    - Final step: uses interleaved numbering where elements=even, text=odd
    - Character offset appended as :<offset>

    Importantly, Calibre's encode() calls adjust_node_for_text_offset() which
    walks backward through previous siblings, so the CFI is encoded relative
    to the earliest node in the sibling sequence. For example, if a text node
    follows a <span>, the CFI will reference the <span>'s index (even) with
    the offset accumulated across all preceding text.
    """
    # Apply Calibre's adjust_node_for_text_offset behavior
    if isinstance(target_node, bs4.element.NavigableString) and not isinstance(
        target_node, bs4.element.Comment
    ):
        adjusted_node, target_offset = _adjust_node_for_text_offset(
            target_node, target_offset
        )
    else:
        adjusted_node = target_node

    logger.debug(
        "Encoding CFI, target_node: %s, target_offset: %s",
        adjusted_node,
        target_offset,
    )
    ancestors = [p for p in adjusted_node.parents][::-1]
    ancestors.append(adjusted_node)
    cfi = ""

    # Encode intermediate path segments (all ancestors above the target node)
    # These use even-number-only element indexing: /2, /4, /6, ...
    for i in range(len(ancestors) - 1):
        parent = ancestors[i]
        child = ancestors[i + 1]
        if child is adjusted_node:
            break
        # For intermediate steps, only count Tag children (even numbers)
        child_index = 0
        for c in parent.children:
            if isinstance(c, bs4.element.Tag):
                child_index += 1
                if c is child:
                    cfi += f"/{child_index * 2}"
                    break

    # Encode the final step using Calibre's interleaved indexing.
    # After _adjust_node_for_text_offset, the node may be a Tag (element) but
    # Calibre's encoder always emits /{index}:{offset} — it does NOT descend
    # into the element. The offset is relative to the text flow starting at
    # the adjusted node and continuing through subsequent siblings.
    index = _cfi_index_for_child(adjusted_node.parent.children, adjusted_node)
    cfi += f"/{index}:{target_offset}"

    return cfi


def is_new_kepub_format(kepub_format: str) -> bool:
    """Check if the kepub format is new or old.

    Args:
        kepub_format: Either 'new' or 'old'

    Returns:
        True if using new format (Calibre kepubify), False if old (KTE).
    """
    return kepub_format == "new"


def find_text_by_kte_path(
    soup: BeautifulSoup, target_tag: int, target_sentence: int, lang: str = "en"
) -> Optional[Tuple[bs4.element.NavigableString, int]]:
    """
    Find text node using old KTE plugin's text-node counting scheme.

    KTE numbered text nodes sequentially (not by blocks), and split
    sentences with regex. Returns (text_node, char_offset_to_start_of_sentence)
    or None if not found.
    """
    n_tag = 1

    for child in soup.body.descendants:
        parent_names = [p.name for p in child.parents]
        if "figure" in parent_names:
            continue

        if (
            not isinstance(child, bs4.element.NavigableString)
            or isinstance(child, bs4.element.Comment)
            or str(child) in ("\n", " ", "\u00a0")
            or str(child).strip() == ""
        ):
            continue

        logger.debug(f"KTE tag #{n_tag}: {repr(str(child)[:50])}...")

        if n_tag == target_tag:
            # Found the right text node, now find the sentence
            sentences = split_into_sentences(str(child), lang)
            if target_sentence <= len(sentences):
                offset = sum(len(s) for s in sentences[: target_sentence - 1])
                return (child, offset)
            else:
                logger.warning(
                    f"Sentence {target_sentence} not found in tag {target_tag} "
                    f"(only {len(sentences)} sentences)"
                )
                return None

        n_tag += 1

    logger.warning(f"KTE tag {target_tag} not found (max was {n_tag - 1})")
    return None


def parse_kobo_highlights(
    book_prefix, highlight, book_id, spine_index_map, kepub_format: str = "new"
) -> Optional[db.CalibreTargetHighlight]:
    """Parse a kobo highlight and return a calibre highlight."""
    kobo_n_start, kobo_n_sentence_start = [
        int(i) for i in highlight.start_path.split("\\.")[1:]
    ]
    kobo_n_end, kobo_n_sentence_end = [
        int(i) for i in highlight.end_path.split("\\.")[1:]
    ]
    logger.debug(
        f"parsing highlight: {highlight.start_path}, "
        f"{highlight.end_path}, {highlight.content_path}"
    )
    logger.debug(f"Text: {highlight.text}")

    input_filename = pathlib.Path(book_prefix) / pathlib.Path(highlight.content_path)

    # That's a dirty hack
    if not pathlib.Path(input_filename).is_file():
        highlight = highlight._replace(
            content_path=highlight.content_path.replace("/", "!")
        )
        input_filename = pathlib.Path(book_prefix) / pathlib.Path(
            highlight.content_path
        )

    with open(input_filename, "rb") as f:
        raw_html = f.read()
    # For chapter title, we still need BeautifulSoup
    soup = BeautifulSoup(raw_html, "html.parser")
    chapter_title = guess_chapter_title(soup)

    use_new_format = is_new_kepub_format(kepub_format)

    if use_new_format and HAS_KEPUBIFY:
        # Use kepubify round-trip: kepubify -> find span -> absolute offset -> original
        logger.debug("Using kepubify round-trip for Kobo->Calibre conversion")

        start_cfi = kobo_span_to_calibre_cfi_via_roundtrip(
            raw_html,
            soup,
            kobo_n_start,
            kobo_n_sentence_start,
            highlight.start_offset,
        )
        end_cfi = kobo_span_to_calibre_cfi_via_roundtrip(
            raw_html,
            soup,
            kobo_n_end,
            kobo_n_sentence_end,
            highlight.end_offset,
            is_end=True,
        )

        if start_cfi is None or end_cfi is None:
            logger.debug(
                "Round-trip conversion failed, falling back to block offset method"
            )
            # Fall back to the block-delta + offset method
            start_cfi = None
            end_cfi = None

        if start_cfi is None or end_cfi is None:
            # Block-delta fallback (original approach)
            logger.debug("Using block-delta fallback for offset calculation")
            kepub_root = kepubify_html_data(raw_html, opts=KepubifyOptions())
            block_delta = get_kepubify_block_delta(kepub_root)

            start_sentence_offset = get_block_offset_from_kepubify(
                raw_html, kobo_n_start, kobo_n_sentence_start
            )
            if start_sentence_offset is None:
                logger.debug("Failed to find the start sentence offset")
                return None

            start_total_offset = start_sentence_offset + highlight.start_offset
            original_block_start = kobo_n_start - block_delta
            start_result = find_text_node_at_block_offset(
                soup, original_block_start, start_total_offset
            )
            if not start_result:
                logger.debug("Failed to find start text node in original document")
                return None
            target_start_node, start_offset_in_node = start_result

            original_block_end = kobo_n_end - block_delta
            if (
                kobo_n_start == kobo_n_end
                and kobo_n_sentence_start == kobo_n_sentence_end
            ):
                end_total_offset = start_sentence_offset + highlight.end_offset
                end_result = find_text_node_at_block_offset(
                    soup, original_block_end, end_total_offset
                )
            else:
                end_sentence_offset = get_block_offset_from_kepubify(
                    raw_html, kobo_n_end, kobo_n_sentence_end
                )
                if end_sentence_offset is None:
                    logger.debug("Failed to find the end sentence offset")
                    return None
                end_total_offset = end_sentence_offset + highlight.end_offset
                end_result = find_text_node_at_block_offset(
                    soup, original_block_end, end_total_offset
                )

            if not end_result:
                logger.debug("Failed to find end text node in original document")
                return None
            target_end_node, end_offset_in_node = end_result

            start_cfi = encode_cfi(target_start_node, start_offset_in_node)
            end_cfi = encode_cfi(target_end_node, end_offset_in_node)
    else:
        # Fallback for old KTE format or when kepubify unavailable
        logger.debug(f"Using {'old KTE' if not use_new_format else 'fallback'} format")

        start_result = find_text_by_kte_path(soup, kobo_n_start, kobo_n_sentence_start)
        if not start_result:
            logger.debug("Failed to find the target start node")
            return None

        target_start_node, sentence_start_offset = start_result
        kobo_target_start_offset = sentence_start_offset + highlight.start_offset

        if kobo_n_start == kobo_n_end:
            target_end_node = target_start_node
            if kobo_n_sentence_start == kobo_n_sentence_end:
                kobo_target_end_offset = sentence_start_offset + highlight.end_offset
            else:
                end_result = find_text_by_kte_path(
                    soup, kobo_n_end, kobo_n_sentence_end
                )
                if not end_result:
                    logger.debug("Failed to find the target end node")
                    return None
                _, sentence_end_offset = end_result
                kobo_target_end_offset = sentence_end_offset + highlight.end_offset
        else:
            end_result = find_text_by_kte_path(soup, kobo_n_end, kobo_n_sentence_end)
            if not end_result:
                logger.debug("Failed to find the target end node")
                return None
            target_end_node, sentence_end_offset = end_result
            kobo_target_end_offset = sentence_end_offset + highlight.end_offset

        start_cfi = encode_cfi(target_start_node, kobo_target_start_offset)
        end_cfi = encode_cfi(target_end_node, kobo_target_end_offset)

    # Common code for both branches
    unique_uuid = str(
        uuid.uuid3(uuid.NAMESPACE_DNS, f"{start_cfi}*{end_cfi}*{highlight.text})").hex
    )

    calibre_highlight_json = {
        "start_cfi": start_cfi,
        "end_cfi": end_cfi,
        "highlighted_text": highlight.text,
        "spine_index": spine_index_map[highlight.content_path],
        "spine_name": highlight.content_path,
        "style": {
            "kind": "color",
            "type": "builtin",
            "which": kobo_color_to_calibre_color(highlight.color),
        },
        "toc_family_titles": [chapter_title],
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "highlight",
        "uuid": unique_uuid,
    }

    calibre_highlight = db.CalibreTargetHighlight(
        book_id,
        "EPUB",
        "local",
        "viewer",
        int(time.time()),
        unique_uuid,
        "highlight",
        calibre_highlight_json,
        highlight.text,
    )
    return calibre_highlight


def decode_calibre_cfi(
    soup: BeautifulSoup, cfi: str
) -> Tuple[bs4.element.NavigableString, int]:
    """Decode a Calibre CFI string using the same algorithm as Calibre's viewer.

    Returns the target NavigableString and its character offset.

    Calibre's CFI scheme (matching cfi.pyj decode/node_for_path_step):
    - Even step numbers select element children (index = step/2 - 1, 0-based)
    - Odd step numbers select text nodes (index = step//2, 0-based)
    - Final segment format: '<step>:<char_offset>'
    """
    parts = cfi.strip().split("/")
    if len(parts) < 2:
        raise ValueError("Invalid CFI string")

    current_node = soup.html
    # Process all intermediate segments (ignoring the final one)
    # We start from "2", because above we already set current_node to soup.html
    for part in parts[2:-1]:
        # Remove any square-bracket annotation (e.g. [id1])
        m = re.match(r"(\d+)", part)
        if not m:
            raise ValueError(f"Invalid segment in CFI: '{part}'")
        num = int(m.group(1))
        # Intermediate steps use even numbers for elements.
        # To invert: child_index = (num / 2) - 1
        child_index = (num // 2) - 1
        # Only consider Tag children (as in Calibre's algorithm)
        children = [
            child
            for child in current_node.children
            if isinstance(child, bs4.element.Tag)
        ]

        logger.debug(
            f"Processing segment '{part}': current_node={current_node.name}, "
            f"children_count={len(children)}, child_index={child_index}"
        )

        if child_index < 0 or child_index >= len(children):
            raise IndexError("Child index out of bounds while decoding CFI")
        current_node = children[child_index]

    # Process final segment using Calibre's interleaved indexing scheme.
    # This mirrors node_for_path_step in cfi.pyj:
    #   is_element = target % 2 == 0
    #   target //= 2
    #   if is_element and target > 0: target -= 1
    #   node_at_index(parent.childNodes, target, 0, not is_element)
    final_segment = parts[-1]
    m = re.match(r"(\d+):(\d+)", final_segment)
    if not m:
        raise ValueError("Invalid final segment in CFI: " + final_segment)
    step_num = int(m.group(1))
    offset = int(m.group(2))

    is_element_step = step_num % 2 == 0
    target_index = step_num // 2
    if is_element_step and target_index > 0:
        target_index -= 1

    # Find the node using Calibre's node_at_index logic
    matched_node = None
    node_index = 0
    for child in current_node.children:
        if isinstance(child, bs4.element.Comment):
            continue
        if is_element_step:
            # Looking for element nodes
            if not isinstance(child, bs4.element.Tag):
                continue
        else:
            # Looking for text nodes
            if not isinstance(child, bs4.element.NavigableString):
                continue
            if isinstance(child, bs4.element.Comment):
                continue
        if node_index == target_index:
            matched_node = child
            break
        node_index += 1

    if matched_node is None:
        raise IndexError(
            f"Step {step_num} not found among children of <{current_node.name}>"
        )

    # Apply Calibre's node_for_text_offset: walk children of the parent
    # starting from matched_node, consuming offset through text content.
    # In Calibre's cfi.pyj, only text nodes are processed; regular element
    # nodes (non-calibreRangeWrapper) are simply skipped. Since our documents
    # never contain calibreRangeWrapper elements, we skip all Tag children.
    seen_first = False
    for child in current_node.children:
        if not seen_first:
            if child is matched_node:
                seen_first = True
            else:
                continue
        if isinstance(child, bs4.element.Comment):
            continue
        if isinstance(child, bs4.element.NavigableString):
            text_len = len(str(child))
            if offset <= text_len:
                return child, offset
            offset -= text_len
        # Element nodes (Tags) are skipped — Calibre's node_for_text_offset
        # only recurses into calibreRangeWrapper elements, which don't exist
        # in our source documents.

    raise IndexError(
        f"Offset {offset} out of range after step {step_num} in <{current_node.name}>"
    )


def find_block_and_sentence_for_offset_new_format(
    raw_html: bytes,
    soup: BeautifulSoup,
    target_node: bs4.element.NavigableString,
    overall_offset: int,
) -> Optional[Tuple[int, int, int]]:
    """
    Find the kepubify block number and sentence for a target offset.

    This works by:
    1. Finding which block element contains the target node
    2. Calculating the character offset from the block start
    3. Using kepubify to find which sentence contains that offset

    Returns (block_num, sentence_num, offset_in_sentence) or None.
    """
    if not HAS_KEPUBIFY:
        return None

    # Find which block element contains the target node
    # Use identity comparison (is) rather than equality (in) because
    # multiple text nodes may have the same content (e.g., ".")
    block_num = 0
    containing_block = None
    for elem in soup.body.descendants:
        if isinstance(elem, bs4.element.Tag) and elem.name.lower() in BLOCK_TAGS:
            block_num += 1
            # Check if target_node is a descendant of this block using identity
            for desc in elem.descendants:
                if desc is target_node:
                    containing_block = elem
                    break
            if containing_block:
                break

    if containing_block is None:
        logger.warning("Could not find containing block for target node")
        return None

    # Calculate offset from block start to target position
    char_offset_in_block = 0
    for node in containing_block.descendants:
        if not isinstance(node, bs4.element.NavigableString):
            continue
        if isinstance(node, bs4.element.Comment):
            continue

        if node is target_node:
            char_offset_in_block += overall_offset
            break
        char_offset_in_block += len(str(node))

    # Convert original block number to kepubify block number using delta
    root = kepubify_html_data(raw_html, opts=KepubifyOptions())
    block_delta = get_kepubify_block_delta(root)
    kepub_block_num = block_num + block_delta

    # Now use kepubify to find which sentence contains this offset

    # Find all spans in this block
    cumulative_offset = 0
    for sent_num in range(1, 100):  # reasonable upper limit
        span_id = f"kobo.{kepub_block_num}.{sent_num}"
        spans = root.xpath(f'//*[@id="{span_id}"]')
        if not spans:
            break

        span_text = spans[0].text_content()
        span_len = len(span_text)

        # Use >= to handle end positions that point just past the last character
        if cumulative_offset + span_len >= char_offset_in_block:
            offset_in_sentence = char_offset_in_block - cumulative_offset
            return (kepub_block_num, sent_num, offset_in_sentence)

        cumulative_offset += span_len

    logger.warning(
        f"Could not find sentence for offset {char_offset_in_block} "
        f"in block {kepub_block_num}"
    )
    return None


def convert_calibre_cfi_to_kobo(
    soup: BeautifulSoup,
    cfi: str,
    raw_html: bytes = None,
    kepub_format: str = "old",
    is_end: bool = False,
) -> Tuple[str, int]:
    r"""Convert a Calibre CFI to a Kobo reader CFI.

    Args:
        soup: BeautifulSoup of the HTML document
        cfi: Calibre CFI string
        raw_html: Raw HTML bytes (required for new format)
        kepub_format: 'old' for KTE plugin format, 'new' for Calibre kepubify format

    Returns a tuple:
      (kobo_path, kobo_offset)
    where:
      kobo_path: a string of the form "span#kobo\.{n_tag}\.{n_sentence}"
      kobo_offset: the character offset within the given sentence.
    """
    # Decode the Calibre CFI first to obtain the target text node and overall offset
    target_node, overall_offset = decode_calibre_cfi(soup, cfi)

    use_new_format = is_new_kepub_format(kepub_format)

    if use_new_format and raw_html and HAS_KEPUBIFY:
        # Primary: kepubify round-trip (most accurate)
        result = calibre_cfi_to_kobo_span_via_roundtrip(
            raw_html, soup, target_node, overall_offset, is_end=is_end
        )
        if result is None:
            # Fallback: block-based counting
            logger.warning(
                "Round-trip conversion failed, falling back to block/sentence counting"
            )
            result = find_block_and_sentence_for_offset_new_format(
                raw_html, soup, target_node, overall_offset
            )
        if result:
            block_num, sentence_num, offset_in_sentence = result
            kobo_path = f"span#kobo\\.{block_num}\\.{sentence_num}"
            return kobo_path, offset_in_sentence
        else:
            logger.warning(
                "Failed to find block/sentence for new format, falling back to old"
            )

    # Old KTE format or fallback: count text nodes sequentially
    n_tag = 1
    found = False

    for child in soup.body.descendants:
        # Skip non-text nodes, comments, or nodes with only whitespace.
        if not isinstance(child, bs4.element.NavigableString) or isinstance(
            child, bs4.element.Comment
        ):
            continue
        text = str(child)
        if text in ("\n", " ", "\u00a0") or text.strip() == "":
            continue
        # Exclude nodes within a <figure>
        parent_names = [p.name for p in child.parents if isinstance(p, bs4.element.Tag)]
        if "figure" in parent_names:
            continue

        if child is target_node:
            found = True
            break
        n_tag += 1

    if not found:
        raise ValueError("Target text node not found among the valid text nodes")

    # Now, using the text content, split it into sentences.
    # Find which sentence the offset falls in.
    sentences = split_into_sentences(str(target_node))
    cumulative = 0
    kobo_sentence = 1
    kobo_offset = 0
    for sentence in sentences:
        if cumulative + len(sentence) >= overall_offset:
            kobo_offset = overall_offset - cumulative
            break
        cumulative += len(sentence)
        kobo_sentence += 1
    else:
        # In case the overall_offset is greater than the total length
        kobo_offset = overall_offset - cumulative

    # Construct the Kobo path.
    # The standard format is: "span#kobo\.{n_tag}\.{n_sentence}"
    kobo_path = f"span#kobo\\.{n_tag}\\.{kobo_sentence}"

    return kobo_path, kobo_offset


def guess_chapter_title(soup):
    """Guess the chapter title from the HTML soup."""
    # 2. Look for <h1> as it's common for chapter headings
    h1 = soup.find("h1")
    if h1 and h1.get_text():
        h1_text = h1.get_text().strip()
        if h1_text:
            return h1_text

    # 3. Look for <h2>, sometimes chapters are marked with h2
    h2 = soup.find("h2")
    if h2 and h2.get_text():
        h2_text = h2.get_text().strip()
        if h2_text:
            return h2_text

    # 4. As a fallback, try to see if there's a div with a class
    # indicating chapter title
    possible_titles = soup.find_all("div", class_="chapter-title")
    for div in possible_titles:
        text = div.get_text().strip()
        if text:
            return text

    # If no title is guessed, return a default notice
    return "Chapter title not found."
