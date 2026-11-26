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
ENERGETIC = (
    "You are a text-to-speech engine, not an assistant. Read EXACTLY the words between <text> tags, once, "
    "and stop immediately after the last word. You may NOT add, extend, comment on or improvise anything. "
    "Delivery: high-energy, punchy and upbeat like a top TikTok creator, fast pace, strong emphasis on key words, "
    "lively intonation, a hint of a smile, short sharp pauses at full stops. Never monotone."
)
CALM = (
    "You are a text-to-speech engine, not an assistant. Read EXACTLY the words between <text> tags, once, "
    "and stop immediately after the last word. Add nothing. Confident, warm, brisk delivery."
)
NARRATOR = ENERGETIC  # kept for backwards compatibility
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


def _openrouter(cfg: Config, text: str, out: Path, voice: str | None = None, style: str = ENERGETIC) -> str:
    """Synthesize `text` into `out` (WAV). Returns the transcript of what the model actually said."""
    import httpx

    headers = {"Content-Type": "application/json"}
    if os.environ.get("OPENROUTER_API_KEY"):  # in the cloud sandbox the proxy injects the key
        headers["Authorization"] = f"Bearer {os.environ['OPENROUTER_API_KEY']}"
    body = {
        "model": cfg.voice_model,
        "modalities": ["text", "audio"],
        "audio": {"voice": voice or cfg.voice_id or "ash", "format": "pcm16"},
        "stream": True,
        "messages": [{"role": "system", "content": style}, {"role": "user", "content": f"<text>{text}</text>"}],
    }
    pcm, transcript = b"", ""
    with httpx.stream("POST", "https://openrouter.ai/api/v1/chat/completions", json=body, headers=headers, timeout=120) as r:
        if r.status_code != 200:
            raise RuntimeError(f"voice request failed: {r.status_code} {r.read()[:200]!r}")
        for line in r.iter_lines():
            if line.startswith("data: {"):
                for ch in json.loads(line[6:]).get("choices", []):
                    a = (ch.get("delta") or {}).get("audio")
                    if a and a.get("data"):
                        pcm += base64.b64decode(a["data"])
                    if a and a.get("transcript"):
                        transcript += a["transcript"]
    if not pcm:
        raise RuntimeError("voice request returned no audio")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return transcript


def _elevenlabs(cfg: Config, text: str, out: Path, voice: str | None = None, style: str = "") -> str:
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
    return ""


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
    plan = attempt_plan(cfg)
    paths = []
    for i, text in enumerate(texts):
        out = workdir / f"voice_{i:02}.wav"
        err = ""
        for voice_name, style in plan:
            try:
                transcript = fn(cfg, text, out, voice_name, style)
                if wav_duration(out) > max_plausible_seconds(text):
                    err = f"clip too long ({wav_duration(out):.1f}s for {len(text.split())} words)"
                elif transcript and len(transcript.split()) > len(text.split()) + 2:
                    err = f"model improvised: said {len(transcript.split())} words for {len(text.split())}"
                else:
                    break
            except Exception as e:
                err = str(e)
        else:
            raise RuntimeError(f"voice scene {i} failed after {len(plan)} attempts: {err}")
        fast = workdir / f"voicefast_{i:02}.wav"
        paths.append(polish(out, fast, cfg.voice_speed))
    return paths


def attempt_plan(cfg: Config) -> list[tuple[str, str]]:
    """Voice/style per attempt. The voice never changes within a video: retries only vary the style."""
    voice_name = cfg.voice_id or "ash"
    return [(voice_name, ENERGETIC)] * 4 + [(voice_name, CALM)]


def polish(src: Path, dst: Path, speed: float) -> Path:
    """Trim leading/trailing silence and speed up without changing pitch."""
    trim = "silenceremove=start_periods=1:start_silence=0.03:start_threshold=-45dB"
    af = f"{trim},areverse,{trim},areverse"
    if abs(speed - 1.0) > 0.01:
        af += f",atempo={speed}"
    af += ",loudnorm=I=-16:TP=-1.5:LRA=7"  # same loudness in every scene so it sounds like one take
    subprocess.run(["ffmpeg", "-y", "-i", str(src), "-af", af, "-ar", str(SAMPLE_RATE), "-ac", "1", str(dst)], check=True, capture_output=True)
    return dst


def concat_audio(paths: list[Path], out: Path) -> Path:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in paths))
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "aac", str(out)], check=True, capture_output=True)
    return out
