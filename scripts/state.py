import json
import os

STATE_FILE = "music_state.json"
MAX_PROCESSED_IDS = 2000

DEFAULT_STATE = {
    "offset": None,
    "processed_ids": []
}

def load_state():
    if not os.path.exists(STATE_FILE):
        return dict(DEFAULT_STATE)
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return dict(DEFAULT_STATE)
    merged = dict(DEFAULT_STATE)
    merged.update(data)
    return merged

def save_state(state):
    if len(state.get("processed_ids", [])) > MAX_PROCESSED_IDS:
        state["processed_ids"] = state["processed_ids"][-MAX_PROCESSED_IDS:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def is_processed(state, message_id):
    return message_id in state.get("processed_ids", [])

def mark_processed(state, message_id):
    state.setdefault("processed_ids", []).append(message_id)