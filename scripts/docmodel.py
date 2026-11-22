"""Shared document model helpers.

One canonical text form for a PDF page, so that evidence offsets computed by
``extract_document.py`` and checked by ``validate_result.py`` agree exactly.

Offsets are *Unicode code point* offsets into the page text produced by
:func:`build_page_text`, not byte offsets.  Both the extractor and the
validator call this module, which is what makes an evidence span replayable.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List

PIPELINE_VERSION = "nanopub-reading/1.0.0"
SCHEMA_VERSION = "nanopub-reading-result/1.0"

# Sentence terminators for English and Chinese prose.  Deliberately conservative:
# a missed split leaves a longer span (safe), an over-eager split would cut a
# quote in half (unsafe), so trailing abbreviations are protected below.
_SENT_END = re.compile(r"(?<=[.!?\u3002\uff01\uff1f])[\"')\]]*\s+")

# Abbreviations that must not end a sentence, e.g. "et al. This ..." / "Fig. 3".
_ABBREV = {
    "al", "e.g", "i.e", "fig", "figs", "eq", "eqs", "sec", "secs", "ref", "refs",
    "vs", "cf", "approx", "no", "nos", "tab", "resp", "etc", "dr", "prof", "st",
    "mr", "ms", "vol", "pp", "ch", "sect",
}

_WS_RUN = re.compile(r"[ \t\u00a0\u3000]+")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_id(prefix: str, *parts: str) -> str:
    """Deterministic identifier: same inputs -> same id, so reruns are stable."""
    joined = "\x1f".join(parts)
    return f"{prefix}:{sha256_text(joined)[:16]}"


def normalize_line(line: str) -> str:
    return _WS_RUN.sub(" ", line).strip()


def join_lines(lines: List[str]) -> str:
    """Join PDF lines into a paragraph.

    Hyphenated line breaks are de-hyphenated ("trans-\nformer" -> "transformer")
    because the hyphen is a typesetting artefact, not part of the word.  Every
    other line break becomes a single space.
    """
    out: List[str] = []
    for raw in lines:
        line = normalize_line(raw)
        if not line:
            continue
        if out and out[-1].endswith("-") and not out[-1].endswith("--"):
            out[-1] = out[-1][:-1] + line
        elif out:
            out[-1] = out[-1] + " " + line
        else:
            out.append(line)
    return "".join(out)


def split_sentences(text: str) -> List[str]:
    """Split a paragraph into sentences, keeping abbreviations intact."""
    if not text:
        return []
    pieces: List[str] = []
    start = 0
    for m in _SENT_END.finditer(text):
        end = m.start()
        candidate = text[start:end].strip()
        head = candidate.rstrip(".!?。！？").rsplit(" ", 1)[-1].lower().strip(",")
        if head in _ABBREV:
            continue
        if candidate:
            pieces.append(candidate)
        start = m.end()
    tail = text[start:].strip()
    if tail:
        pieces.append(tail)
    # Re-join a piece that is only a few characters long (stray "3." etc.).
    merged: List[str] = []
    for piece in pieces:
        if merged and len(piece) <= 3:
            merged[-1] = merged[-1] + " " + piece
        else:
            merged.append(piece)
    return merged


def build_page_text(blocks: List[str], page: int = 1) -> Dict[str, Any]:
    """Assemble page text from paragraph texts and index their offsets.

    Identifiers embed the page number (``p003-b015-s002``) so they stay unique
    across the whole document; block-local ids would collide on every page.
    """
    parts: List[str] = []
    block_meta: List[Dict[str, Any]] = []
    cursor = 0
    for idx, block in enumerate(blocks):
        if not block:
            continue
        if parts:
            parts.append("\n\n")
            cursor += 2
        start = cursor
        parts.append(block)
        cursor += len(block)
        block_id = f"b{idx:03d}"
        sent_meta: List[Dict[str, Any]] = []
        sent_cursor = start
        for s_idx, sentence in enumerate(split_sentences(block)):
            local = block.find(sentence, sent_cursor - start)
            if local < 0:
                local = sent_cursor - start
            s_start = start + local
            s_end = s_start + len(sentence)
            sent_meta.append(
                {
                    "sentence_id": f"p{page:03d}-{block_id}s{s_idx:03d}",
                    "text": sentence,
                    "char_start": s_start,
                    "char_end": s_end,
                }
            )
            sent_cursor = s_end
        block_meta.append(
            {
                "block_id": block_id,
                "text": block,
                "char_start": start,
                "char_end": cursor,
                "sentences": sent_meta,
            }
        )
    return {"text": "".join(parts), "blocks": block_meta, "char_length": cursor}


def _collapse_with_map(s: str):
    """Collapse whitespace runs to one space, keeping index -> original index."""
    out: List[str] = []
    idx_map: List[int] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i].isspace():
            j = i
            while j < n and s[j].isspace():
                j += 1
            out.append(" ")
            idx_map.append(i)
            i = j
        else:
            out.append(s[i])
            idx_map.append(i)
            i += 1
    return "".join(out), idx_map


def locate_quote(page_text: str, quote: str) -> Dict[str, Any]:
    """Find a quote in page text.

    Two methods are attempted, in this order, and reported back:
      ``exact_substring``      -- byte-for-byte after line joining
      ``whitespace_normalized``-- only whitespace differs
    Anything else is *not* treated as found; the caller must degrade the claim.
    """
    if not quote:
        return {"verified": False, "method": "unchecked", "detail": "empty quote"}
    pos = page_text.find(quote)
    if pos >= 0:
        return {
            "verified": True,
            "method": "exact_substring",
            "char_start": pos,
            "char_end": pos + len(quote),
            "detail": "",
        }
    # Whitespace-tolerant retry: collapse whitespace runs in both strings while
    # keeping a map from collapsed index back to the original index.
    collapsed_page, idx_map = _collapse_with_map(page_text)
    collapsed_quote, _ = _collapse_with_map(quote)
    cpos = collapsed_page.find(collapsed_quote)
    if cpos >= 0:
        start = idx_map[cpos]
        last = cpos + len(collapsed_quote) - 1
        end = idx_map[last] + 1
        return {
            "verified": True,
            "method": "whitespace_normalized",
            "char_start": start,
            "char_end": end,
            "detail": "quote differs only in whitespace",
        }
    return {
        "verified": False,
        "method": "reported_not_found",
        "detail": "quote is not an exact substring of the page text",
    }


def write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
