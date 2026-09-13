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

## Multiple shows

This repo can publish more than one independent podcast, each with its own
feed and subscribe URL. The main show above uses the flat
`scripts/pending/{en.txt,ko.txt,meta.json}` layout and publishes to `docs/`
at the site root (`.../morning-brief-podcast/feed.xml`).

Any other show is a subdirectory: `scripts/pending/<show_id>/{en.txt,ko.txt,meta.json}`.
Its `meta.json` must include a `"show"` object so the build script knows
where to publish it and how to bootstrap its feed the first time:

```json
{
  "date": "2026-09-14",
  "title": "Morning Brief — Monday, 14 September 2026",
  "description": "...",
  "show": {
    "docs_subdir": "ksb",
    "site_base": "https://rogineh.github.io/morning-brief-podcast/ksb",
    "channel_title": "Morning Brief — Australia Edition",
    "channel_description": "..."
  }
}
```

This publishes into `docs/<docs_subdir>/` with its own `feed.xml` and
`index.html`, at `<site_base>/feed.xml` — a fully separate subscribe URL,
pruned and updated independently of the main show. `channel_title` and
`channel_description` are only used the first time that show's feed.xml is
created; later episodes for the same show can omit them.

The current second show is `ksb` (`docs/ksb/`) — an Australia/
Queensland/Gold Coast-only edition with no tech or AI segment, at
`https://rogineh.github.io/morning-brief-podcast/ksb/feed.xml`. It has
its own daily Routine that writes to `scripts/pending/ksb/`.
