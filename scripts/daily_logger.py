import json
import os
import time

LOG_FILE = "daily_log.json"

def load_log():
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_log(data):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_track(message_id, performer, title, genres, caption):
    log_data = load_log()
    log_data.append({
        "message_id": message_id,
        "performer": performer,
        "title": title,
        "genres": genres,
        "caption": caption,
        "timestamp": time.time()
    })
    save_log(log_data)

def remove_tracks(message_ids):
    log_data = load_log()
    filtered_data = [track for track in log_data if track["message_id"] not in message_ids]
    save_log(filtered_data)