"""Build subtitles and the ffmpeg command for a 1080x1920 video.

Visuals: drop screen recordings / clips into `assets/` and name them in each beat's
`visual`; with no clip the renderer falls back to a plain branded background so the
pipeline always produces something reviewable.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..models import Script


def _ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def beat_timings(script: Script, words_per_sec: float = 2.6) -> list[tuple[float, float, str]]:
    """Estimate caption timing from word count. Replace with real alignment once TTS audio exists."""
    t, out = 0.0, []
    for text in [script.hook] + [b.voiceover for b in script.beats] + [script.cta]:
        dur = max(1.2, len(text.split()) / words_per_sec)
        out.append((t, t + dur, text))
        t += dur
    return out


def to_srt(script: Script) -> str:
    blocks = []
    for i, (a, b, text) in enumerate(beat_timings(script), 1):
        blocks.append(f"{i}\n{_ts(a)} --> {_ts(b)}\n{text}\n")
    return "\n".join(blocks)


def ffmpeg_command(srt: Path, out: Path, duration: float, audio: Path | None = None) -> list[str]:
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x101820:s=1080x1920:d={duration:.2f}:r=30"]
    if audio:
        cmd += ["-i", str(audio)]
    style = "FontSize=18,Alignment=2,MarginV=260,Outline=2,PrimaryColour=&H00FFFFFF"
    cmd += ["-vf", f"subtitles={srt}:force_style='{style}'", "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-shortest"] if audio else []
    return cmd + [str(out)]


def run(script: Script, workdir: Path, audio: Path | None = None) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    srt = workdir / "captions.srt"
    srt.write_text(to_srt(script))
    duration = beat_timings(script)[-1][1]
    out = workdir / "video.mp4"
    subprocess.run(ffmpeg_command(srt, out, duration, audio), check=True, capture_output=True)
    return out
