from typing import List
import re


def tokenize_sentences(text: str) -> List[str]:
    """Tokenize a string of text into sentences."""

    # Original regex from https://bit.ly/3HqIzoP
    regex = re.compile(
        r"""
        [^.!?\s] [^.!?\n]* # beginning of sentence
        (?:[.!?](?!['\"”]?\s|$)[^.!?]*)* # the sentence itself
        [.!?]?['\"”\s]?[\s]? # end of sentence
        """,
        re.VERBOSE,
    )
    regex_result = re.findall(regex, text)

    # merge adjacent sentences between quotes
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
