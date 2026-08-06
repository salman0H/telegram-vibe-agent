import os
import time
import json
import html
import urllib.request
import urllib.error
import telegram_client

LOG_FILE = "daily_log.json"

# Define a list of OpenAI-compatible providers for the fallback mechanism.
# The system will attempt them in order. If one fails or lacks a key, it moves to the next.
PROVIDERS = [
    {
        "name": "Groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "env_key": "GROQ_API_KEY",
        "model": "llama3-8b-8192" # Fast and heavily rate-limited friendly
    },
    {
        "name": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "env_key": "OPENROUTER_API_KEY",
        "model": "meta-llama/llama-3-8b-instruct:free" # Always free routing
    },
    {
        "name": "Together",
        "url": "https://api.together.xyz/v1/chat/completions",
        "env_key": "TOGETHER_API_KEY",
        "model": "meta-llama/Llama-3-8b-chat-hf"
    }
]

def call_llm(prompt):
    """
    Sends a prompt to the first available and working LLM provider using pure urllib.
    Returns the generated text or None if all providers fail.
    """
    payload = {
        "messages": [
            {"role": "system", "content": "You are a poetic music curator for a Telegram channel. Output exactly what is requested, no markdown code blocks, no chatty introductions."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.85,
        "max_tokens": 500
    }
    
    data = json.dumps(payload).encode("utf-8")

    for provider in PROVIDERS:
        api_key = os.environ.get(provider["env_key"])
        if not api_key:
            print(f"[LLM Router] Skipping {provider['name']} - No API key found in environment.")
            continue
            
        print(f"[LLM Router] Attempting generation via {provider['name']} (Model: {provider['model']})...")
        
        # Inject the specific model into the payload for this provider
        payload["model"] = provider["model"]
        current_data = json.dumps(payload).encode("utf-8")
        
        req = urllib.request.Request(
            provider["url"],
            data=current_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                # OpenRouter recommends these headers, ignored safely by others
                "HTTP-Referer": "https://github.com/salman0H/telegram-vibe-agent",
                "X-Title": "Telegram Vibe Agent"
            }
        )
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                content = res_data.get("choices", [])[0].get("message", {}).get("content", "")
                
                print(f"[LLM Router] Success with {provider['name']}!")
                # Clean up potential markdown formatting that LLMs tend to add
                return content.replace("```html", "").replace("```", "").strip()
                
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8")
            print(f"[LLM Warning] {provider['name']} HTTP Error {e.code}: {err_msg}")
        except Exception as e:
            print(f"[LLM Warning] {provider['name']} Exception: {e}")
            
    print("[LLM Error] All available providers failed.")
    return None

def generate_vibe_caption(performer, title):
    """Generates the main artistic caption."""
    prompt = f"""
    Generate Telegram caption in EXACT HTML format. No markdown blocks.
    Artist: {performer}, Title: {title}
    
    [Vibe Emoji] {performer} - {title}
    
    [One Persian paragraph describing the emotional mood of the song]
    
    <blockquote><b>«[Unique Persian literary or cinematic quote matching the vibe]»</b></blockquote>
    <blockquote><b>"[Unique poetic English sentence matching the vibe]"</b></blockquote>
    """
    return call_llm(prompt)

def generate_hashtags(performer, title):
    """Generates tags separately to ensure they are added."""
    prompt = f"Generate 4 to 6 relevant hashtags for the song: {performer} - {title}. Output ONLY tags separated by spaces. Example: #Pop #Music #Vibe"
    return call_llm(prompt)

def main():
    # Check if we have at least ONE working key
    has_keys = any(os.environ.get(p["env_key"]) for p in PROVIDERS)
    if not has_keys:
        print("[Error] No API keys configured. Set GROQ_API_KEY, OPENROUTER_API_KEY, or TOGETHER_API_KEY.")
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

        # 1. Process Caption (if needed)
        if needs_caption:
            ai_text = generate_vibe_caption(track.get("performer", "Unknown"), track.get("title", "Unknown"))
            if ai_text:
                new_caption = ai_text
            else:
                print(f"[Curator] Failed to get AI caption for message {message_id}. Retaining in log.")
                continue # Skip to next track if main caption fails
                
        # 2. Process Hashtags (if needed) - Fixed logic: Independent sequential step, not elif!
        if needs_tags or needs_caption: 
            # If it needed a caption, it inherently needs tags appended now
            tags_text = generate_hashtags(track.get("performer", "Unknown"), track.get("title", "Unknown"))
            if tags_text:
                # Append tags gracefully
                new_caption = f"{new_caption}\n\n{tags_text}" if new_caption else tags_text
            else:
                print(f"[Curator] Warning: Failed to generate hashtags for {message_id}. Proceeding without them.")
            
        if len(new_caption) > 1024:
            new_caption = new_caption[:1020] + "..."
            
        # 3. Edit Message in Telegram
        result = telegram_client.edit_message_caption(message_id, new_caption)
        
        if result and (result.get("ok") or result.get("ignored")):
            success_ids.append(message_id)
        else:
            print(f"[Curator] Telegram edit failed for message {message_id}. Retaining in log.")
            
        time.sleep(3) # Rate limit protection

    # Save remaining uncompleted tracks back to log
    remaining_tracks = [t for t in log_data if t["message_id"] not in success_ids]
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(remaining_tracks, f, ensure_ascii=False, indent=2)
        
    print(f"[Curator] Execution finished. {len(success_ids)} tracks updated. {len(remaining_tracks)} remaining in log.")

if __name__ == "__main__":
    main()