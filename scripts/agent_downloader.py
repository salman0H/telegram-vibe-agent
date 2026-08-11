import os
import json
import time
import subprocess
import glob
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
    if os.path.exists(STATE_FILE) and os.path.getsize(STATE_FILE) > 0:
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("[Warning] state.json is corrupted or empty. Starting fresh.")
    return {"last_update_id": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def load_daily_log():
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return []

def save_daily_log(log_data):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

def download_track(query):
    # Empty the downloads directory first to prevent picking up old files
    for f in glob.glob(f"{DOWNLOAD_DIR}/*"):
        try:
            os.remove(f)
        except:
            pass

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
                
                # 🔴 FIX: Bulletproof File Resolution
                # Instead of reconstructing the path from the title (which fails on characters like '/'),
                # we directly grab the generated .mp3 file from the ephemeral directory.
                downloaded_files = glob.glob(f"{DOWNLOAD_DIR}/*.mp3")
                
                if downloaded_files:
                    actual_filepath = downloaded_files[0]
                    print(f"[Debug] File successfully located at: {actual_filepath}")
                    return {"path": actual_filepath, "title": title, "performer": uploader}
                
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
        print("[Agent] No new messages in Telegram queue.")
        return
        
    print(f"[Agent] Found {len(updates)} new update(s) in queue! Processing...")
    log_data = load_daily_log()
    
    for update in updates:
        update_id = update.get("update_id")
        state["last_update_id"] = update_id 
        
        message = update.get("message")
        if not message:
            continue
            
        user_id = str(message.get("from", {}).get("id", ""))
        text_query = message.get("text", "")
        message_id = message.get("message_id")
        
        # Security Gateway
        if user_id != str(ADMIN_ID):
            print(f"[Security] Blocked unauthorized sender: {user_id}")
            continue
            
        if not text_query:
            continue
            
        print(f"\n[Agent] Received authorized query: '{text_query}'")
        
        # --- Feedback: Start ---
        status_msg = telegram_api.send_message(
            BOT_TOKEN, 
            user_id, 
            f"⏳ Searching and downloading:\n{text_query}", 
            reply_to_message_id=message_id
        )
        status_msg_id = status_msg.get("result", {}).get("message_id") if status_msg else None
        
        # --- Download ---
        track_info = download_track(text_query)
        if not track_info:
            print("[Agent] Failed to download track.")
            if status_msg_id:
                telegram_api.edit_message_text(BOT_TOKEN, user_id, status_msg_id, "❌ Failed to find or download the track.")
            continue
            
        # --- Feedback: Uploading ---
        if status_msg_id:
            telegram_api.edit_message_text(BOT_TOKEN, user_id, status_msg_id, "✅ Download complete!\nUploading to channel...")
            
        # --- Upload ---
        audio_path = track_info["path"]
        tg_response = telegram_api.send_audio(BOT_TOKEN, CHANNEL_ID, audio_path, caption="")
        
        # Cleanup
        try:
            os.remove(audio_path)
        except Exception as e:
            print(f"[Cleanup Error] Could not delete {audio_path}: {e}")
            
        # --- Feedback: Finished ---
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
