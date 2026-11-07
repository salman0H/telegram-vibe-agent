"""Maintain an ordered artist/song catalogue and its generated Markdown table."""
import argparse
import html
import json
import os
from pathlib import Path
import re
import subprocess
import unicodedata

ARTISTS_FILE = Path("data/artist_tracks.json")
MARKDOWN_FILE = Path("data/artists.md")
LEGACY_FILE = Path("data/artists.txt")
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


def clean_title(value):
    if not isinstance(value, str):
        return None
    title = " ".join(unicodedata.normalize("NFKC", value).split())
    if (not title or artist_key(title) in {"unknown", "unknown title", "none", "null", "n/a"}
            or re.fullmatch(r"Track_\d+", title, re.IGNORECASE)
            or any(unicodedata.category(c) == "Cc" for c in title)):
        return None
    return title


def atomic_write(path, text):
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load_catalogue(path=ARTISTS_FILE):
    path = Path(path)
    if not path.exists():
        return []
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict) or not isinstance(entry.get("artist"), str)
        or not isinstance(entry.get("tracks"), list)
        or not all(isinstance(title, str) for title in entry["tracks"])
        for entry in entries
    ):
        raise ValueError("Invalid artist catalogue; restore a valid version from Git.")
    return entries


def markdown_cell(text):
    # Escape metadata so titles cannot create extra columns, links, or HTML.
    text = html.escape(text, quote=False).replace("|", "&#124;").replace("\\", "&#92;")
    for char in ('*', '_', '`', '[', ']', '~'):
        text = text.replace(char, "\\" + char)
    return text


def render_markdown(entries):
    lines = ["# Channel artists and songs", "",
             "Artists and songs appear in first-recorded order. Song numbers are local to each artist.",
             "Generated from `artist_tracks.json`; updated automatically when channel audio is recorded.", "",
             "| # | Artist | Songs |", "| --- | --- | --- |"]
    for index, entry in enumerate(entries, 1):
        songs = "<br>".join(f"{number}. {markdown_cell(title)}"
                             for number, title in enumerate(entry["tracks"], 1)) or "—"
        lines.append(f"| {index} | {markdown_cell(entry['artist'])} | {songs} |")
    return "\n".join(lines) + "\n"


def record_tracks(tracks, path=ARTISTS_FILE):
    """Append new titles to the existing artist row; never duplicate a known title."""
    entries = load_catalogue(path)
    by_artist = {artist_key(entry["artist"]): entry for entry in entries}
    known_titles = {key: {artist_key(title) for title in entry["tracks"]}
                    for key, entry in by_artist.items()}
    additions = []
    for track in tracks:
        name = clean_artist(track.get("performer"))
        if not name:
            continue
        key = artist_key(name)
        if key not in by_artist:
            entry = {"artist": name, "tracks": []}
            entries.append(entry)
            by_artist[key] = entry
            known_titles[key] = set()
            additions.append(name)
        title = clean_title(track.get("title"))
        if title and artist_key(title) not in known_titles[key]:
            by_artist[key]["tracks"].append(title)
            known_titles[key].add(artist_key(title))
    # Save the source first. A run interrupted before rendering repairs Markdown next time.
    atomic_write(path, json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
    atomic_write(MARKDOWN_FILE, render_markdown(entries))
    return additions


def record_artists(performers, path=ARTISTS_FILE):
    """Import artist-only credits without inventing missing song titles."""
    return record_tracks(({"performer": name} for name in performers), path)


def collect_channel_artists(updates, channel_id):
    if not channel_id:
        return []
    tracks = []
    for update in updates:
        post = update.get("channel_post") or update.get("edited_channel_post")
        if post and str(post.get("chat", {}).get("id", "")) == str(channel_id) and post.get("audio"):
            tracks.append(post["audio"])
    return record_tracks(tracks) if tracks else []


def seed_from_git_history():
    """Pair artist and title from complete historical queue snapshots, oldest first."""
    result = subprocess.run(
        ["git", "log", "--reverse", "--format=%H", "--", "daily_log.json"],
        capture_output=True, text=True, encoding="utf-8", check=True, timeout=60)
    tracks = []
    for revision in result.stdout.splitlines():
        snapshot = subprocess.run(["git", "show", f"{revision}:daily_log.json"],
                                  capture_output=True, text=True, encoding="utf-8", timeout=15)
        if snapshot.returncode:
            continue  # The file may have been deleted in this historical commit.
        try:
            queue = json.loads(snapshot.stdout)
        except ValueError:
            continue  # Older revisions can contain empty or malformed state files.
        if isinstance(queue, list):
            tracks.extend(track for track in queue if isinstance(track, dict))
    return record_tracks(tracks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-git-history", action="store_true",
                        help="Seed songs from locally available queue history, without contacting Telegram.")
    args = parser.parse_args()
    if LEGACY_FILE.exists() and not ARTISTS_FILE.exists():
        record_artists(LEGACY_FILE.read_text(encoding="utf-8").splitlines())
    if args.from_git_history:
        seed_from_git_history()
    queue = Path("daily_log.json")
    tracks = json.loads(queue.read_text(encoding="utf-8")) if queue.exists() else []
    record_tracks(tracks)


if __name__ == "__main__":
    main()
