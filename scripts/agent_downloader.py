import os
import json
import time
import subprocess
import telegram_api

# Environment Variables
BOT_TOKEN = os.environ.get("MUSIC_BOT_TOKEN")
CHANNEL_ID = os.environ.get("MUSIC_CHANNEL_ID")
ADMIN_ID = os.environ.get("ADMIN_USER_ID")

# Constants
STATE_FILE = "state.json"
LOG_FILE = "daily_log.json"
DOWNLOAD_DIR = "downloads"

def ensure_dirs():
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"last_update_id": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def load_daily_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_daily_log(log_data):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

def download_track(query):
    output_template = f"{DOWNLOAD_DIR}/%(title)s.%(ext)s"
    cmd = [
        "yt-dlp",
        f"ytsearch1:{query}",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--max-filesize", "45M",
        "--output", output_template,
        "--print-json",
        "--no-warnings"
    ]
    
    print(f"[Downloader] Executing yt-dlp for query: '{query}'")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        for line in result.stdout.strip().split('\n'):
            try:
                info = json.loads(line)
                title = info.get("title", "Unknown Title")
                uploader = info.get("uploader", "Unknown Artist")
                expected_filepath = os.path.join(DOWNLOAD_DIR, f"{title}.mp3")
                
                if os.path.exists(expected_filepath):
                    return {"path": expected_filepath, "title": title, "performer": uploader}
            except json.JSONDecodeError:
                continue
    except subprocess.CalledProcessError as e:
        print(f"[Downloader Error] yt-dlp failed: {e.stderr}")
        
    return None

def main():
    if not all([BOT_TOKEN, CHANNEL_ID, ADMIN_ID]):
        print("[Error] Missing critical environment variables.")
        return

    ensure_dirs()
    state = load_state()
    offset = state.get("last_update_id", 0) + 1
    
    print(f"[Agent] Checking for new messages (Offset: {offset})...")
    updates = telegram_api.get_updates(BOT_TOKEN, offset)
    
    if not updates:
        print("[Agent] No new messages.")
        return
        
    log_data = load_daily_log()
    
    for update in updates:
        update_id = update.get("update_id")
        state["last_update_id"] = update_id 
        
        message = update.get("message")
        if not message:
            continue
            
        user_id = str(message.get("from", {}).get("id", ""))
        
        # Security Gateway
        if user_id != str(ADMIN_ID):
            print(f"[Security] Ignored message from unauthorized user: {user_id}")
            continue
            
        text_query = message.get("text")
        message_id = message.get("message_id")
        
        if not text_query:
            continue
            
        print(f"\n[Agent] Received authorized query: '{text_query}'")
        
        # --- Interactive Feedback: Step 1 (Start) ---
        status_msg = telegram_api.send_message(
            BOT_TOKEN, 
            user_id, 
            f"⏳ Searching and downloading:\n{text_query}", 
            reply_to_message_id=message_id
        )
        status_msg_id = status_msg.get("result", {}).get("message_id") if status_msg else None
        
        # --- Processing: Download ---
        track_info = download_track(text_query)
        if not track_info:
            print("[Agent] Failed to download track.")
            if status_msg_id:
                telegram_api.edit_message_text(BOT_TOKEN, user_id, status_msg_id, "❌ Failed to find or download the track. It might be too large (>45MB).")
            continue
            
        # --- Interactive Feedback: Step 2 (Downloaded) ---
        if status_msg_id:
            telegram_api.edit_message_text(BOT_TOKEN, user_id, status_msg_id, "✅ Download complete!\nUploading to channel...")
            
        # --- Processing: Upload ---
        audio_path = track_info["path"]
        tg_response = telegram_api.send_audio(BOT_TOKEN, CHANNEL_ID, audio_path, caption="")
        
        # Cleanup file from GitHub disk
        try:
            os.remove(audio_path)
        except Exception as e:
            print(f"[Cleanup Error] Could not delete {audio_path}: {e}")
            
        # --- Interactive Feedback: Step 3 (Finished) ---
        if tg_response and tg_response.get("ok"):
            channel_msg = tg_response.get("result", {})
            channel_msg_id = channel_msg.get("message_id")
            
            log_data.append({
                "message_id": channel_msg_id,
                "performer": track_info["performer"],
                "title": track_info["title"],
                "caption": ""
            })
            print(f"[Agent] Queued in daily_log.json (Msg ID: {channel_msg_id})")
            if status_msg_id:
                telegram_api.edit_message_text(BOT_TOKEN, user_id, status_msg_id, "🚀 Uploaded to channel successfully!\nQueued for AI night shift.")
        else:
            if status_msg_id:
                telegram_api.edit_message_text(BOT_TOKEN, user_id, status_msg_id, "❌ Failed to upload to channel. (Telegram API Error)")
        
        time.sleep(2) 

    save_state(state)
    save_daily_log(log_data)
    print("\n[Agent] Shift completed. States saved.")

if __name__ == "__main__":
    main()
