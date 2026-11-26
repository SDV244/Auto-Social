"""Text-to-speech, one clip per scene (hook, each beat, CTA).

One clip per scene gives exact durations (scene length = audio length), so captions and
visuals stay in sync with no forced alignment. Providers:

openrouter  openai/gpt-audio-mini through the key you already use (~$0.0002 per second of audio, measured)
elevenlabs  higher-end voices, ~10-20x the cost
none        dry run, no audio, no cost
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import wave
from pathlib import Path

from ..budget import Budget
from ..config import Config
from ..models import Script

SAMPLE_RATE = 24000
USD_PER_CHAR = {"openrouter": 0.00002, "elevenlabs": 0.0003}  # conservative estimates for the budget guard
NARRATOR = (
    "Text-to-speech engine for short videos. Speak ONLY the exact text between <text> tags, once, then stop. "
    "No greetings, no commentary, no extra words. Confident, warm, brisk, natural delivery."
)
MAX_ATTEMPTS = 4
WORDS_PER_SEC = 2.3  # observed narration pace


def max_plausible_seconds(text: str) -> float:
    """Upper bound for a faithful read of `text`; longer clips mean the model rambled or padded."""
    return max(3.0, len(text.split()) / WORDS_PER_SEC * 1.6 + 1.0)


def scene_texts(script: Script) -> list[str]:
    """Same order as render.scenes(): hook, beats, cta."""
    return [script.hook] + [b.voiceover for b in script.beats] + [script.cta]


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def _openrouter(cfg: Config, text: str, out: Path) -> Path:
    import httpx

    headers = {"Content-Type": "application/json"}
    if os.environ.get("OPENROUTER_API_KEY"):  # in the cloud sandbox the proxy injects the key
        headers["Authorization"] = f"Bearer {os.environ['OPENROUTER_API_KEY']}"
    body = {
        "model": cfg.voice_model,
        "modalities": ["text", "audio"],
        "audio": {"voice": cfg.voice_id or "onyx", "format": "pcm16"},
        "stream": True,
        "messages": [{"role": "system", "content": NARRATOR}, {"role": "user", "content": f"<text>{text}</text>"}],
    }
    pcm = b""
    with httpx.stream("POST", "https://openrouter.ai/api/v1/chat/completions", json=body, headers=headers, timeout=120) as r:
        if r.status_code != 200:
            raise RuntimeError(f"voice request failed: {r.status_code} {r.read()[:200]!r}")
        for line in r.iter_lines():
            if line.startswith("data: {"):
                for ch in json.loads(line[6:]).get("choices", []):
                    a = (ch.get("delta") or {}).get("audio")
                    if a and a.get("data"):
                        pcm += base64.b64decode(a["data"])
    if not pcm:
        raise RuntimeError("voice request returned no audio")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return out


def _elevenlabs(cfg: Config, text: str, out: Path) -> Path:
    import httpx

    r = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{cfg.voice_id}",
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={"text": text, "model_id": "eleven_multilingual_v2"},
        timeout=120,
    )
    r.raise_for_status()
    mp3 = out.with_suffix(".mp3")
    mp3.write_bytes(r.content)
    subprocess.run(["ffmpeg", "-y", "-i", str(mp3), "-ar", str(SAMPLE_RATE), "-ac", "1", str(out)], check=True, capture_output=True)
    return out


def synthesize_scenes(cfg: Config, budget: Budget, script: Script, workdir: Path) -> list[Path] | None:
    """One WAV (24 kHz mono) per scene, or None when voice.provider is 'none'."""
    if cfg.voice_provider == "none":
        return None
    if cfg.voice_provider not in USD_PER_CHAR:
        raise ValueError(f"unknown voice provider: {cfg.voice_provider}")
    texts = scene_texts(script)
    budget.charge(sum(len(t) for t in texts) * USD_PER_CHAR[cfg.voice_provider], "voice synthesis")
    workdir.mkdir(parents=True, exist_ok=True)
    fn = _openrouter if cfg.voice_provider == "openrouter" else _elevenlabs
    paths = []
    for i, text in enumerate(texts):
        out = workdir / f"voice_{i:02}.wav"
        for attempt in range(MAX_ATTEMPTS):
            try:
                fn(cfg, text, out)
                if wav_duration(out) <= max_plausible_seconds(text):
                    break
                err = f"clip too long ({wav_duration(out):.1f}s for {len(text.split())} words)"
            except Exception as e:
                err = str(e)
            if attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(f"voice scene {i} failed after {MAX_ATTEMPTS} attempts: {err}")
        paths.append(out)
    return paths


def concat_audio(paths: list[Path], out: Path) -> Path:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in paths))
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "aac", str(out)], check=True, capture_output=True)
    return out
