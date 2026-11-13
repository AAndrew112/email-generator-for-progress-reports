#!/usr/bin/env python3
"""OPERATOR-RUN ONLY. The analysis assistant must never run or read this tool's inputs.

Reads  raw/archive.json (export from the archive pipeline) and private/names_input.csv
Writes work/docs_pseudo.jsonl            pseudonymized documents (what the assistant may read)
       work/pseudonymization_report.json counts only; no names
       private/key.json                  token -> real strings (used by rehydrate.py)
       private/residual_candidates.csv   capitalised words that are still in the text

What it does, in order, per document:
  1. redacts emails, phone numbers, URLs, @handles, street addresses, long ID numbers
  2. replaces every name, alias, workplace, school and place from names_input.csv
  3. catches the rest automatically: every capitalised word that is almost never written in lower
     case anywhere in the corpus is treated as a name (token NAME_####). This covers the long tail
     (classmates, teachers, one-off people) so you only list the people who matter. Spelling variants
     and first+last names are grouped under one token; private/auto_groups.csv shows each group. Words you
     want left alone go in private/not_names.txt, one per line. Use --no-auto to turn this off.
  4. optionally (--ner) replaces extra names/places found by spaCy, if installed
Source file names and paths are never copied: only a pseudonymized title for journals.

Everything is local. Nothing is sent over the network.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    CAP_WORD, LOW_WORD, MID_CAP, MID_LOW, STOP_CAPS, is_name_like, load_dictionary, load_records,
    scan_candidates,
)

TRUTHY = {"yes", "y", "true", "1"}
REDACTIONS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("URL", re.compile(r"(?:https?://|www\.)\S+")),
    ("HANDLE", re.compile(r"(?<![\w@])@[A-Za-z0-9_.]{2,}")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")),
    ("ADDRESS", re.compile(
        r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|"
        r"Drive|Dr|Court|Ct|Way|Place|Pl|Terrace|Circle)\b\.?")),
    ("ID_NUM", re.compile(r"(?<!\d)(?:\d{3}-\d{2}-\d{4}|\d{9,})(?!\d)")),
]
NER_LABELS = {"PERSON": "PERSON_NER", "GPE": "PLACE_NER", "LOC": "PLACE_NER", "FAC": "PLACE_NER",
              "ORG": "ORG_NER"}


class Pseudonymizer:
    def __init__(self, names_csv: Path | None, ner: bool = False) -> None:
        self.key: dict[str, Counter[str]] = defaultdict(Counter)
        self.hits: Counter[str] = Counter()
        self.redaction_ids: dict[str, dict[str, str]] = defaultdict(dict)
        self.ner_ids: dict[str, str] = {}
        self.entries: list[tuple[str, str, bool]] = []
        self.tokens_declared: list[str] = []
        self.regex_aliases: list[tuple[re.Pattern[str], str]] = []
        if names_csv is not None:
            self._load_names(names_csv)
        norm = lambda x: re.sub(r"\s+", " ", x)  # noqa: E731
        ci = {norm(s).lower(): t for s, t, cs in self.entries if not cs}
        cs_map = {norm(s): t for s, t, cs in self.entries if cs}
        self._ci_map, self._cs_map = ci, cs_map
        self._ci_re = self._build(ci.keys(), re.I)
        self._cs_re = self._build(cs_map.keys(), 0)
        self.nlp = None
        self.recording = True
        self.auto_re: re.Pattern[str] | None = None
        self.auto_ids: dict[str, str] = {}
        self.auto_groups: list[tuple[str, list[str], int]] = []
        self.auto_ci_ids: dict[str, str] = {}
        self.auto_ci_re: re.Pattern[str] | None = None
        self.lowercase_words = 0
        self.dictionary_used = False
        self.not_names: set[str] = set()
        if ner:
            try:
                import spacy

                self.nlp = spacy.load("en_core_web_sm")
            except Exception as exc:  # noqa: BLE001
                print(f"NER unavailable ({exc}); continuing without it.", file=sys.stderr)

    @staticmethod
    def _build(keys: Any, flags: int) -> re.Pattern[str] | None:
        keys = sorted(keys, key=len, reverse=True)
        if not keys:
            return None
        alt = "|".join(re.escape(k).replace(r"\ ", r"\s+") for k in keys)
        # "Don" must not match inside "don't": an apostrophe + t is a contraction, not a name ending.
        return re.compile(rf"(?<![A-Za-z0-9_])(?:{alt})(?![A-Za-z0-9_]|['\u2019]t\b)", flags)

    def _load_names(self, path: Path) -> None:
        counters: Counter[str] = Counter()
        claimed: dict[str, str] = {}
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("name") or "").strip()
                if not name or name.startswith("#"):
                    continue
                cat = (row.get("category") or "PERSON").strip().upper()
                token = (row.get("token") or "").strip().upper().strip("[]")
                if not token:
                    if cat == "SUBJECT":
                        token = "SUBJECT"
                    else:
                        counters[cat] += 1
                        token = f"{cat}_{counters[cat]:0{3 if cat == 'PERSON' else 2}d}"
                cs = (row.get("case_sensitive") or "").strip().lower() in TRUTHY
                surfaces = [name] + [a.strip() for a in (row.get("aliases") or "").split(";") if a.strip()]
                for s in surfaces:
                    if s.lower().startswith("re:"):  # a pattern covering a family of spellings
                        try:
                            rx = re.compile(rf"(?<![A-Za-z0-9_\[])(?:{s[3:].strip()})(?![A-Za-z0-9_\]])", re.I)
                        except re.error as exc:
                            raise SystemExit(f"Bad pattern '{s}' for {name}: {exc}") from exc
                        self.regex_aliases.append((rx, token))
                        continue
                    k = s if cs else s.lower()
                    if claimed.get(k, token) != token:
                        raise SystemExit(f"'{s}' is listed for two different tokens; fix names_input.csv")
                    claimed[k] = token
                    self.entries.append((s, token, cs))
                if token not in self.tokens_declared:
                    self.tokens_declared.append(token)

    def _hit(self, tok: str, real: str) -> None:
        if self.recording:
            self.key[tok][real] += 1
            self.hits[tok] += 1

    # --- replacement steps -------------------------------------------------
    def _redact(self, text: str) -> str:
        for kind, rx in REDACTIONS:
            def sub(m: re.Match[str], kind: str = kind) -> str:
                ids = self.redaction_ids[kind]
                tok = ids.setdefault(m.group(0), f"{kind}_{len(ids) + 1:02d}")
                self._hit(tok, m.group(0))
                return f"[{tok}]"

            text = rx.sub(sub, text)
        return text

    def _names(self, text: str) -> str:
        def replacer(table: dict[str, str], fold: bool):
            def sub(m: re.Match[str]) -> str:
                flat = re.sub(r"\s+", " ", m.group(0))
                tok = table[flat.lower() if fold else flat]
                self._hit(tok, flat)
                return f"[{tok}]"

            return sub

        if self._cs_re:
            text = self._cs_re.sub(replacer(self._cs_map, False), text)
        if self._ci_re:
            text = self._ci_re.sub(replacer(self._ci_map, True), text)
        for rx, tok in self.regex_aliases:
            text = rx.sub(lambda m, tok=tok: (self._hit(tok, m.group(0)), f"[{tok}]")[1], text)
        return text

    def _ner(self, text: str) -> str:
        if self.nlp is None:
            return text
        out, last = [], 0
        for ent in self.nlp(text).ents:
            if ent.label_ not in NER_LABELS or "[" in ent.text or "]" in ent.text:
                continue
            prefix = NER_LABELS[ent.label_]
            tok = self.ner_ids.setdefault(f"{prefix}|{ent.text}", f"{prefix}_{len(self.ner_ids) + 1:03d}")
            self._hit(tok, ent.text)
            out += [text[last:ent.start_char], f"[{tok}]"]
            last = ent.end_char
        return "".join(out) + text[last:]

    def base(self, text: str) -> str:
        return self._ner(self._names(self._redact(text)))

    def learn_auto_names(self, texts: list[str], not_names: set[str]) -> int:
        """Find name-like words in the whole corpus: capitalised words that are (almost) never written
        in lower case, or that are capitalised in the middle of sentences at least 30% of the time
        (speech recognition capitalises names inconsistently). Ordinary words (So, Like, Maybe) only
        get a capital at the start of a sentence.
        """
        self.not_names = not_names
        self.recording = False
        base = [self.base(t) for t in texts]
        self.recording = True
        cap: Counter[str] = Counter()
        low: Counter[str] = Counter()
        mid_cap: Counter[str] = Counter()
        mid_low: Counter[str] = Counter()
        for t in base:
            cap.update(CAP_WORD.findall(t))
            low.update(LOW_WORD.findall(t))
            mid_cap.update(MID_CAP.findall(t))
            mid_low.update(MID_LOW.findall(t))
        names = [w for w in cap if w not in STOP_CAPS and w not in not_names
                 and is_name_like(w, cap, low, mid_cap, mid_low)]
        dictionary = load_dictionary()
        self.dictionary_used = bool(dictionary)
        lower_forms: list[str] = []
        if dictionary:
            # Words that are not ordinary English words and are capitalised mid-sentence at least once are names
            # (or brands, or slang). The recogniser also writes them in lower case, so replace every case.
            have = set(names)
            lower_forms = [w for w in cap if w not in have and w not in STOP_CAPS and w not in not_names
                           and w.lower() not in dictionary and mid_cap[w] >= 1 and low[w.lower()] <= 50 * mid_cap[w]]
            names += lower_forms
        self.lowercase_words = len(lower_forms)
        self.auto_groups = self._group(names, cap, base)
        self.auto_ids = {w: tok for tok, members, _ in self.auto_groups for w in members}
        self.auto_ci_ids = {w.lower(): self.auto_ids[w] for w in lower_forms}
        if lower_forms:
            alt_ci = "|".join(re.escape(w.lower()) for w in sorted(lower_forms, key=len, reverse=True))
            self.auto_ci_re = re.compile(rf"(?<![A-Za-z0-9_\[])(?:{alt_ci})(?![A-Za-z0-9_\]])", re.I)
        names = list(self.auto_ids)
        if names:
            alt = "|".join(re.escape(w) for w in sorted(names, key=len, reverse=True))
            self.auto_re = re.compile(rf"(?<![A-Za-z0-9_\[])(?:{alt})(?![A-Za-z0-9_\]])")
        return len(self.auto_groups)

    @staticmethod
    def _group(names: list[str], cap: Counter[str], base: list[str]) -> list[tuple[str, list[str], int]]:
        """Group words that are probably the same person or place under one token.

        Two conservative rules: (1) two name words written side by side at least twice ("Jane Smith")
        belong together; (2) a rare variant spelling (misrecognition such as Pria for Priya) joins
        the frequent word it resembles. Two frequent look-alikes (Sara, Sarah) stay separate.
        """
        parent = {w: w for w in names}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb, key=lambda w: (-cap[w], w))] = min(ra, rb, key=lambda w: (-cap[w], w))

        known = set(names)
        pairs: Counter[tuple[str, str]] = Counter()
        pair_rx = re.compile(r"(?<![A-Za-z0-9_\[])([A-Z][a-z]{2,}) ([A-Z][a-z]{2,})(?![A-Za-z0-9_\]])")
        for t in base:
            for a, b in pair_rx.findall(t):
                if a in known and b in known:
                    pairs[(a, b)] += 1
        for (a, b), n in sorted(pairs.items()):
            if n >= 2:
                union(a, b)
        by_letter: dict[str, list[str]] = defaultdict(list)
        for w in sorted(names, key=lambda w: (-cap[w], w)):
            by_letter[w[0]].append(w)
        for words in by_letter.values():
            for i, big in enumerate(words):
                for small in words[i + 1:]:
                    if (len(big) >= 4 and len(small) >= 4 and abs(len(big) - len(small)) <= 2
                            and cap[small] <= max(3, 0.2 * cap[big])
                            and difflib.SequenceMatcher(None, big.lower(), small.lower()).ratio() >= 0.86):
                        union(small, big)
        groups: dict[str, list[str]] = defaultdict(list)
        for w in names:
            groups[find(w)].append(w)
        ordered = sorted(groups.values(), key=lambda g: (-sum(cap[w] for w in g), min(g)))
        return [(f"NAME_{i:04d}", sorted(g, key=lambda w: (-cap[w], w)), sum(cap[w] for w in g))
                for i, g in enumerate(ordered, 1)]

    def _auto(self, text: str) -> str:
        def sub(m: re.Match[str]) -> str:
            tok = self.auto_ids[m.group(0)]
            self._hit(tok, m.group(0))
            return f"[{tok}]"

        def sub_ci(m: re.Match[str]) -> str:
            tok = self.auto_ci_ids[m.group(0).lower()]
            self._hit(tok, m.group(0))
            return f"[{tok}]"

        if self.auto_re is not None:
            text = self.auto_re.sub(sub, text)
        if self.auto_ci_re is not None:
            text = self.auto_ci_re.sub(sub_ci, text)
        return text

    def __call__(self, text: str) -> str:
        return self._auto(self.base(text))


def quality_of(rec: dict[str, Any]) -> dict[str, Any]:
    text = rec.get("transcript") or ""
    detail = (rec.get("metadata") or {}).get("transcript_detail") or {}
    segments = detail.get("segments") or []
    uncertain = detail.get("uncertain_segments") or []
    return {
        "transcription_status": rec.get("transcription_status"),
        "illegible_markers": len(re.findall(r"\[illegible", text)),
        "uncertain_markers": len(re.findall(r"\[\?[^\]]*\?\]", text)),
        "low_confidence_fraction": round(len(uncertain) / len(segments), 3) if segments else None,
        "review_required": bool(rec.get("review_required")),
    }


def build_docs(records: list[dict[str, Any]], pz: Pseudonymizer) -> tuple[list[dict[str, Any]], int]:
    docs, empty = [], 0
    for rec in sorted(records, key=lambda r: (r.get("date") or "9999", r.get("time") or "", r["record_id"])):
        text = (rec.get("transcript") or "").strip()
        if not text:
            empty += 1
            continue
        is_journal = rec.get("source_type") == "journal"
        date = rec.get("date")
        docs.append({
            "doc_id": "D-" + hashlib.sha1(rec["record_id"].encode()).hexdigest()[:10],
            "kind": "journal" if is_journal else "chat",
            "date": date,
            "date_precision": {10: "day", 7: "month", 4: "year"}.get(len(date or ""), None),
            "time": rec.get("time"),
            "timezone": rec.get("timezone"),
            "date_confidence": rec.get("timestamp_confidence"),
            "duration_s": rec.get("duration"),
            "page": rec.get("page_number"),
            "source_label": pz(Path(rec.get("source_filename") or "").stem) if is_journal else None,
            "quality": quality_of(rec),
            "text": pz(text),
        })
    return docs, empty


def main() -> None:
    root_default = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=root_default)
    ap.add_argument("--input", type=Path, help="default: <root>/raw/archive.json")
    ap.add_argument("--ner", action="store_true", help="also use spaCy NER if installed")
    ap.add_argument("--no-auto", action="store_true",
                    help="only replace names listed in names_input.csv (no automatic catch-all)")
    ap.add_argument("--allow-no-names", action="store_true", help="testing only")
    args = ap.parse_args()
    root: Path = args.root
    names_csv = root / "private" / "names_input.csv"
    if not names_csv.exists():
        if not args.allow_no_names:
            sys.exit(f"Create {names_csv} first (run tools/suggest_names.py, mark the sheet, then tools/build_names.py).")
        names_csv = None  # type: ignore[assignment]

    pz = Pseudonymizer(names_csv, ner=args.ner)
    records = load_records(args.input or root / "raw" / "archive.json")
    auto_words = 0
    protect = root / "private" / "not_names.txt"
    keep = {w.strip() for w in protect.read_text(encoding="utf-8").splitlines() if w.strip()} if protect.exists() else set()
    if not args.no_auto:
        texts = [(r.get("transcript") or "") for r in records]
        texts += [Path(r.get("source_filename") or "").stem for r in records if r.get("source_type") == "journal"]
        auto_words = pz.learn_auto_names(texts, keep)
    docs, empty = build_docs(records, pz)

    work, private = root / "work", root / "private"
    work.mkdir(exist_ok=True)
    private.mkdir(exist_ok=True)
    with open(work / "docs_pseudo.jsonl", "w", encoding="utf-8") as fh:
        for d in docs:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")

    # Words the operator chose to leave readable (topics, brands, apps, media). They are not people or places and are
    # already visible in the text, so the assistant gets the list to avoid counting them as pseudonymization misses.
    (work / "keep_visible.txt").write_text("".join(w + "\n" for w in sorted(keep)), encoding="utf-8")
    residual = scan_candidates([d["text"] for d in docs], ratio=0.3)
    with open(private / "residual_candidates.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["word", "count", "documents", "example"], lineterminator="\n")
        w.writeheader()
        w.writerows(residual)
    with open(private / "auto_groups.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["token", "occurrences", "words_grouped_together"])
        for tok, members, total in pz.auto_groups:
            w.writerow([tok, total, "; ".join(members)])
    with open(private / "key.json", "w", encoding="utf-8") as fh:
        json.dump({t: dict(c) for t, c in pz.key.items()}, fh, ensure_ascii=False, indent=1)

    n_words = sum(len(d["text"].split()) for d in docs) or 1
    by_cat: Counter[str] = Counter()
    for tok, n in pz.hits.items():
        by_cat[re.sub(r"_?\d+$", "", tok)] += n
    report = {
        "documents": len(docs),
        "empty_documents_skipped": empty,
        "words": n_words,
        "replacements_by_category": dict(sorted(by_cat.items())),
        "tokens_declared": len(pz.tokens_declared),
        "tokens_never_matched": sorted(t for t in pz.tokens_declared if pz.hits[t] == 0),
        "tokens_matching_over_5_per_1000_words": sorted(
            t for t, n in pz.hits.items() if t in pz.tokens_declared and n / n_words * 1000 > 5),
        "residual_capitalised_words": len(residual),
        "residual_occurrences": sum(r["count"] for r in residual),
        "ner_used": pz.nlp is not None,
        "automatic_catch_all": not args.no_auto,
        "auto_name_groups": auto_words,
        "keep_visible_words": len(keep),
        "dictionary_used": pz.dictionary_used,
        "auto_lowercase_name_words": pz.lowercase_words,
        "pattern_aliases": len(pz.regex_aliases),
    }
    (work / "pseudonymization_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nNext: open {private / 'residual_candidates.csv'}. Any real name there means add it to "
          "names_input.csv (append at the end) and run this tool again.")


if __name__ == "__main__":
    main()
