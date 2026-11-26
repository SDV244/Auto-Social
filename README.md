# Auto-Social

Semi-automated **faceless short-form video pipeline** for the niche *AI tools for business & productivity* (English, US).
Goal: monetize via affiliates, a mailing list and later ad programs, with a human approving everything before it goes out.

```
research -> transcript -> script (Claude) -> voice -> render (ffmpeg) -> draft in runs/ -> YOU approve -> publish
```

## Design choices (economy first)

| Choice | Why |
|---|---|
| Public **captions** instead of download + Whisper | Free and fast. Whisper (local) is only the fallback. |
| Claude with **prompt caching**, one script per video | Cents per video. |
| **Hard monthly budget** (`monthly_budget_usd`, default 100) in `budget.py` | Paid calls refuse to run past the cap. |
| Voice provider `none` by default | Dry runs cost $0. Turn on ElevenLabs only when drafts look good. |
| **Approval queue** (`runs/<id>/status`) | Keeps a human editorial hand on each video. Platforms demonetize templated, repetitive channels. |
| Original angle required in the prompt | The reference video is inspiration for topic/structure, never copied. |

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,research]"        # add ,transcribe for the local Whisper fallback
cp config.example.yaml config.yaml
export ANTHROPIC_API_KEY=...            # and ELEVENLABS_API_KEY if voice.provider=elevenlabs

auto-social research --top 10            # what is trending in the niche
auto-social make --count 1               # builds one draft in runs/<video-id>/
auto-social review
auto-social approve <video-id>
pytest
```

Each draft folder holds `video.mp4`, `captions.srt`, `script.json`, `caption.txt` (with disclosure) and `status`.

## Visuals and editing

Every scene (hook, each beat, CTA) gets a visual chosen by the script (`visual_type`):

| Type | How | Cost |
|---|---|---|
| `screen` | Real page recorded at phone size with Playwright (screenshots encoded by system ffmpeg) | $0 |
| `card` | Text card rendered from HTML by headless Chromium, slow zoom | $0 |
| `stock` | Provider hook in `visuals.stock_clip` (Pixabay API key needed; Pexels paused new keys). Falls back to `card` | $0 |

Any failure degrades to a card so a render always completes. Captions are burned in by ffmpeg/libass.
Install the browser once on your machine: `pip install playwright && playwright install chromium` (or set `PLAYWRIGHT_CHROMIUM_PATH`).

## Voice

`voice.provider: openrouter` (default) uses `openai/gpt-audio-mini` through the same OpenRouter key: measured ~$0.0013 per 6 s of audio, about 1-2 cents per video. One clip is synthesized per scene, so scene length = audio length and captions are timed exactly, with no forced alignment. The model occasionally rambles or pads a clip, so every clip is checked against the expected duration and retried (up to 4 times). ElevenLabs is available as `elevenlabs` (about 10-20x the cost). Always listen to the first drafts before publishing.

## Models

`models.script` (default `deepseek/deepseek-v4-flash`) writes drafts for fractions of a cent; `make --final` uses `models.final` (`anthropic/claude-sonnet-5.5`). Free OpenRouter models were tested: rate-limited (429) and more generic angles, so they are not the default.

## Status

Verified end to end in the cloud sandbox (2026-11): live YouTube search, caption download, scripts through OpenRouter, scene renderer with a real screen recording + text cards + captions.

Known limits:
- YouTube rate-limits/bot-checks datacenter IPs (`429`, "confirm you're not a bot"); upload age may be unknown and some caption downloads fail (those videos are skipped). A home connection is much less affected.
- Captions are phrases of 3-4 words timed by character share inside each scene (exact scene timing, approximate inside a scene).
- Not verified: ElevenLabs voice, Postiz publishing, Pixabay stock. Voice quality needs a human listen (I could not hear it).
- `screen` scenes need the target site reachable; otherwise they become cards.

## Roadmap

1. Run the first 5-10 drafts by hand, tune the prompt in `stages/script.py`.
2. Real visuals (screen recordings / licensed clips) and caption timing from the TTS audio.
3. Publishing through Postiz (API/MCP) **keeping the approval gate**; TikTok and Instagram stay manual until API access is approved.
4. Scheduler (cron / GitHub Actions) on a server instead of a laptop.
5. Landing page + email capture, and real tracked affiliate links in `affiliate_cta`.

## Rules we follow

- Create platform accounts manually; use official APIs only.
- Disclose AI assistance and affiliate links.
- Use a cloned voice only if it is yours or you have consent.
- Never reuse another creator's footage, audio or wording.
