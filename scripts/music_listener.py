import re
import sys
import state
import telegram_client
import itunes_client
import daily_logger

def extract_performer_title(audio):
    performer = audio.get("performer")
    title = audio.get("title")
    if performer and title:
        return performer, title
    file_name = audio.get("file_name", "")
    name_no_ext = re.sub(r"\.\w{2,4}$", "", file_name)
    match = re.match(r"^\s*(.+?)\s*-\s*(.+?)\s*$", name_no_ext)
    if match:
        return performer or match.group(1), title or match.group(2)
    return performer or "Unknown Artist", title or (name_no_ext or "Unknown Title")

def main():
    if not telegram_client.CHANNEL_ID:
        sys.exit(1)

    st = state.load_state()
    updates = telegram_client.get_updates(offset=st.get("offset"))
    if not updates:
        return

    next_offset = st.get("offset") or 0
    
    for update in updates:
        update_id = update.get("update_id", 0)
        if update_id >= next_offset:
            next_offset = update_id + 1

    for message_id, audio, base_caption in telegram_client.iter_channel_audio_posts(updates):
        if state.is_processed(st, message_id):
            continue
            
        performer, title = extract_performer_title(audio)
        genres = []
        
        match = itunes_client.search_track(performer, title)
        if match:
            performer = match["artists"][0] if match["artists"] else performer
            title = match["name"] or title
            if match.get("genres"):
                genres = match["genres"]

        daily_logger.add_track(message_id, performer, title, genres, base_caption)
        state.mark_processed(st, message_id)

    st["offset"] = next_offset
    state.save_state(st)

if __name__ == "__main__":
    main()