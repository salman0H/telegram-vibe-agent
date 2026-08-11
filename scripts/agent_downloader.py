import os
import json
import time
import subprocess
import telegram_api

# Environment Variables
BOT_TOKEN = os.environ.get("MUSIC_BOT_TOKEN")
CHANNEL_ID = os.environ.get("MUSIC_CHANNEL_ID")
ADMIN_ID = os.environ.get("ADMIN_USER_ID") # Security: Only accept queries from this Telegram User ID

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
    """
    Uses yt-dlp to search, download, and extract best quality audio.
    Caps file size at ~45MB to respect Telegram's 50MB bot upload limit.
    """
    output_template = f"{DOWNLOAD_DIR}/%(title)s.%(ext)s"
    
    # Command constructs: search yt, extract audio, convert to mp3, limit size
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
        # Parse yt-dlp output to get file details
        for line in result.stdout.strip().split('\n'):
            try:
                info = json.loads(line)
                title = info.get("title", "Unknown Title")
                uploader = info.get("uploader", "Unknown Artist")
                # yt-dlp changes extension to mp3 after post-processing
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
        print("[Error] Missing critical environment variables (Token, Channel, or Admin ID).")
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
        state["last_update_id"] = update_id # Confirm receipt to Telegram
        
        message = update.get("message")
        if not message:
            continue
            
        user_id = str(message.get("from", {}).get("id", ""))
        
        # Security Gateway: Ignore everyone except the authorized Admin
        if user_id != str(ADMIN_ID):
            print(f"[Security] Ignored message from unauthorized user: {user_id}")
            continue
            
        text_query = message.get("text")
        if not text_query:
            continue # We only process text queries (song names) for now
            
        print(f"\n[Agent] Received authorized query: '{text_query}'")
        
        # 1. Download
        track_info = download_track(text_query)
        if not track_info:
            print("[Agent] Failed to download track. Moving to next update.")
            continue
            
        # 2. Upload to Channel
        audio_path = track_info["path"]
        tg_response = telegram_api.send_audio(BOT_TOKEN, CHANNEL_ID, audio_path, caption="")
        
        # 3. Cleanup: CRITICAL STEP to respect GitHub Storage Limits
        try:
            os.remove(audio_path)
            print(f"[Cleanup] Deleted local file: {audio_path}")
        except Exception as e:
            print(f"[Cleanup Error] Could not delete {audio_path}: {e}")
            
        # 4. Append to Daily Log for Night Shift (AI Curator)
        if tg_response and tg_response.get("ok"):
            channel_msg = tg_response.get("result", {})
            channel_msg_id = channel_msg.get("message_id")
            
            log_data.append({
                "message_id": channel_msg_id,
                "performer": track_info["performer"],
                "title": track_info["title"],
                "caption": "" # Empty, waiting for AI
            })
            print(f"[Agent] Track queued in daily_log.json for AI curation (Msg ID: {channel_msg_id})")
        
        time.sleep(2) # Respect API limits

    # Save tracking states
    save_state(state)
    save_daily_log(log_data)
    print("\n[Agent] Shift completed. States saved.")

if __name__ == "__main__":
    main()
