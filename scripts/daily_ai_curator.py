import os
import time
import json
import html
import google.generativeai as genai
import telegram_client

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
LOG_FILE = "daily_log.json"

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    generation_config={"temperature": 0.85, "max_output_tokens": 500}
)

def generate_vibe_caption(performer, title, genres):
    prompt = f"""
    Generate Telegram caption in EXACT HTML format. No markdown.
    Artist: {performer}, Title: {title}
    
    [Vibe Emoji] {performer} - {title}
    [One Persian paragraph describing the vibe]
    <blockquote><b>«[Unique Persian literary or cinematic quote]»</b></blockquote>
    <blockquote><b>"[Unique poetic English sentence]"</b></blockquote>
    """
    try:
        response = model.generate_content(prompt)
        return response.text.replace("```html", "").replace("```", "").strip()
    except Exception:
        return None

def generate_hashtags(performer, title, genres):
    prompt = f"Generate 4 to 6 relevant hashtags for: {performer} - {title}. Output ONLY tags separated by space."
    try:
        response = model.generate_content(prompt)
        return response.text.replace("```", "").strip()
    except Exception:
        return None

def main():
    if not GEMINI_KEY or not os.path.exists(LOG_FILE):
        return

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        try:
            log_data = json.load(f)
        except Exception:
            return

    if not log_data:
        return

    success_ids = []

    for track in log_data:
        message_id = track["message_id"]
        raw_caption = track.get("caption", "")
        base_caption = html.escape(raw_caption) if raw_caption else ""
        
        needs_caption = not base_caption.strip()
        needs_tags = bool(base_caption.strip()) and ("#" not in base_caption)
        
        if not needs_caption and not needs_tags:
            success_ids.append(message_id)
            continue

        new_caption = base_caption

        if needs_caption:
            ai_text = generate_vibe_caption(track["performer"], track["title"], track["genres"])
            if not ai_text:
                continue
            new_caption = ai_text
            
        elif needs_tags:
            tags_text = generate_hashtags(track["performer"], track["title"], track["genres"])
            if not tags_text:
                continue
            new_caption = f"{base_caption}\n\n{tags_text}"
            
        if len(new_caption) > 1024:
            new_caption = new_caption[:1020] + "..."
            
        result = telegram_client.edit_message_caption(message_id, new_caption)
        
        if result and (result.get("ok") or result.get("ignored")):
            success_ids.append(message_id)
            
        time.sleep(4)

    remaining_tracks = [t for t in log_data if t["message_id"] not in success_ids]
    
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(remaining_tracks, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()