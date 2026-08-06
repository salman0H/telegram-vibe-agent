import os
import json
import urllib.request
import urllib.parse
from urllib.error import URLError

# Fallback mechanism to support both environment variable naming conventions
BOT_TOKEN = os.environ.get("MUSIC_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("MUSIC_CHANNEL_ID") or os.environ.get("TELEGRAM_CHANNEL_ID", "")

def edit_message_caption(message_id, caption):
    """
    Edits the caption of an audio message in the Telegram channel using HTML parse mode.
    """
    if not BOT_TOKEN or not CHANNEL_ID:
        print("[Error] Missing Bot Token or Channel ID in environment variables.")
        return None

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageCaption"
    
    payload = {
        "chat_id": CHANNEL_ID,
        "message_id": message_id,
        "caption": caption,
        "parse_mode": "HTML"
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, 
        data=data, 
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode())
            print(f"[Telegram Client] Successfully edited message {message_id}")
            return res_data
    except URLError as e:
        if hasattr(e, 'read'):
            err_body = e.read().decode()
            print(f"[Telegram API Error] Message {message_id} edit failed: {err_body}")
            try:
                err_json = json.loads(err_body)
                # Ignore redundant edits if caption is identical
                if "message is not modified" in err_json.get("description", ""):
                    return {"ok": True, "ignored": True}
            except Exception:
                pass
        else:
            print(f"[Network Error] {e}")
        return None