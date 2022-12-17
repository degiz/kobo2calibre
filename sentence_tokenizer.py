from typing import List
import re

# This regex is inspired by https://bit.ly/3HqIzoP
REGEX_EPUB = re.compile(
    r"""
    [^.!?\s] [^.!?]* # beginning of sentence, ignoring new lines
    (?:[.!?](?!['\"”]?\s|$)[^?]*)* # the sentence itself
    [.!?]?['\"”\s]?[\s]? # end of sentence
    """,
    re.VERBOSE,
)

# A regex that will most likely work on books converted with KTE plugin
REGEX_KTE = re.compile(
    r'(\s*.*?[\.\!\?\:][\'"\u201c\u201d\u2018\u2019\u2026]?\s*)',
    re.UNICODE | re.MULTILINE,
)


# def tokenize_sentences(text: str) -> List[str]:
#     """Tokenize a string of text into sentences."""

#     regex_result = re.findall(REGEX_KEPUBIFY, text)
#     return regex_result


def tokenize_epub_sentences(text: str) -> List[str]:
    """Tokenize a string of text into sentences in EPUB format."""

    regex_result = re.findall(REGEX_EPUB, text)

    # merge adjacent sentences between quotes, to repeat what Spacy does
    result = []
    i = 0
    while i < len(regex_result) - 1:
        if regex_result[i].startswith("“") and (
            regex_result[i + 1].endswith("”") or regex_result[i + 1].endswith("” ")
        ):
            result.append(regex_result[i] + regex_result[i + 1])
            i += 2
        else:
            result.append(regex_result[i])
            i += 1
    if i < len(regex_result):
        result.append(regex_result[i])

    return result
