"""Porter stemming algorithm, pure Python implementation.

Reference: Porter, M. (1980). "An algorithm for suffix stripping." Program.

Zero dependencies. Roughly 130 lines. Used by ``bm25.tokenize`` so that
morphological variants ("diffusion", "diffusing", "diffused") collapse to a
single token ("diffus") and become matchable.

The public API is :func:`stem` and :func:`stem_tokens`.
"""

from __future__ import annotations

_VOWELS = frozenset("aeiou")


def _is_consonant(word: str, i: int) -> bool:
    ch = word[i]
    if ch in _VOWELS:
        return False
    if ch == "y":
        if i == 0:
            return True
        return not _is_consonant(word, i - 1)
    return True


def _measure(stem: str) -> int:
    """Porter's m: number of VC sequences after optional initial C*."""
    if not stem:
        return 0
    i = 0
    while i < len(stem) and _is_consonant(stem, i):
        i += 1
    m = 0
    while i < len(stem):
        while i < len(stem) and not _is_consonant(stem, i):
            i += 1
        while i < len(stem) and _is_consonant(stem, i):
            i += 1
        m += 1
    return m


def _has_vowel(stem: str) -> bool:
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(stem: str) -> bool:
    if len(stem) < 2 or stem[-1] != stem[-2]:
        return False
    return _is_consonant(stem, len(stem) - 1)


def _ends_cvc(stem: str) -> bool:
    """Word ends in consonant-vowel-consonant, last not in {w, x, y}."""
    if len(stem) < 3:
        return False
    if not _is_consonant(stem, len(stem) - 3):
        return False
    if _is_consonant(stem, len(stem) - 2):
        return False
    if not _is_consonant(stem, len(stem) - 1):
        return False
    return stem[-1] not in "wxy"


_STEP2: list[tuple[str, str]] = [
    ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"),
    ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"),
    ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
    ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"),
    ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
]

_STEP3: list[tuple[str, str]] = [
    ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"),
    ("ical", "ic"), ("ful", ""), ("ness", ""),
]

_STEP4: tuple[str, ...] = (
    "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement",
    "ment", "ent", "ou", "ism", "ate", "iti", "ous", "ive", "ize",
)


def stem(word: str) -> str:
    """Return the Porter stem of *word*."""
    word = word.lower()
    if len(word) <= 2:
        return word

    # Step 1a
    if word.endswith("sses") or word.endswith("ies"):
        word = word[:-2]
    elif word.endswith("ss"):
        pass
    elif word.endswith("s"):
        word = word[:-1]

    # Step 1b
    flag_1b = False
    if word.endswith("eed"):
        if _measure(word[:-3]) > 0:
            word = word[:-1]
    elif word.endswith("ed") and _has_vowel(word[:-2]):
        word = word[:-2]
        flag_1b = True
    elif word.endswith("ing") and _has_vowel(word[:-3]):
        word = word[:-3]
        flag_1b = True

    if flag_1b:
        if word.endswith(("at", "bl", "iz")):
            word += "e"
        elif _ends_double_consonant(word) and word[-1] not in "lsz":
            word = word[:-1]
        elif _measure(word) == 1 and _ends_cvc(word):
            word += "e"

    # Step 1c
    if word.endswith("y") and len(word) > 1 and _has_vowel(word[:-1]):
        word = word[:-1] + "i"

    # Step 2
    for suffix, replacement in _STEP2:
        if word.endswith(suffix):
            base = word[: -len(suffix)]
            if _measure(base) > 0:
                word = base + replacement
            break

    # Step 3
    for suffix, replacement in _STEP3:
        if word.endswith(suffix):
            base = word[: -len(suffix)]
            if _measure(base) > 0:
                word = base + replacement
            break

    # Step 4
    matched = False
    for suffix in _STEP4:
        if word.endswith(suffix):
            base = word[: -len(suffix)]
            if _measure(base) > 1:
                word = base
            matched = True
            break
    if not matched and word.endswith("ion"):
        base = word[:-3]
        if _measure(base) > 1 and base and base[-1] in "st":
            word = base

    # Step 5a
    if word.endswith("e"):
        base = word[:-1]
        m = _measure(base)
        if m > 1 or (m == 1 and not _ends_cvc(base)):
            word = base

    # Step 5b
    if _measure(word) > 1 and word.endswith("l") and _ends_double_consonant(word):
        word = word[:-1]

    return word


def stem_tokens(words: list[str]) -> list[str]:
    """Stem a list of tokens."""
    return [stem(w) for w in words]
