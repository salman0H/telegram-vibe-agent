import os
import json
import urllib.request
import urllib.parse
from urllib.error import URLError

BOT_TOKEN = os.environ.get("MUSIC_BOT_TOKEN", "")
CHANNEL_ID = str(os.environ.get("MUSIC_CHANNEL_ID", ""))
STATE_FILE = "music_state.json"
LOG_FILE = "daily_log.json"

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    if not BOT_TOKEN:
        print("[Error] Missing MUSIC_BOT_TOKEN")
        return

    state = load_json(STATE_FILE, {"offset": 0})
    queue = load_json(LOG_FILE, [])
    queued_ids = {track["message_id"] for track in queue}

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"offset": state["offset"], "timeout": 5, "allowed_updates": ["channel_post"]}
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}")

    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
    except URLError as e:
        print(f"[Network Error] {e}")
        return

    if not data.get("ok"):
        print(f"[Telegram API Error] {data}")
        return

    updates = data.get("result", [])
    if not updates:
        return

    highest_offset = state["offset"]

    for update in updates:
        update_id = update["update_id"]
        highest_offset = max(highest_offset, update_id + 1)
        
        post = update.get("channel_post")
        if not post or "audio" not in post:
            continue

        msg_channel = str(post.get("chat", {}).get("id", ""))
        if CHANNEL_ID and msg_channel != CHANNEL_ID:
            continue

        message_id = post["message_id"]
        if message_id in queued_ids:
            continue

        raw_caption = post.get("caption", "")
        
        needs_caption = not raw_caption.strip()
        needs_tags = bool(raw_caption.strip()) and ("#" not in raw_caption)

        if needs_caption or needs_tags:
            audio = post["audio"]
            queue.append({
                "message_id": message_id,
                "performer": audio.get("performer", "Unknown Artist"),
                "title": audio.get("title", "Unknown Title"),
                "genres": [],
                "caption": raw_caption,
                "timestamp": post.get("date", 0)
            })
            queued_ids.add(message_id)

    save_json(LOG_FILE, queue)
    state["offset"] = highest_offset
    save_json(STATE_FILE, state)

if __name__ == "__main__":
    main()