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
    Searches the iTunes API ONCE per song to find the primary genre.
    Reduces API calls significantly while giving context to the LLM.
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
                genre = data["results"][0].get("primaryGenreName", "Unknown")
                print(f"[iTunes] Found genre: {genre}")
                return genre
    except Exception as e:
        print(f"[iTunes] Failed to fetch metadata: {e}")
        
    return "Unknown"

def call_groq(system_prompt, user_prompt):
    """
    Sends a single optimized request to the Groq API.
    Bypasses Cloudflare 1010 block with standard browser headers.
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
        "temperature": 0.65, 
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

def generate_ai_content(performer, title, needs_caption, needs_tags):
    """
    A unified generator that handles captions, tags, or both in a SINGLE API call.
    Uses iTunes genre to guide the LLM's poetic tone.
    """
    genre = fetch_itunes_metadata(performer, title)
    
    # Core universal rules for the LLM
    rules = [
        "CRITICAL STRICT RULES:",
        "1. NEVER write the artist's name or the song title in your response.",
        "2. NEVER use emojis under any circumstances.",
        "3. DO NOT use markdown, HTML, or blockquotes.",
    ]
    
    if needs_caption and needs_tags:
        system_prompt = "You are an elite, minimalist music curator.\n"
        system_prompt += "Your goal is to write a final caption containing exactly two parts separated by a blank line:\n"
        system_prompt += "Part 1: A single, deeply poetic sentence (max 2 lines) capturing the emotional vibe of the song.\n"
        system_prompt += "Part 2: Exactly 3 to 4 relevant hashtags.\n\n"
        system_prompt += "\n".join(rules) + "\n"
        system_prompt += "4. LANGUAGE DETECTION for Part 1: Analyze the artist and title. If the artist is Iranian/Persian, you MUST write Part 1 in pure, elegant Persian (فارسی) and wrap it in standard Persian quotes: « »\n"
        system_prompt += "5. If the song is international/English, write Part 1 in English and wrap it in double quotes: \" \"\n"
        system_prompt += "6. For Part 2 (Hashtags): If it's a Persian song, include 1 or 2 Persian hashtags. Format: #Tag1 #Tag2\n"
        system_prompt += "7. Output ONLY the final text. No introductions, no explanations."
        
    elif needs_caption:
        system_prompt = "You are an elite, minimalist music curator.\n"
        system_prompt += "Your goal is to write a single, deeply poetic sentence (max 2 lines) capturing the emotional vibe of the requested song.\n\n"
        system_prompt += "\n".join(rules) + "\n"
        system_prompt += "4. LANGUAGE DETECTION: Analyze the artist and title. If the artist is Iranian/Persian, you MUST write the sentence in pure, elegant Persian (فارسی) and wrap it in standard Persian quotes: « »\n"
        system_prompt += "5. If the song is international/English, write it in English and wrap it in double quotes: \" \"\n"
        system_prompt += "6. Output ONLY the final quoted sentence. No introductions, no explanations."
        
    else: # Only tags needed
        system_prompt = "You are an SEO expert for a minimalist music channel.\n"
        system_prompt += "Your goal is to generate exactly 3 to 4 relevant hashtags based on the artist and genre.\n\n"
        system_prompt += "\n".join(rules) + "\n"
        system_prompt += "4. Format: #Tag1 #Tag2 #Tag3\n"
        system_prompt += "5. If it's a Persian song, include 1 or 2 Persian hashtags.\n"
        system_prompt += "6. Output ONLY the hashtags separated by spaces."

    user_prompt = f"Artist: {performer}\nTitle: {title}\nGenre from iTunes: {genre}\n\nGenerate the content now based on the strict rules."
    
    print("[Groq API] Sending optimized unified generation request...")
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

        if needs_caption or needs_tags:
            ai_text = generate_ai_content(track.get("performer", "Unknown"), track.get("title", "Unknown"), needs_caption, needs_tags)
            
            if ai_text:
                if needs_caption and needs_tags:
                    new_caption = ai_text # LLM provides both nicely formatted
                elif needs_caption:
                    new_caption = ai_text # LLM provides just the quote
                elif needs_tags:
                    new_caption = f"{new_caption}\n\n{ai_text}" if new_caption else ai_text # Append tags
            else:
                print(f"[Curator] Failed to get AI content for message {message_id}. Retaining in log.")
                continue 
            
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