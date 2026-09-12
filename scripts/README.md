# Episode pipeline

Content (news research + script writing) happens outside GitHub, in a
sandboxed environment whose network policy blocks `edge-tts` and most
external TTS APIs. Audio synthesis happens here instead, via GitHub
Actions, which has normal internet access.

## Handoff

Each day, three files are written to `scripts/pending/` and pushed to `main`:

- `en.txt` — the English script (plain text, blank line between paragraphs)
- `ko.txt` — the Korean script (same format)
- `meta.json` — `{"date": "YYYY-MM-DD", "title": "...", "description": "..."}`

Pushing those files triggers `.github/workflows/tts.yml`, which runs
`scripts/build_episode.py`. That script:

1. Synthesizes `en.txt` with `edge-tts` (`en-AU-NatashaNeural`) and `ko.txt`
   with `edge-tts` (`ko-KR-SunHiNeural`).
2. Concatenates the two with a short silence gap into
   `docs/audio/brief-<date>.mp3`.
3. Prepends a new `<item>` to `docs/feed.xml` and prunes entries (and their
   audio files) older than 30 days.
4. Updates the "latest episode" section of `docs/index.html`.
5. Deletes the consumed files in `scripts/pending/` and commits everything.

If `scripts/pending/` is empty, the workflow is a no-op.
