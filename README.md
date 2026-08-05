# 🎵 Poetic Vibe Curator (Telegram Serverless Agent)

Welcome to the most dramatic, automated, and serverless Telegram music curator on GitHub. 

This project is a two-phase, ephemeral-state agent that silently watches a Telegram public channel, analyzes newly uploaded audio tracks, fetches metadata, and uses AI to inject deep, melancholic, and poetic captions (in Persian and English)—all while you sleep. 

No databases. No servers. Just pure GitHub Actions magic, OpenSSL cryptography, and AI-driven literature. 🍷✨

---

## 🏗 System Architecture

Telegram bots are restricted from reading channel history (`BotMethodInvalid` on `get_chat_history`). To bypass this without deploying a heavy MTProto userbot, this system implements a **Two-Phase Serverless Architecture** running entirely on GitHub Actions runners.

### Phase 1: The Listener (`music_listener.py`)
Runs every few hours. It acts as an offset-based radar.
* Hits the `getUpdates` method to catch newly uploaded channel posts.
* Extracts the audio file, queries the **iTunes API** for precise metadata and genres.
* Logs the pending tracks into a local `daily_log.json`.
* **State Management:** Because GitHub Actions runners are ephemeral, the `offset` state and pending logs are compressed into a `tar.gz` archive, encrypted symmetrically using `openssl aes-256-cbc`, and forcefully committed back to the repository.

### Phase 2: The AI Curator (`daily_ai_curator.py`)
Runs at Midnight (Tehran Time). The Ghostwriter.
* Decrypts the state and reads the pending tracks.
* Sends the track metadata to the **Google Gemini API** with a highly specific prompt to generate:
  1. An atmospheric Persian paragraph.
  2. A unique quote from Persian literature or cinema (e.g., Shamloo, Ebtehaj, Kiarostami).
  3. An elevated, poetic English sentence.
* Uses Telegram's `editMessageCaption` to **seamlessly mutate** the original post without sending a new message or using annoying replies.
* Cleans up the log and re-encrypts the state.

---

## 🚀 Tech Stack & Core Technologies

This project stands on the shoulders of these fantastic technologies:

* **[Python 3.12](https://www.python.org/):** The core engine. Zero bloated dependencies (uses built-in `urllib` instead of `requests` for Telegram client to keep cold-starts blazing fast).
* **[GitHub Actions](https://github.com/features/actions):** Serves as our Serverless Cron-job orchestrator and ephemeral runtime environment.
* **[Google Gemini API (2.5 Flash)](https://ai.google.dev/):** The brain behind the poetic curation, configured with strict generation parameters to output clean HTML.
* **[Telegram Bot API](https://core.telegram.org/bots/api):** For `getUpdates` and `editMessageCaption` endpoints.
* **[iTunes Search API](https://affiliate.itunes.apple.com/resources/documentation/itunes-store-web-service-search-api/):** For accurate track, artist, and genre resolution.
* **[OpenSSL](https://www.openssl.org/):** Secures the database. The state is AES-256 encrypted before every commit to ensure no API offsets or local logs are exposed in plaintext.

---

## 🛠 Setup & Deployment

Want to run your own ghostwriter? Here is how to set it up:

1. **Clone the repo** and ensure the directory structure matches the source (`scripts/`, `.github/workflows/`).
2. **Create GitHub Repository Secrets:**
   * `MUSIC_BOT_TOKEN`: Your Telegram Bot Token (must be an admin in the channel).
   * `MUSIC_CHANNEL_ID`: Your target channel ID (e.g., `-100123456789`).
   * `GEMINI_API_KEY`: Your Google AI Studio API Key.
   * `DB_PASSWORD`: A strong password to encrypt/decrypt the state files (`music_state.enc`).
3. **Initialize the State (Optional but recommended):**
   Run the listener locally once to generate the initial offset, encrypt it, and push it, or simply let the first GitHub Action run fail gracefully and create it for you.
4. **Enable Actions:** Go to your repository's "Actions" tab and enable the workflows.

---

## 🔒 Security Note

*Why encrypt a simple JSON file?* 
Because committing raw state files to a repository (especially public ones) is bad practice. By using `openssl aes-256-cbc -pbkdf2` inside the CI/CD pipeline, we ensure that our state database remains completely opaque and secure, while fully utilizing GitHub as a free, version-controlled storage backend.

---

### *"Music expresses that which cannot be put into words and that which cannot remain silent." — Victor Hugo (and now, this bot).*
