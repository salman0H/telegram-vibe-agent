import os
import time
import json
import html
import re
import urllib.request
import urllib.parse
import urllib.error
import telegram_client
from content_memory import MEMORY_FILE, load_memory, load_corpus, remember, save_json
from editorial import SYSTEM_PROMPT, make_brief, validate_response

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
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.75,
        "max_tokens": 1600,
        "response_format": {"type": "json_object"}
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
            choice = res_data.get("choices", [])[0]
            finish_reason = choice.get("finish_reason", "unknown")
            content = choice.get("message", {}).get("content", "")
            print(f"[Groq API] finish_reason={finish_reason}, content_length={len(content)}")
            if finish_reason == "length":
                print("[Groq Warning] Truncated response rejected.")
                return None
            return content.strip() if content else None
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        print(f"[Groq HTTP Error] Code {e.code}: {err_msg}")
    except Exception as e:
        print(f"[Groq Network Error] Exception: {e}")
        
    return None

def generate_ai_content(performer, title, needs_caption, needs_tags, memory, corpus, genres=None):
    """Generate, check and retry at most three times; never publish a bad fallback."""
    genre = ", ".join(genres) if genres else fetch_itunes_metadata(performer, title)
    feedback = None
    for attempt in range(3):
        brief = make_brief(performer, title, genre, needs_caption, needs_tags, memory, corpus)
        if feedback:
            brief["revision_needed"] = feedback
        raw = call_groq(SYSTEM_PROMPT, json.dumps(brief, ensure_ascii=False))
        if not raw:
            return None
        try:
            return validate_response(raw, brief, memory, corpus)
        except ValueError as error:
            feedback = str(error)
            print(f"[Curator] Rejected candidate {attempt + 1}/3: {feedback}")
    return None

def main():
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")
    if not os.path.exists(LOG_FILE):
        print(f"[Curator] {LOG_FILE} does not exist. Execution skipped.")
        return
    with open(LOG_FILE, encoding="utf-8") as stream:
        log_data = json.load(stream)
    memory, corpus = load_memory(), load_corpus()
    if not isinstance(log_data, list):
        raise ValueError("The pending queue must be a JSON array")
    queued_keys = {str(track["message_id"]) for track in log_data}
    # Finish cleanup if an earlier run removed a queue item before journal cleanup.
    for key in list(memory["pending"]):
        if key not in queued_keys:
            remember(memory, memory["pending"].pop(key))
            save_json(MEMORY_FILE, memory)
    remaining = list(log_data)
    for track in log_data:
        message_id = track["message_id"]
        key = str(message_id)
        raw_caption = track.get("caption", "")
        base_caption = html.escape(raw_caption, quote=False)
        needs_caption = not raw_caption.strip()
        # Preserve the existing policy: blank posts get a sentence only;
        # existing captions receive tags only when they have none.
        needs_tags = bool(raw_caption.strip()) and "#" not in raw_caption
        if not needs_caption and not needs_tags:
            if key in memory["pending"]:
                remember(memory, memory["pending"].pop(key))
                save_json(MEMORY_FILE, memory)
            remaining = [t for t in remaining if t["message_id"] != message_id]
            save_json(LOG_FILE, remaining)
            continue
        record = memory["pending"].get(key)
        if record and record.get("original_caption") != raw_caption:
            # Reserve the old source conservatively: a previous edit may have succeeded.
            remember(memory, record)
            del memory["pending"][key]
            save_json(MEMORY_FILE, memory)
            record = None
        if record is None:
            record = generate_ai_content(
                track.get("performer", "Unknown"), track.get("title", "Unknown"),
                needs_caption, needs_tags, memory, corpus, track.get("genres"))
            if not record:
                print(f"[Curator] No acceptable content for {message_id}; retained in queue.")
                continue
            caption = record["caption"] if needs_caption else base_caption + "\n\n" + record["caption"]
            # Telegram measures caption length after entity parsing in UTF-16 units.
            if len(html.unescape(re.sub(r"</?b>", "", caption)).encode("utf-16-le")) // 2 > 1024:
                print(f"[Curator] Caption {message_id} exceeds Telegram limit; retained unchanged.")
                continue
            record.update(caption=caption, original_caption=raw_caption)
            memory["pending"][key] = record
            # Write-ahead journal: a retry edits the SAME post with the SAME caption,
            # including when Telegram succeeded but the response was lost.
            save_json(MEMORY_FILE, memory)
        result = telegram_client.edit_message_caption(message_id, record["caption"])
        if result and (result.get("ok") or result.get("ignored")):
            remember(memory, record)
            # Keep the journal until queue removal is durable.
            save_json(MEMORY_FILE, memory)
            remaining = [t for t in remaining if t["message_id"] != message_id]
            save_json(LOG_FILE, remaining)
            del memory["pending"][key]
            save_json(MEMORY_FILE, memory)
            print(f"[Curator] Updated message {message_id}.")
        else:
            print(f"[Curator] Edit {message_id} failed; pending caption reserved for retry.")
        time.sleep(3)
    print(f"[Curator] Finished; {len(remaining)} tracks remaining.")


if __name__ == "__main__":
    main()
