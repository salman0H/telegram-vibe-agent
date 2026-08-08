import os
import time
import json
import html
import urllib.request
import urllib.error
import telegram_client

LOG_FILE = "daily_log.json"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

def call_groq(prompt):
    """
    Sends a prompt directly to the Groq API using standard urllib.
    Includes a browser User-Agent to bypass Cloudflare 1010 firewall errors.
    """
    if not GROQ_API_KEY:
        print("[LLM Error] GROQ_API_KEY is missing from environment variables.")
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    
    payload = {
        "model": "llama3-70b-8192",
        "messages": [
            {
                "role": "system", 
                "content": "You are a poetic music curator for a Telegram channel. You write exclusively in Persian. Output exactly what is requested, no markdown code blocks, no chatty introductions, no extra text."
            },
            {
                "role": "user", 
                "content": prompt
            }
        ],
        "temperature": 0.7,
        "max_tokens": 500
    }
    
    data = json.dumps(payload).encode("utf-8")
    
    # 🔴 FIX: Added User-Agent and Accept headers to bypass Cloudflare WAF block (Error 1010)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    req = urllib.request.Request(url, data=data, headers=headers)
    
    try:
        print("[Groq API] Sending generation request...")
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content = res_data.get("choices", [])[0].get("message", {}).get("content", "")
            
            print("[Groq API] Success! Response received.")
            return content.replace("```html", "").replace("```", "").strip()
            
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print(f"[Groq HTTP Error] Code {e.code}: {err_msg}")
    except Exception as e:
        print(f"[Groq Network Error] Exception: {e}")
        
    return None

def generate_vibe_caption(performer, title):
    """Generates the main artistic caption formatted in HTML."""
    prompt = f"""
    Generate a Telegram caption in EXACT HTML format.
    Artist: {performer}, Title: {title}
    
    [Vibe Emoji] {performer} - {title}
    
    [One very short Persian paragraph describing the emotional mood of this song]
    
    <blockquote><b>«[Unique Persian literary or cinematic quote matching the vibe]»</b></blockquote>
    <blockquote><b>"[Unique poetic English sentence matching the vibe]"</b></blockquote>
    """
    return call_groq(prompt)

def generate_hashtags(performer, title):
    """Generates Telegram hashtags separately."""
    prompt = f"Generate 4 to 6 relevant hashtags for the song: {performer} - {title}. Output ONLY hashtags separated by spaces. Example: #Pop #Music #Vibe"
    return call_groq(prompt)

def main():
    if not GROQ_API_KEY:
        print("[Error] GROQ_API_KEY is not configured in GitHub Secrets.")
        return

    if not os.path.exists(LOG_FILE):
        print(f"[Curator] {LOG_FILE} does not exist. Execution skipped.")
        return

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        try:
            log_data = json.load(f)
        except Exception as e:
            print(f"[Error] Failed to parse {LOG_FILE}: {e}")
            return

    if not log_data:
        print("[Curator] No tracks pending in log.")
        return

    print(f"[Curator] Loaded {len(log_data)} tracks for processing.")
    success_ids = []

    for track in log_data:
        message_id = track["message_id"]
        raw_caption = track.get("caption", "")
        base_caption = html.escape(raw_caption) if raw_caption else ""
        
        needs_caption = not base_caption.strip()
        needs_tags = bool(base_caption.strip()) and ("#" not in base_caption)
        
        if not needs_caption and not needs_tags:
            print(f"[Curator] Message {message_id} is already complete. Marking as done.")
            success_ids.append(message_id)
            continue

        print(f"[Curator] Processing message {message_id} (Artist: {track.get('performer')}, Title: {track.get('title')})")
        new_caption = base_caption

        if needs_caption:
            ai_text = generate_vibe_caption(track.get("performer", "Unknown"), track.get("title", "Unknown"))
            if ai_text:
                new_caption = ai_text
            else:
                print(f"[Curator] Failed to get Groq AI caption for message {message_id}. Retaining in log.")
                continue 
                
        if needs_tags or needs_caption: 
            tags_text = generate_hashtags(track.get("performer", "Unknown"), track.get("title", "Unknown"))
            if tags_text:
                new_caption = f"{new_caption}\n\n{tags_text}" if new_caption else tags_text
            else:
                print(f"[Curator] Warning: Failed to generate hashtags for {message_id}.")
            
        if len(new_caption) > 1024:
            new_caption = new_caption[:1020] + "..."
            
        result = telegram_client.edit_message_caption(message_id, new_caption)
        
        if result and (result.get("ok") or result.get("ignored")):
            success_ids.append(message_id)
            print(f"[Curator] Successfully updated message {message_id} in Telegram.")
        else:
            print(f"[Curator] Telegram edit request failed for message {message_id}. Retaining in log.")
            
        time.sleep(3)

    remaining_tracks = [t for t in log_data if t["message_id"] not in success_ids]
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(remaining_tracks, f, ensure_ascii=False, indent=2)
        
    print(f"[Curator] Execution finished. {len(success_ids)} updated, {len(remaining_tracks)} remaining.")

if __name__ == "__main__":
    main()