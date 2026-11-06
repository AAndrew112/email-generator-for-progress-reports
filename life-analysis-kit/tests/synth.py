"""Synthetic stand-in for an archive.json export. Contains no real data.

Plants known names, identifiers and a topic shift (work talk in 2019, family talk in 2020)
so the tests can check pseudonymization and era detection.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SUBJECT = "Dana Whitfield"
PLANTED = {
    "Dana": "subject first name", "Whitfield": "subject surname",
    "Priya": "friend", "Natarajan": "friend surname", "Pria": "friend misspelling",
    "Marcus": "partner", "Oyelaran": "partner surname", "Theo": "child",
    "Brightwater": "workplace", "Lincoln Middle": "school", "Duluth": "city",
    "dana.w@example.com": "email", "867-5309": "phone", "example.com/dana": "url",
    "@dana_w": "handle", "42 Maple Street": "address",
    "Bronwyn": "unlisted friend, mid-sentence", "Odessa": "unlisted full name", "Brandt": "its surname", "Odesa": "its misspelling", "Sarah": "look-alike 1", "Sara": "look-alike 2", "Zelda": "unlisted friend, sentence start only",
}
NAMES_CSV = """name,category,token,aliases,case_sensitive
Dana Whitfield,SUBJECT,SUBJECT,Dana;Whitfield,
Priya Natarajan,PERSON,,Priya;Pria,
Marcus Oyelaran,PARTNER,PARTNER,Marcus,
Theo,CHILD,CHILD_1,,
Brightwater Analytics,WORKPLACE,,Brightwater,
Lincoln Middle School,SCHOOL,,Lincoln Middle,
Duluth,CITY,,,
Hope,PERSON,,,yes
"""

WORK_WORDS = "deadline project meeting manager budget client spreadsheet presentation promotion schedule".split()
FAMILY_WORDS = "baby nursery diapers sleep feeding stroller bedtime crying cuddles nap".split()
TEEN_WORDS = "homework locker crush gym teacher lunch quiz yearbook friends gossip".split()
FILL = "so anyway i was thinking that it is what it is and honestly we should just see how it goes".split()


def sentence(rng: random.Random, topic: list[str], n: int = 9) -> str:
    ws = [rng.choice(topic) if rng.random() < 0.45 else rng.choice(FILL) for _ in range(n)]
    return " ".join(ws).capitalize() + "."


def make_records(seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    recs, n = [], 0

    def add(kind: str, date: str | None, text: str, precision_conf: str = "exact") -> None:
        nonlocal n
        n += 1
        is_j = kind == "journal"
        recs.append({
            "record_id": f"{'jr' if is_j else 'mp'}-{n:05d}", "source_type": kind, "date": date,
            "time": None if is_j else f"{rng.randint(7, 22):02d}:{rng.randint(0, 59):02d}:00",
            "timezone": None if is_j else "-08:00", "timestamp_confidence": precision_conf if date else "unknown",
            "transcript": text, "source_filename": "Dana trip to Duluth.pdf" if is_j else f"2019-01-01_00-00-00_PST_dana_w_{n}.mp4",
            "source_location": f"/Users/dana.whitfield/Journals/{n}.pdf", "page_number": 1 if is_j else None,
            "duration": None if is_j else 60.0, "speaker_verification": None,
            "transcription_status": "machine", "review_required": False,
            "metadata": {"transcript_detail": {"segments": [{"avg_logprob": -0.3}] * 4, "uncertain_segments": [{}] if n % 7 == 0 else []}},
        })

    for year, topic, length in ((2019, WORK_WORDS, 2), (2020, FAMILY_WORDS, 6)):
        for month in range(1, 13):
            for k in range(6):
                text = " ".join(sentence(rng, topic) for _ in range(length))
                if (year, month, k) == (2019, 3, 0):
                    text += (" Hi it's Dana. I told Priya Natarajan to email me at dana.w@example.com or call (612) 867-5309. "
                             "Marcus said see https://example.com/dana or @dana_w. We live at 42 Maple Street. "
                             "Pria and Theo came to Brightwater in Duluth. I hope Hope is fine. Then Bronwyn laughed at Lincoln Middle. Zelda came over later. Odessa Brandt visited. Odessa Brandt left. Then Odessa called. Odesa texted. Sara called. Sara left. Sara won. Sara sang. Sarah called. Sarah left. Sarah won. Sarah sang.")
                add("marco_polo", f"{year}-{month:02d}-{rng.randint(1, 28):02d}", text)
    for month in range(1, 7):
        for _ in range(3):
            add("journal", f"2005-{month:02d}-{rng.randint(1, 28):02d}", " ".join(sentence(rng, TEEN_WORDS) for _ in range(3)))
    add("journal", "2005-03", "A month-level entry. " + sentence(rng, TEEN_WORDS), "inferred")
    add("journal", "2005", "A year-level entry. " + sentence(rng, TEEN_WORDS), "inferred")
    add("journal", None, "No date here. " + sentence(rng, TEEN_WORDS), "unknown")
    add("marco_polo", "2019-06-15", " ".join("word" for _ in range(2600)))   # one long message to split
    add("marco_polo", "2019-06-16", "   ")                                    # empty -> skipped
    return recs


def write_archive(path: Path) -> None:
    recs = make_records()
    dated = [r for r in recs if r["date"]]
    undated = [r for r in recs if not r["date"]]
    path.write_text(json.dumps({"records": dated, "undated_records": undated}), encoding="utf-8")
