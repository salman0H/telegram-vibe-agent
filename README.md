# Poetic Vibe Curator

A serverless Telegram music agent that runs on GitHub Actions. It accepts an administrator's music requests, watches channel audio uploads, and edits the original posts with minimalist Persian or English captions using Groq. Python scripts use the standard library; the download workflow also installs `yt-dlp` and FFmpeg.

## Channel rules

The channel's existing behavior is preserved:

- An empty caption receives one short poetic sentence, in bold and quotation marks, ending in a period. Iranian/Persian music gets Persian text; international music gets English text. Romanized Persian metadata is considered by the model.
- A manually written caption is preserved. If it has no `#`, the agent appends 3–4 hashtags; Persian music receives 1–2 Persian hashtags.
- A nonempty caption already containing `#` is left alone.
- Captions contain no emoji, artist names, song titles, or explanatory commentary.
- The agent edits the original audio message rather than creating another channel post.

Empty captions still receive a sentence only, following the original decision logic. The system has artist/title metadata and an optional iTunes genre, **not an audio transcription or listening analysis**.

## How it works

1. **Downloader — `scripts/agent_downloader.py`:** accepts text requests or forwarded audio from `ADMIN_USER_ID`, downloads/converts the track, uploads it to the channel, and adds it to `daily_log.json`.
2. **Listener — `scripts/music_listener.py`:** polls Telegram channel updates, filters the configured channel and audio messages, deduplicates queued message IDs, and queues posts needing captions or tags.
3. **Curator — `scripts/daily_ai_curator.py`:** uses queued genres when available, otherwise searches iTunes once per track. It generates [JSON-mode output](https://console.groq.com/docs/structured-outputs) through Groq's `openai/gpt-oss-120b`, validates the result, renders safe Telegram HTML, and edits the post.
4. **Editorial memory — `scripts/content_memory.py`:** stores used source IDs, normalized caption fingerprints, the latest 100 captions and editorial choices, and pending edits in `content_memory.json`. Actions commit this file alongside the queue so memory survives fresh runners.

State remains repository-backed JSON. The current workflows do **not** encrypt it or require Gemini/`DB_PASSWORD`.

## Reducing repetition

Random wording instructions alone do not provide memory. This version combines:

- Eight sentence structures and eight imagery lenses. Choices used in the last three successful captions are excluded.
- A small prompt context containing the last 12 successful captions, with instructions to avoid their imagery and phrasing. Stored history remains broader than prompt context.
- A bilingual poetry corpus with source attribution. Selection excludes every used or pending excerpt, favors authors absent from the last three captions, and favors theme words matching track metadata when available.
- Permanent exact-caption fingerprints, normalized for punctuation, HTML entities, Arabic/Persian letter variants, diacritics, and Persian half-spaces.
- Checks against the last 100 captions for similar wording, substantial word overlap, and identical three-word openings. Pending captions are checked too.
- At most three generation attempts for invalid/repetitive outputs, with specific rejection feedback. After that, the track stays queued. Truncated model responses are rejected.

Similarity checks are lexical heuristics; they cannot guarantee that every metaphor is semantically unique. The model chooses the language and emotional interpretation from metadata, so ambiguous artist names can still be misclassified. History starts with the first run of this version; it does not reconstruct old channel captions.

## Poetry corpus and attribution

[`data/poetry.json`](data/poetry.json) contains **48 short excerpts: 24 Persian and 24 English**, from Hafez, Saadi, Rumi, Emily Dickinson, William Shakespeare, Edgar Allan Poe, and William Blake. Each entry includes:

| Field | Meaning |
| --- | --- |
| `id` | Stable excerpt identifier, used to prevent reuse |
| `language` | `fa` or `en` |
| `author`, `work` | Poet and original work |
| `text` | Original-language excerpt |
| `source` | Link to the source text |
| `themes` | Editorial tags for selection and model context |
| `rights` | Original-text rights note |

The corpus uses historical public-domain originals rather than modern translations. Persian sources are linked to [Ganjoor](https://ganjoor.net/); English sources are linked to the [Poetry Foundation](https://www.poetryfoundation.org/poems). Specific source URLs are stored with every excerpt.

The corpus is an **inspiration library**: captions are newly written, not presented as quotations from these poets. The selected poet is recorded in editorial memory; their name is not appended to the channel caption. The validator rejects full copied excerpts. The prompt also prohibits borrowing signature images or falsely attributing generated text.

An excerpt is reserved before Telegram is called and marked used after a successful edit. Used IDs never rotate out. Once all entries in a language are exhausted, the agent writes original captions without a source; it does not reset the library or reuse old entries. Different excerpts from the same work have separate IDs.

To expand the corpus, add sourced entries with new IDs, verify the exact text and author, and run the tests. Never rename, recycle, or alter used IDs to make an old excerpt appear new. Keep `content_memory.json` in Git; deleting it resets repetition protection.

## Failure recovery and state

Before sending an edit, the curator atomically saves its full caption and source reservation in a write-ahead journal. If Telegram fails or its response is lost, the next run retries **the same caption on the same message**. Telegram's “message is not modified” response counts as success. Successful usage is saved before queue removal; writes use a temporary file and atomic replacement.

Oversized captions are left queued rather than cut through an HTML tag or a manual caption. Malformed memory fails the run rather than silently erasing used-source history. Restore the latest valid `content_memory.json` from Git if needed.

All three state-writing workflows share the `music-agent-state` concurrency group. This serializes runs so queue and memory commits do not overwrite one another. State-saving steps for the curator and downloader run even after an earlier failure. Failed Git rebases/pushes remain visible instead of being ignored. GitHub may replace a pending scheduled run when another run queues in the same group; the next run processes the persisted queue.

| File | Purpose |
| --- | --- |
| `state.json` | Downloader update cursor |
| `music_state.json` | Listener update cursor |
| `daily_log.json` | Tracks pending curation |
| `content_memory.json` | Created on first accepted generation; source/caption history and retry journal |

These files contain channel metadata and generated text and are visible to anyone with repository access. API credentials belong only in GitHub Secrets. A runner lost before its final Git commit can still lose local state; Git-backed persistence is not a transactional database. Run local state-mutating scripts only when Actions are idle.

## Setup

Use Python 3.12. Configure the bot as a channel administrator with permission to post audio and edit messages, then add these repository secrets:

| Secret | Used by |
| --- | --- |
| `MUSIC_BOT_TOKEN` | Downloader, listener, curator |
| `MUSIC_CHANNEL_ID` | Target channel for all three |
| `ADMIN_USER_ID` | Downloader's authorized sender |
| `GROQ_API_KEY` | Curator |

The standalone curator also accepts `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` as fallbacks. Use the `MUSIC_*` pair consistently to avoid different targets between workflows. No new secrets are required for editorial memory.

Enable Actions with repository content-write permission. Each workflow can also be run manually using `workflow_dispatch`.

| Workflow | UTC schedule | Tehran time (UTC+03:30) |
| --- | --- | --- |
| `bot.yml` | Every three hours, starting 00:00 | Every three hours, starting 03:30 |
| `listener.yml` | 04:00, 10:00, 16:00, 22:00 | 01:30, 07:30, 13:30, 19:30 |
| `curator.yml` | 04:30, 10:30, 16:30, 22:30 | 02:00, 08:00, 14:00, 20:00 |

The downloader workflow also invokes the curator after downloading. GitHub cron execution can be delayed. The listener/downloader still use the original Telegram `getUpdates` polling arrangement; this change does not redesign ingestion or recover channel history. Avoid attaching another update consumer or webhook to the same bot.

## Development and verification

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts tests
```

Tests run offline with mocked Groq and Telegram calls. They cover source exhaustion, persistent exact history, Persian normalization, near duplicates, pending reservations, bounded retries, strict output validation, original-caption preservation, HTML length safety, and crash recovery. They never publish to the channel. A separate CI workflow runs these checks on pushes and pull requests.

For an intentional local live run from the repository root, set the appropriate environment variables first:

```sh
python3 scripts/music_listener.py
python3 scripts/daily_ai_curator.py
```

The curator command performs real Telegram edits; use the offline tests for routine development.
