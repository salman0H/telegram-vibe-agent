import os
import time
import html
import google.generativeai as genai
import daily_logger
import telegram_client

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    
generation_config = {
    "temperature": 0.85,
    "top_p": 0.9,
    "top_k": 40,
    "max_output_tokens": 500,
}
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    generation_config=generation_config
)

def generate_vibe_caption(performer, title, genres):
    prompt = f"""
    You are an elite, melancholic music curator. Analyze the vibe of this track:
    Artist: {performer}
    Title: {title}
    Genres: {', '.join(genres) if genres else 'Unknown'}

    Generate a Telegram caption strictly following this EXACT HTML format. Do NOT use markdown (** or *). Only use the specified HTML tags.

    [Appropriate Vibe Emoji] {performer} - {title}

    [One deep, atmospheric paragraph in Persian describing the mood, space, and imagery of the song. E.g., walking in rainy streets, midnight solitude, etc.]

    <blockquote><b>«[A completely unique and non-repetitive Persian literary quote, poem, or cinematic dialog matching the vibe. Use sources like Ebtehaj, Shamloo, Akhavan, Sohrab, Forough, Saadi, Hafez, Rumi, Fazel Nazari, or Iranian cinema.]»</b></blockquote>

    <blockquote><b>"[A poetic, elevated English literary sentence capturing the exact essence of the song.]"</b></blockquote>

    STRICT RULES:
    1. Output ONLY the raw HTML text described above. No introductions, no summary tables, no markdown code blocks (```html).
    2. The Persian quote MUST be unique for every request.
    3. Tone must be dignified, melancholic, poetic, and fluent.
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        text = text.replace("```html", "").replace("```", "").strip()
        return text
    except Exception:
        return None

def generate_hashtags(performer, title, genres):
    prompt = f"""
    Generate 4 to 6 relevant, aesthetic hashtags for this track:
    Artist: {performer}
    Title: {title}
    Genres: {', '.join(genres) if genres else 'Unknown'}
    
    STRICT RULES:
    1. Output ONLY the hashtags separated by spaces (e.g., #Melancholy #DarkVibe #Persian).
    2. No introductions, no extra text, no bullet points.
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip().replace("```", "")
    except Exception:
        return None

def main():
    if not GEMINI_KEY:
        return

    log_data = daily_logger.load_log()
    if not log_data:
        return

    processed_message_ids = []

    for track in log_data:
        message_id = track["message_id"]
        raw_caption = track.get("caption", "")
        base_caption = html.escape(raw_caption) if raw_caption else ""
        
        # Condition Checkers
        needs_full_caption = not base_caption.strip()
        needs_hashtags = bool(base_caption.strip()) and ("#" not in base_caption)
        
        # If track is fully configured, skip processing and remove from log
        if not needs_full_caption and not needs_hashtags:
            processed_message_ids.append(message_id)
            continue

        new_caption = base_caption

        # Apply AI mutations based on the condition
        if needs_full_caption:
            ai_text = generate_vibe_caption(track["performer"], track["title"], track["genres"])
            if not ai_text:
                continue
            new_caption = ai_text
            
        elif needs_hashtags:
            tags_text = generate_hashtags(track["performer"], track["title"], track["genres"])
            if not tags_text:
                continue
            new_caption = f"{base_caption}\n\n{tags_text}"
            
        # Enforce Telegram caption limits
        if len(new_caption) > 1024:
            new_caption = new_caption[:1020] + "..."
            
        # Push update to Telegram
        result = telegram_client.edit_message_caption(message_id, new_caption)
        
        # If successful or ignored due to Telegram rules, mark as done
        if result and (result.get("ok") or result.get("ignored")):
            processed_message_ids.append(message_id)
            
        # Avoid hitting API limits
        time.sleep(4)

    # Clean up the log file by removing processed tracks
    if processed_message_ids:
        daily_logger.remove_tracks(processed_message_ids)

if __name__ == "__main__":
    main()