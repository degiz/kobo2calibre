import spacy
from spacy.language import Language
import pytest
from sentence_tokenizer import tokenize_sentences


@Language.component("set_custom_boundaries")
def set_custom_boundaries(doc):
    """Somehow Kobo splits text here."""
    for token in doc[:-1]:
        if token.text == "e.g.":
            doc[token.i + 1].is_sent_start = True
    return doc


nlp = spacy.load("en_core_web_sm")
nlp.enable_pipe("senter")
nlp.add_pipe("set_custom_boundaries", before="parser")

text_1 = (
    "In the year 1878 I took my degree of Doctor of Medicine of the University of "
    "London, and proceeded to Netley to go through the course prescribed for "
    "surgeons in the army. Having completed my studies there, I was duly attached to "
    "the Fifth Northumberland Fusiliers as Assistant Surgeon. The regiment was "
    "stationed in India at the time, and before I could join it, the second Afghan "
    "war had broken out. On landing at Bombay, I learned that my corps had advanced "
    "through the passes, and was already deep in the enemy’s country. I followed, "
    "however, with many other officers who were in the same situation as myself, and "
    " succeeded in reaching Candahar in safety, where I found my regiment, and at "
    "once entered upon my new duties."
)
expected_tokenized_text_1 = []


text_2 = (
    "“Whatever have you been doing with yourself, Watson?” he asked in undisguised "
    "wonder, as we rattled through the crowded London streets. “You are as thin as a "
    "lath and as brown as a nut.”"
)

text_3 = "As stated above, e.g. is short for “for example.”"

text_4 = (
    "After work, I’m going to try the new restaurant (i.e., All About Pasta)"
    "to decide on a venue for the reception."
)

text_5 = (
    "“Oh! a mystery is it?” I cried, rubbing my hands. “This is very piquant. I am "
    "much obliged to you for bringing us together. ‘The proper study of mankind is "
    "man,’ you know.”"
)


def from_spacy(text: str):
    return [t.text_with_ws for t in nlp(str(text)).sents]


@pytest.mark.parametrize(
    "text",
    # [text_1, text_2, text_3, text_4, text_5],
    [text_5],
)
def test_tokenizer(text):
    print(from_spacy(text))
    print(tokenize_sentences(text))
    assert tokenize_sentences(text) == from_spacy(text)
