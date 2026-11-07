"""Keep a cumulative, UTF-8 artist list from published channel audio metadata."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import unicodedata

ARTISTS_FILE = Path("data/artists.txt")
UNKNOWN_NAMES = {"unknown", "unknown artist", "unknown performer", "various artists",
                 "none", "null", "n/a", "ناشناس", "خواننده ناشناس"}


def artist_key(name):
    name = unicodedata.normalize("NFKC", name).casefold()
    name = name.translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "\u200c": " "}))
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    return " ".join(name.split()).rstrip(".،,؛;")


def clean_artist(value):
    if not isinstance(value, str):
        return None
    name = " ".join(unicodedata.normalize("NFKC", value).split()).rstrip(".،,؛;")
    if (not name or artist_key(name) in UNKNOWN_NAMES or name.startswith("@")
            or re.search(r"https?://|(?:www\.|t\.me/)", name, re.IGNORECASE)
            or not any(c.isalpha() for c in name)
            or any(unicodedata.category(c) == "Cc" for c in name)):
        return None
    return name


def record_artists(performers, path=ARTISTS_FILE):
    """Append new credits in first-seen order; retain original spelling and bands."""
    path = Path(path)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    seen = {artist_key(line) for line in existing.splitlines() if line.strip()}
    additions = []
    for performer in performers:
        name = clean_artist(performer)
        if name and artist_key(name) not in seen:
            seen.add(artist_key(name))
            additions.append(name)
    if not additions:
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(existing)
        if existing and not existing.endswith("\n"):
            stream.write("\n")
        stream.write("\n".join(additions) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    print(f"[Artists] Added {len(additions)} new artist credit(s).")
    return additions


def collect_channel_artists(updates, channel_id):
    """Collect every audio post in the configured channel, including captioned posts."""
    if not channel_id:
        return []
    performers = []
    for update in updates:
        post = update.get("channel_post") or update.get("edited_channel_post")
        if post and str(post.get("chat", {}).get("id", "")) == str(channel_id):
            performers.append(post.get("audio", {}).get("performer"))
    return record_artists(performers)


def seed_from_git_history():
    """Read only performer fields added to the published-track queue in local Git history."""
    result = subprocess.run(
        ["git", "log", "--reverse", "--format=", "-p", "--", "daily_log.json"],
        capture_output=True, text=True, encoding="utf-8", check=True, timeout=60)
    performers = []
    for match in re.finditer(r'^\+\s*"performer":\s*("(?:[^"\\]|\\.)*")', result.stdout, re.MULTILINE):
        performers.append(json.loads(match.group(1)))
    return record_artists(performers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-git-history", action="store_true",
                        help="Seed from locally available queue history, without contacting Telegram.")
    args = parser.parse_args()
    if args.from_git_history:
        seed_from_git_history()
    queue = Path("daily_log.json")
    if queue.exists():
        tracks = json.loads(queue.read_text(encoding="utf-8"))
        record_artists(track.get("performer") for track in tracks)


if __name__ == "__main__":
    main()
