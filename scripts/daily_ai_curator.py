import os
import time
import json
import html
import urllib.request
import urllib.parse
import urllib.error
import telegram_client

LOG_FILE = "daily_log.json"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

def fetch_itunes_metadata(performer, title):
    """
    Searches the iTunes API to find the primary genre and metadata of the song.
    This helps the LLM understand the true vibe and origin of the track.
    """
    query = f"{performer} {title}"
    safe_query = urllib.parse.quote_plus(query)
    url = f"https://itunes.apple.com/search?term={safe_query}&entity=song&limit=1"
    
    try:
        print(f"[iTunes] Fetching metadata for: {performer} - {title}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data.get("resultCount", 0) > 0:
                track_info = data["results"][0]
                genre = track_info.get("primaryGenreName", "Unknown")
                print(f"[iTunes] Found genre: {genre}")
                return genre
    except Exception as e:
        print(f"[iTunes] Failed to fetch metadata: {e}")
        
    return "Unknown"

def call_groq(system_prompt, user_prompt):
    """
    Sends a highly strictly formatted prompt to the Groq API.
    """
    if not GROQ_API_KEY:
        print("[LLM Error] GROQ_API_KEY is missing.")
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.65, # Lowered slightly for more focused, less hallucinatory poetic generation
        "max_tokens": 150
    }
    
    data = json.dumps(payload).encode("utf-8")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    req = urllib.request.Request(url, data=data, headers=headers)
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content = res_data.get("choices", [])[0].get("message", {}).get("content", "")
            return content.strip()
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print(f"[Groq HTTP Error] Code {e.code}: {err_msg}")
    except Exception as e:
        print(f"[Groq Network Error] Exception: {e}")
        
    return None

def generate_vibe_caption(performer, title):
    """Generates the main artistic caption based on iTunes vibe and language detection."""
    
    # 1. Ask iTunes for help to get the exact genre
    genre = fetch_itunes_metadata(performer, title)
    
    # 2. Strict system guidelines to match image_af914f.png style
    system_prompt = """You are an elite, minimalist music curator.
    Your goal is to write a single, deeply poetic, and atmospheric sentence (max 2 lines) that captures the exact emotional vibe of the requested song.
    
    CRITICAL STRICT RULES:
    1. NEVER write the artist's name or the song title in your response.
    2. NEVER use emojis.
    3. DO NOT use markdown, HTML, or blockquotes.
    4. LANGUAGE DETECTION: Analyze the artist and title. If the artist is Iranian/Persian, you MUST write the sentence in pure, elegant Persian (فارسی) and wrap it in standard Persian quotes: « »
    5. If the song is international/English, write it in English and wrap it in double quotes: " "
    6. Output ONLY the final quoted sentence. No introductions, no explanations, no translations."""

    user_prompt = f"Artist: {performer}\nTitle: {title}\nGenre from iTunes: {genre}\n\nWrite the single poetic sentence now based on the rules."
    
    print("[Groq API] Sending caption generation request...")
    return call_groq(system_prompt, user_prompt)

def generate_hashtags(performer, title):
    """Generates a minimalistic set of Telegram hashtags."""
    genre = fetch_itunes_metadata(performer, title) # Can use cached version in future, but fine for now
    
    system_prompt = """You are an SEO expert for a minimalist music channel.
    Generate exactly 3 to 4 relevant hashtags based on the artist and genre.
    RULES:
    1. Output ONLY the hashtags separated by spaces.
    2. If it's a Persian song, include 1 or 2 Persian hashtags.
    3. DO NOT output any other text."""
    
    user_prompt = f"Artist: {performer}\nTitle: {title}\nGenre: {genre}"
    
    print("[Groq API] Sending hashtag generation request...")
    return call_groq(system_prompt, user_prompt)

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

        print(f"\n[Curator] --- Processing message {message_id} ({track.get('performer')} - {track.get('title')}) ---")
        new_caption = base_caption

        if needs_caption:
            ai_text = generate_vibe_caption(track.get("performer", "Unknown"), track.get("title", "Unknown"))
            if ai_text:
                new_caption = ai_text
            else:
                print(f"[Curator] Failed to get AI caption for message {message_id}. Retaining in log.")
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
        
    print(f"\n[Curator] Execution finished. {len(success_ids)} updated, {len(remaining_tracks)} remaining.")

if __name__ == "__main__":
    main()