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
    "American", "English", "Spanish", "Mexican", "Italian", "French", "Chinese", "Covid",
}

# A capitalised word that follows lower-case text, a digit or a comma is probably a name.
_MID_SENTENCE_CAP = re.compile(r"(?<=[a-z0-9,;] )[A-Z][a-z]{2,}\b")


def load_records(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(data.get("records", [])) + list(data.get("undated_records", []))


def candidate_words(text: str) -> Iterator[tuple[str, int]]:
    for m in _MID_SENTENCE_CAP.finditer(text):
        if m.group(0) not in STOP_CAPS:
            yield m.group(0), m.start()


def scan_candidates(texts: list[str], context: int = 30) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    docs: defaultdict[str, set[int]] = defaultdict(set)
    sample: dict[str, str] = {}
    for i, text in enumerate(texts):
        for word, pos in candidate_words(text):
            counts[word] += 1
            docs[word].add(i)
            sample.setdefault(word, text[max(0, pos - context): pos + len(word) + context].replace("\n", " "))
    return [
        {"word": w, "count": n, "documents": len(docs[w]), "example": sample[w]}
        for w, n in counts.most_common()
    ]
