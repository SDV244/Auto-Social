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

## Status

Verified here: unit tests, SRT generation, ffmpeg rendering of a 1080x1920 video.
**Not verified yet:** live YouTube search/captions (the build sandbox blocks YouTube), the ElevenLabs call, and a real Claude script run. Run `research` and `make` once on your machine and check the output before relying on them.

Placeholder visuals: the renderer uses a plain background. Next step is screen-recording clips per beat (the `visual` field already says what to show).

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
