import os
import time
import json
import html
from google import genai
from google.genai import types
import telegram_client

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
LOG_FILE = "daily_log.json"

# List of models to try in order (Fallback Mechanism)
AVAILABLE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-pro"
]

if GEMINI_KEY:
    client = genai.Client(api_key=GEMINI_KEY)
else:
    client = None

def generate_vibe_caption(performer, title, genres):
    prompt = f"""
    Generate Telegram caption in EXACT HTML format. No markdown codeblocks, no intro.
    Artist: {performer}, Title: {title}
    
    [Vibe Emoji] {performer} - {title}
    
    [One Persian paragraph describing the mood]
    
    <blockquote><b>«[Unique Persian literary or cinematic quote]»</b></blockquote>
    <blockquote><b>"[Unique poetic English sentence]"</b></blockquote>
    """
    
    for model_name in AVAILABLE_MODELS:
        try:
            print(f"[Gemini] Attempting to generate caption with model: {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.85,
                    max_output_tokens=500,
                )
            )
            text = response.text.replace("```html", "").replace("```", "").strip()
            print(f"[Gemini] Success! Model {model_name} generated the caption.")
            return text
        except Exception as e:
            print(f"[Gemini Warning] Model {model_name} failed: {e}")
            continue # Try the next model in the list
            
    print("[Gemini Error] All models failed to generate caption.")
    return None

def generate_hashtags(performer, title, genres):
    prompt = f"Generate 4 to 6 relevant hashtags for: {performer} - {title}. Output ONLY tags separated by spaces."
    
    for model_name in AVAILABLE_MODELS:
        try:
            print(f"[Gemini] Attempting to generate hashtags with model: {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.85,
                    max_output_tokens=500,
                )
            )
            print(f"[Gemini] Success! Model {model_name} generated the hashtags.")
            return response.text.replace("```", "").strip()
        except Exception as e:
            print(f"[Gemini Warning] Model {model_name} failed: {e}")
            continue # Try the next model in the list

    print("[Gemini Error] All models failed to generate hashtags.")
    return None

def main():
    if not client:
        print("[Error] Missing GEMINI_API_KEY.")
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
            print(f"[Curator] Message {message_id} already complete. Marking done.")
            success_ids.append(message_id)
            continue

        print(f"[Curator] Processing message {message_id} (Artist: {track.get('performer')}, Title: {track.get('title')})")
        new_caption = base_caption

        if needs_caption:
            ai_text = generate_vibe_caption(track.get("performer", "Unknown"), track.get("title", "Unknown"), track.get("genres", []))
            if not ai_text:
                print(f"[Curator] Failed to get AI caption for message {message_id}. Retaining in log.")
                continue
            new_caption = ai_text
            
        elif needs_tags:
            tags_text = generate_hashtags(track.get("performer", "Unknown"), track.get("title", "Unknown"), track.get("genres", []))
            if not tags_text:
                print(f"[Curator] Failed to get AI hashtags for message {message_id}. Retaining in log.")
                continue
            new_caption = f"{base_caption}\n\n{tags_text}"
            
        if len(new_caption) > 1024:
            new_caption = new_caption[:1020] + "..."
            
        result = telegram_client.edit_message_caption(message_id, new_caption)
        
        if result and (result.get("ok") or result.get("ignored")):
            success_ids.append(message_id)
        else:
            print(f"[Curator] Telegram edit failed for message {message_id}. Retaining in log.")
            
        time.sleep(3)

    remaining_tracks = [t for t in log_data if t["message_id"] not in success_ids]
    
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(remaining_tracks, f, ensure_ascii=False, indent=2)
        
    print(f"[Curator] Execution finished. {len(success_ids)} tracks updated. {len(remaining_tracks)} remaining in log.")

if __name__ == "__main__":
    main()