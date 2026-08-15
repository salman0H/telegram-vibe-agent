import os
import json
import time
import subprocess
import glob
import urllib.request
import telegram_api

BOT_TOKEN = os.environ.get("MUSIC_BOT_TOKEN")
CHANNEL_ID = os.environ.get("MUSIC_CHANNEL_ID")
ADMIN_ID = os.environ.get("ADMIN_USER_ID")

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
            pass
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

def empty_dir():
    for f in glob.glob(f"{DOWNLOAD_DIR}/*"):
        try: os.remove(f)
        except: pass

def extract_clean_metadata(query):
    # Overwrite YouTube's messy titles by extracting performer and title from the user's clean query
    performer = "Unknown Artist"
    title = query
    
    if "-" in query:
        parts = query.split("-", 1)
        performer = parts[0].strip()
        title = parts[1].strip()
    elif "–" in query:
        parts = query.split("–", 1)
        performer = parts[0].strip()
        title = parts[1].strip()
        
    return performer, title

def download_track_ytdlp(query):
    empty_dir()
    output_template = f"{DOWNLOAD_DIR}/%(title)s.%(ext)s"
    
    # We keep ytsearch1 because many Persian tracks are not officially on YouTube Music
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
    
    print(f"[Downloader] Executing yt-dlp for text query: '{query}'")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        for line in result.stdout.strip().split('\n'):
            try:
                info = json.loads(line)
                # We ignore YouTube's uploader/title for metadata, we only need the path
                downloaded_files = glob.glob(f"{DOWNLOAD_DIR}/*.mp3")
                if downloaded_files:
                    return {"path": downloaded_files[0]}
            except json.JSONDecodeError:
                continue
    except subprocess.CalledProcessError as e:
        print(f"[Downloader Error] yt-dlp failed: {e.stderr}")
    return None

def download_telegram_file(file_id, output_filename):
    empty_dir()
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            
        if not data.get("ok"):
            print(f"[Downloader Error] getFile failed: {data}")
            return None
            
        file_path = data["result"]["file_path"]
        dl_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        
        output_filename = output_filename.replace("/", "_").replace("\\", "_")
        if not output_filename.endswith(".mp3"):
            output_filename += ".mp3"
            
        output_filepath = os.path.join(DOWNLOAD_DIR, output_filename)
        print(f"[Downloader] Pulling file directly from Telegram servers...")
        
        urllib.request.urlretrieve(dl_url, output_filepath)
        return output_filepath
    except Exception as e:
        print(f"[Downloader Error] Telegram direct download failed: {e}")
        return None

def main():
    if not all([BOT_TOKEN, CHANNEL_ID, ADMIN_ID]):
        print("[Error] Missing critical environment variables.")
        return

    ensure_dirs()
    state = load_state()
    offset = state.get("last_update_id", 0) + 1
    
    updates = telegram_api.get_updates(BOT_TOKEN, offset)
    
    if not updates:
        print("[Agent] No new messages in queue.")
        return
        
    print(f"[Agent] Found {len(updates)} new update(s) in queue! Processing...")
    log_data = load_daily_log()
    
    for update in updates:
        update_id = update.get("update_id")
        state["last_update_id"] = update_id 
        
        message = update.get("message") or update.get("edited_message")
        
        if not message:
            continue
            
        user_id = str(message.get("from", {}).get("id", ""))
        message_id = message.get("message_id")
        
        if user_id != str(ADMIN_ID):
            print(f"[Security] Update {update_id} blocked. Unauthorized sender: {user_id}")
            continue
            
        text_query = message.get("text", "")
        audio_obj = message.get("audio") or message.get("voice") or message.get("document")
        
        if not text_query and not audio_obj:
            continue
            
        track_info = None
        status_msg_id = None
        clean_performer = "Unknown Artist"
        clean_title = "Unknown Title"
        
        if audio_obj:
            print(f"\n[Agent] Received forwarded Audio/Document.")
            file_id = audio_obj.get("file_id")
            clean_title = audio_obj.get("title", f"Track_{update_id}") if isinstance(audio_obj, dict) else f"Track_{update_id}"
            clean_performer = audio_obj.get("performer", "Unknown Artist") if isinstance(audio_obj, dict) else "Unknown Artist"
            file_name = audio_obj.get("file_name", f"{clean_title}.mp3") if isinstance(audio_obj, dict) else f"{clean_title}.mp3"
            
            status = telegram_api.send_message(BOT_TOKEN, user_id, f"⏳ Receiving forwarded audio:\n{clean_title}", reply_to_message_id=message_id)
            status_msg_id = status.get("result", {}).get("message_id") if status else None
            
            audio_path = download_telegram_file(file_id, file_name)
            if audio_path:
                track_info = {"path": audio_path}
                
        elif text_query:
            print(f"\n[Agent] Received text query: '{text_query}'")
            # Extract metadata exactly from what the user typed
            clean_performer, clean_title = extract_clean_metadata(text_query)
            
            status = telegram_api.send_message(BOT_TOKEN, user_id, f"⏳ Searching yt-dlp for:\n{text_query}", reply_to_message_id=message_id)
            status_msg_id = status.get("result", {}).get("message_id") if status else None
            
            track_info = download_track_ytdlp(text_query)

        # Validation & Upload
        if not track_info or not track_info["path"]:
            print("[Agent] Failed to process track.")
            if status_msg_id:
                telegram_api.edit_message_text(BOT_TOKEN, user_id, status_msg_id, "❌ Failed to process or download the track.")
            continue
            
        if status_msg_id:
            telegram_api.edit_message_text(BOT_TOKEN, user_id, status_msg_id, "✅ Download complete!\nUploading to channel...")
            
        audio_path = track_info["path"]
        
        # Pass the extracted clean metadata directly to Telegram API
        tg_response = telegram_api.send_audio(
            BOT_TOKEN, 
            CHANNEL_ID, 
            audio_path, 
            caption="", 
            performer=clean_performer, 
            title=clean_title
        )
        
        try:
            os.remove(audio_path)
        except Exception:
            pass
            
        if tg_response and tg_response.get("ok"):
            channel_msg = tg_response.get("result", {})
            channel_msg_id = channel_msg.get("message_id")
            
            log_data.append({
                "message_id": channel_msg_id,
                "performer": clean_performer,
                "title": clean_title,
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
