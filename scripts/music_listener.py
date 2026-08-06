import os
import json
import asyncio
from telethon import TelegramClient

API_ID = int(os.environ.get("TG_API_ID", 0))
API_HASH = os.environ.get("TG_API_HASH", "")
BOT_TOKEN = os.environ.get("MUSIC_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("MUSIC_CHANNEL_ID", "")
LOG_FILE = "daily_log.json"

async def main():
    if not all([API_ID, API_HASH, BOT_TOKEN, CHANNEL_ID]):
        return

    client = TelegramClient('bot_session', API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)

    try:
        target_channel = int(CHANNEL_ID)
    except ValueError:
        target_channel = CHANNEL_ID

    extracted_tracks = []
    existing_log = []
    
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            try:
                existing_log = json.load(f)
            except Exception:
                pass
                
    existing_ids = {track["message_id"] for track in existing_log}

    async for message in client.iter_messages(target_channel, limit=100):
        if message.audio:
            raw_caption = message.text or ""
            needs_caption = not raw_caption.strip()
            needs_tags = bool(raw_caption.strip()) and ("#" not in raw_caption)

            if needs_caption or needs_tags:
                if message.id not in existing_ids:
                    performer, title = "Unknown", "Unknown"
                    for attr in message.document.attributes:
                        if hasattr(attr, 'performer'):
                            performer = attr.performer or performer
                            title = attr.title or title
                            break
                            
                    extracted_tracks.append({
                        "message_id": message.id,
                        "performer": performer,
                        "title": title,
                        "genres": [],
                        "caption": raw_caption,
                        "timestamp": message.date.timestamp()
                    })

    existing_log.extend(extracted_tracks)
    
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_log, f, ensure_ascii=False, indent=2)

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())