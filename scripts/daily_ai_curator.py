import os
import time
import json
import html
import urllib.request
import urllib.parse
import urllib.error
import random
import telegram_client

LOG_FILE = "daily_log.json"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

def fetch_itunes_metadata(performer, title):
    """
    Searches the iTunes API ONCE per song to find the primary genre.
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
    """
    if not GROQ_API_KEY:
        print("[LLM Error] GROQ_API_KEY is missing.")
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    
    payload = {
        "model": "llama3-70b-8192",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.75, # 🔴 FIX: Slightly increased temperature for more creative, less predictable vocabulary
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
    Unified generator. Injects dynamic structural constraints to prevent repetitive "In the..." or "در سکوت..." patterns.
    """
    genre = fetch_itunes_metadata(performer, title)
    
    # 🔴 FIX: Dynamic Diversity Engine
    # Randomly selects a structural mandate to force the LLM to start sentences differently every single time.
    structural_styles = [
        "Start the sentence immediately with a raw emotion or abstract concept. DO NOT set a scene.",
        "Begin the sentence with a strong, active verb or action.",
        "Open with a striking, surreal visual imagery without introductory phrases.",
        "Start by describing a specific, fleeting physical sensation or touch.",
        "Launch directly into a bold philosophical statement about memory or time.",
        "Focus purely on the atmosphere, starting with a noun related to nature or urban life."
    ]
    forced_style = random.choice(structural_styles)
    
    rules = [
        "CRITICAL STRICT RULES:",
        "1. NEVER write the artist's name or the song title.",
        "2. NEVER use emojis.",
        "3. NO extra spaces inside quotation marks. (Wrong: « text » | Right: «text»)",
        "4. The poetic sentence MUST end with a period/full stop (.).",
        "5. You MUST wrap the entire poetic sentence in HTML bold tags: <b>...</b>",
        "6. BAN LIST: NEVER start sentences with 'In the...', 'در تاریکی', 'در سکوت', 'در این ترانه', 'Through the', or 'Amidst'.",
        "7. BAN LIST: AVOID clichés like 'haunting melody', 'echoes', 'اشک‌ها', 'قلب', 'صدای تنهایی'.",
        f"8. STRUCTURAL MANDATE: {forced_style}"
    ]
    
    if needs_caption and needs_tags:
        system_prompt = "You are an elite, unpredictable, minimalist music curator.\n"
        system_prompt += "Your goal is to write a final caption containing exactly two parts separated by a blank line:\n"
        system_prompt += "Part 1: A single, deeply poetic sentence (max 2 lines) capturing the emotional vibe of the song.\n"
        system_prompt += "Part 2: Exactly 3 to 4 relevant hashtags.\n\n"
        system_prompt += "\n".join(rules) + "\n"
        system_prompt += "9. LANGUAGE DETECTION for Part 1: Analyze the artist and title. If the artist is Iranian/Persian, write Part 1 in pure Persian. Format EXACTLY like this template: <b>«متن شاعرانه شما در اینجا.»</b>\n"
        system_prompt += "10. If the song is international/English, write Part 1 in English. Format EXACTLY like this template: <b>\"Your poetic English sentence here.\"</b>\n"
        system_prompt += "11. For Part 2 (Hashtags): If Persian song, include 1-2 Persian hashtags. Format: #Tag1 #Tag2\n"
        system_prompt += "12. Output ONLY the final text. No introductions."
        
    elif needs_caption:
        system_prompt = "You are an elite, unpredictable, minimalist music curator.\n"
        system_prompt += "Your goal is to write a single, deeply poetic sentence (max 2 lines) capturing the emotional vibe of the requested song.\n\n"
        system_prompt += "\n".join(rules) + "\n"
        system_prompt += "9. LANGUAGE DETECTION: Analyze the artist and title. If the artist is Iranian/Persian, write the sentence in pure Persian. Format EXACTLY like this template: <b>«متن شاعرانه شما در اینجا.»</b>\n"
        system_prompt += "10. If the song is international/English, write the sentence in English. Format EXACTLY like this template: <b>\"Your poetic English sentence here.\"</b>\n"
        system_prompt += "11. Output ONLY the final text. No introductions."
        
    else: 
        system_prompt = "You are an SEO expert for a minimalist music channel.\n"
        system_prompt += "Your goal is to generate exactly 3 to 4 relevant hashtags based on the artist and genre.\n\n"
        system_prompt += "CRITICAL STRICT RULES:\n1. NEVER write the artist's name or title.\n2. NEVER use emojis.\n"
        system_prompt += "3. Format: #Tag1 #Tag2 #Tag3\n"
        system_prompt += "4. If it's a Persian song, include 1 or 2 Persian hashtags.\n"
        system_prompt += "5. Output ONLY the hashtags separated by spaces."

    user_prompt = f"Artist: {performer}\nTitle: {title}\nGenre from iTunes: {genre}\n\nGenerate the content now based on the strict rules."
    
    print("[Groq API] Sending optimized unified generation request with diversity engine...")
    return call_groq(system_prompt, user_prompt)

def clean_typography(text):
    """
    Python post-processing safety net.
    """
    if not text:
        return text
    text = text.replace("« ", "«").replace(" »", "»")
    text = text.replace("<b>« ", "<b>«").replace(" »</b>", "»</b>")
    text = text.replace('" ', '"').replace(' "', '"')
    text = text.replace('<b>" ', '<b>"').replace(' "</b>', '"</b>')
    return text

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
                ai_text = clean_typography(ai_text)
                
                if needs_caption and needs_tags:
                    new_caption = ai_text 
                elif needs_caption:
                    new_caption = ai_text 
                elif needs_tags:
                    new_caption = f"{new_caption}\n\n{ai_text}" if new_caption else ai_text 
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
