"""Text-to-speech behind a tiny interface so providers are swappable (cost vs quality)."""
from __future__ import annotations

import os
from pathlib import Path

from ..budget import Budget
from ..config import Config

# Rough ElevenLabs-style cost per 1k characters; verify against your actual plan.
USD_PER_1K_CHARS = 0.30


def synthesize(cfg: Config, budget: Budget, text: str, out_path: Path) -> Path | None:
    if cfg.voice_provider == "none":
        return None  # dry run: no audio, no cost
    if cfg.voice_provider == "elevenlabs":
        import httpx

        budget.charge(len(text) / 1000 * USD_PER_1K_CHARS, "voice synthesis")
        r = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{cfg.voice_id}",
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            json={"text": text, "model_id": "eleven_multilingual_v2"},
            timeout=120,
        )
        r.raise_for_status()
        out_path.write_bytes(r.content)
        return out_path
    raise ValueError(f"unknown voice provider: {cfg.voice_provider}")
