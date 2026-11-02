"""Persistent editorial memory; exact history never expires, prompt context stays small."""
import hashlib
import html
import json
import os
from pathlib import Path
import re
import unicodedata
from difflib import SequenceMatcher

MEMORY_FILE = "content_memory.json"
CORPUS_FILE = Path(__file__).resolve().parents[1] / "data" / "poetry.json"


def save_json(path, data):
    """Replace atomically so an interrupted write cannot truncate the queue/memory."""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def normalize(text):
    text = html.unescape(re.sub(r"<[^>]*>", "", text))
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "\u200c": " "}))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[^\W_]+", text, re.UNICODE))


def fingerprint(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def load_memory(path=MEMORY_FILE):
    if not Path(path).exists():
        return {"version": 1, "used_poem_ids": [], "fingerprints": [], "recent": [], "pending": {}}
    # Corrupt memory must stop the run, never silently permit old material again.
    with open(path, encoding="utf-8") as stream:
        memory = json.load(stream)
    if memory.get("version") != 1 or any(not isinstance(memory.get(k), list) for k in
            ("used_poem_ids", "fingerprints", "recent")) or not isinstance(memory.get("pending"), dict):
        raise ValueError("Invalid content memory; restore the last valid version from Git.")
    return memory


def load_corpus(path=CORPUS_FILE):
    with open(path, encoding="utf-8") as stream:
        entries = json.load(stream)
    ids, texts = set(), set()
    for entry in entries:
        if (not all(entry.get(k) for k in ("id", "language", "author", "work", "text", "source", "themes"))
                or entry["language"] not in ("fa", "en")
                or entry["id"] in ids or fingerprint(entry["text"]) in texts):
            raise ValueError("Invalid or duplicate poetry entry")
        ids.add(entry["id"])
        texts.add(fingerprint(entry["text"]))
    return entries


def repeated(text, memory):
    normalized = normalize(text)
    if fingerprint(text) in memory["fingerprints"]:
        return True
    words = normalized.split()
    for previous in memory["recent"]:
        old = normalize(previous["text"])
        old_words = old.split()
        if words[:3] == old_words[:3] and len(words) >= 3:
            return True
        a, b = set(words), set(old_words)
        if (SequenceMatcher(None, normalized, old).ratio() >= .78
                or (a and b and len(a & b) / len(a | b) >= .65)):
            return True
    return False


def remember(memory, record):
    if record.get("text"):
        digest = fingerprint(record["text"])
        if digest not in memory["fingerprints"]:
            memory["fingerprints"].append(digest)
            memory["recent"].append({k: record.get(k) for k in
                                     ("text", "poem_id", "author", "style", "lens")})
            memory["recent"] = memory["recent"][-100:]
    if record.get("poem_id") and record["poem_id"] not in memory["used_poem_ids"]:
        memory["used_poem_ids"].append(record["poem_id"])
