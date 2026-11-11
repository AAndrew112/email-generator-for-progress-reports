"""Helpers shared by the operator-run tools."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator

STOP_CAPS = {
    "Okay", "Yeah", "Yes", "Well", "Right", "Sure", "Anyway", "Also", "Because", "Then", "Maybe",
    "God", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "June", "July", "August", "September", "October",
    "November", "December", "Christmas", "Thanksgiving", "Easter", "Halloween", "Valentine",
    "Google", "Facebook", "Instagram", "Netflix", "Amazon", "Zoom", "Marco", "Polo", "Apple",
    "Mom", "Dad", "Mommy", "Daddy", "Grandma", "Grandpa", "Hey", "Hello", "Thanks", "Thank",
    "Jan", "Feb", "Mar", "Apr", "Aug", "Sept", "Oct", "Nov", "Dec", "Mon", "Tues", "Wed", "Thurs", "Fri", "Sat",
    "Sun", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays",
    "Hmm", "Mmm", "Ugh", "Wow", "Whoa", "Mhm", "Huh", "Ooh", "Aww", "Yay", "Yep", "Nope", "Alright",
    "Oops", "Gosh", "Geez", "Dude", "Girl", "Guys", "Please", "Sorry", "Anyways", "Honestly",
    "American", "English", "Spanish", "Mexican", "Italian", "French", "Chinese", "Covid",
}

CAP_WORD = re.compile(r"\b[A-Z][a-z]{2,}(?:[A-Z][a-z]+)*\b")
LOW_WORD = re.compile(r"\b[a-z]{3,}\b")
# Capitalisation in the middle of a sentence (after a lower-case word, digit or comma) is the clearest sign
# of a name: ordinary words only get a capital at the start of a sentence.
MID_CAP = re.compile(r"(?<=[a-z0-9,;:] )[A-Z][a-z]{2,}(?:[A-Z][a-z]+)*\b")
MID_LOW = re.compile(r"(?<=[a-z0-9,;:] )[a-z]{3,}\b")


def is_name_like(word: str, cap: Counter, low: Counter, mid_cap: Counter, mid_low: Counter) -> bool:
    """Name if it is (almost) never lower case, or is capitalised mid-sentence at least 30% of the time.

    The second rule catches names the recogniser writes in lower case a third of the time, which the
    first rule misses. Case-sensitive replacement then only touches the capitalised form.
    """
    if low[word.lower()] <= 0.25 * cap[word]:
        return True
    m = mid_cap[word]
    return m >= 3 and m / (m + mid_low[word.lower()]) >= 0.3

# A capitalised word that follows lower-case text, a digit or a comma is probably a name.
_MID_SENTENCE_CAP = re.compile(r"(?<=[a-z0-9,;] )[A-Z][a-z]{2,}\b")


def load_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(data.get("records", [])) + list(data.get("undated_records", []))


def candidate_words(text: str) -> Iterator[tuple[str, int]]:
    for m in _MID_SENTENCE_CAP.finditer(text):
        if m.group(0) not in STOP_CAPS:
            yield m.group(0), m.start()


def scan_candidates(texts: list[str], context: int = 30, ratio: float = 0.0) -> list[dict[str, Any]]:
    """Capitalised words in mid-sentence. With ``ratio`` > 0, keep only words that are capitalised
    at least that share of the time (names that are also ordinary words, like Will or Rose), which
    drops ordinary words that merely got a capital letter (Today, Anyway).
    """
    counts: Counter[str] = Counter()
    low: Counter[str] = Counter()
    docs: defaultdict[str, set[int]] = defaultdict(set)
    sample: dict[str, str] = {}
    for i, text in enumerate(texts):
        if ratio:
            low.update(LOW_WORD.findall(text))
        for word, pos in candidate_words(text):
            counts[word] += 1
            docs[word].add(i)
            sample.setdefault(word, text[max(0, pos - context): pos + len(word) + context].replace("\n", " "))
    return [
        {"word": w, "count": n, "documents": len(docs[w]), "example": sample[w]}
        for w, n in counts.most_common()
        if not ratio or n / (n + low[w.lower()]) >= ratio
    ]


def rank_name_like(texts: list[str], context: int = 30) -> list[dict[str, Any]]:
    """Capitalised words that are (almost) never written in lower case, most frequent first.

    This is the same rule the pseudonymizer uses for its automatic catch-all, so the list shows
    what would otherwise be replaced by a plain NAME_#### token.
    """
    cap: Counter[str] = Counter()
    low: Counter[str] = Counter()
    mid_cap: Counter[str] = Counter()
    mid_low: Counter[str] = Counter()
    docs: defaultdict[str, set[int]] = defaultdict(set)
    sample: dict[str, str] = {}
    for i, text in enumerate(texts):
        low.update(LOW_WORD.findall(text))
        mid_cap.update(MID_CAP.findall(text))
        mid_low.update(MID_LOW.findall(text))
        for m in CAP_WORD.finditer(text):
            w = m.group(0)
            cap[w] += 1
            docs[w].add(i)
            sample.setdefault(w, text[max(0, m.start() - context): m.end() + context].replace("\n", " "))
    return [{"word": w, "count": n, "documents": len(docs[w]), "example": sample[w]}
            for w, n in cap.most_common() if w not in STOP_CAPS and is_name_like(w, cap, low, mid_cap, mid_low)]
