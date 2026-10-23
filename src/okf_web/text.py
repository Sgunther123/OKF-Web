"""Tokenization shared by the lexical retriever and the hashing embedder.

One tokenizer, one place: retrieval quality is only as good as the
words it sees, and until this module the words were ``[a-z0-9]+`` over
lowercased text — which shreds every accented word ("devolución" became
two fragments) and yields nothing at all for Cyrillic, Greek or CJK
text (GAPS item 1). Here a word is a run of letters and digits in any
script, taken from case-folded, accent-stripped text, so a shopper's
"devolucion" and a merchant's "devolución" are the same token.

ASCII text tokenizes exactly as before: the fast path below is the old
regex over ``str.lower()``, so English bundles keep their rankings and
their measured numbers.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "fold",
    "words",
]

_WORD_RE = re.compile(r"[^\W_]+")  # letters and digits, any script; never `_`
_ASCII_WORD_RE = re.compile(r"[a-z0-9]+")
# Scripts written without spaces: a run of these is one "word" to the
# regex, so it is split into character bigrams (the dictionary-free
# convention for CJK retrieval) — "配送" then matches inside "配送について".
_CJK_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]"
)


def fold(text: str) -> str:
    """Case-folded text with accents removed: NFKD decomposition, then
    every combining mark dropped, then ``str.casefold``."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _split_cjk(token: str) -> list[str]:
    if not _CJK_RE.search(token):
        return [token]
    if len(token) < 2:
        return [token]
    return [token[i : i + 2] for i in range(len(token) - 1)]


def words(text: str) -> list[str]:
    """The tokens of ``text``: letters-and-digits runs of the folded text,
    CJK runs as character bigrams."""
    if text.isascii():
        return _ASCII_WORD_RE.findall(text.lower())
    out: list[str] = []
    for token in _WORD_RE.findall(fold(text)):
        out.extend(_split_cjk(token))
    return out
