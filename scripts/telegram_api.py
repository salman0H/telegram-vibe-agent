import os
import json
import mimetypes
import uuid
import urllib.request
from urllib.error import HTTPError

def get_updates(bot_token, offset=None):
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    if offset:
        url += f"?offset={offset}"
    
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            return data.get("result", [])
    except Exception as e:
        print(f"[Telegram API] getUpdates Error: {e}")
        return []

def send_message(bot_token, chat_id, text, reply_to_message_id=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
        
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"[Telegram API] sendMessage Exception: {e}")
    return None

def edit_message_text(bot_token, chat_id, message_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        pass
    return None

def send_audio(bot_token, chat_id, audio_path, caption=""):
    url = f"https://api.telegram.org/bot{bot_token}/sendAudio"
    boundary = uuid.uuid4().hex
    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}

    body = []
    body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n")
    if caption:
        body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n")

    filename = os.path.basename(audio_path)
    mime_type = mimetypes.guess_type(audio_path)[0] or 'audio/mpeg'
    body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{filename}\"\r\nContent-Type: {mime_type}\r\n\r\n")
    
    body_bytes = "".join(body).encode('utf-8')
    
    try:
        with open(audio_path, 'rb') as f:
            audio_bytes = f.read()
    except Exception as e:
        print(f"[Telegram API] Failed to read audio file: {e}")
        return None
        
    footer = f"\r\n--{boundary}--\r\n".encode('utf-8')
    full_data = body_bytes + audio_bytes + footer
    req = urllib.request.Request(url, data=full_data, headers=headers)
    
    try:
        print(f"[Telegram API] Uploading {filename} to Telegram...")
        with urllib.request.urlopen(req, timeout=120) as response:
            res_data = json.loads(response.read().decode())
            return res_data
    except Exception as e:
        print(f"[Telegram API] sendAudio Exception: {e}")
        
    return None
