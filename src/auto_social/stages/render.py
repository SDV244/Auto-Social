"""Scene-based renderer: one clip per scene (hook, beats, cta), concatenated with audio + captions.

Each scene uses its beat's visual (screen recording / stock / text card); anything that
fails or is not configured degrades to a text card, so a render always completes.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..models import Script
from . import visuals

FPS = 30


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


def scenes(script: Script) -> list[dict]:
    """Scene list aligned with beat_timings: hook, each beat, cta."""
    items = [{"type": "card", "ref": "", "text": script.title}]
    for b in script.beats:
        items.append({"type": b.visual_type, "ref": b.visual_ref, "text": b.on_screen_text or b.voiceover})
    items.append({"type": "card", "ref": "", "text": script.cta})
    for it, (a, b, _) in zip(items, beat_timings(script)):
        it["duration"] = b - a
    return items


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def _still_clip(png: Path, dur: float, out: Path) -> None:
    frames = int(dur * FPS)
    vf = f"zoompan=z='min(zoom+0.0007,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps={FPS},format=yuv420p"
    _run(["ffmpeg", "-y", "-i", str(png), "-vf", vf, "-frames:v", str(frames), "-c:v", "libx264", str(out)])


def _video_clip(src: Path, dur: float, out: Path) -> None:
    vf = f"scale=1080:1920,fps={FPS},tpad=stop_mode=clone:stop_duration={dur:.2f},format=yuv420p"
    _run(["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-t", f"{dur:.2f}", "-an", "-c:v", "libx264", str(out)])


def build_clips(script: Script, workdir: Path) -> list[Path]:
    clips = []
    for i, sc in enumerate(scenes(script)):
        out = workdir / f"scene_{i:02}.mp4"
        raw = None
        if sc["type"] == "screen":
            raw = visuals.screen_clip(sc["ref"], sc["duration"], workdir / f"scene_{i:02}_screen.mp4")
        elif sc["type"] == "stock":
            raw = visuals.stock_clip(sc["ref"], sc["duration"], workdir / f"scene_{i:02}_stock.mp4")
        if raw:
            _video_clip(raw, sc["duration"], out)
        else:
            png = visuals.card_png(sc["text"], workdir / f"scene_{i:02}.png")
            _still_clip(png, sc["duration"], out)
        clips.append(out)
    return clips


def final_command(concat_list: Path, srt: Path, out: Path, audio: Path | None = None) -> list[str]:
    # libass scales style units to a 384x288 canvas: MarginV=48 is ~320px from the bottom of a 1920px frame
    style = "FontSize=12,Alignment=2,MarginV=48,Outline=3,Bold=1,PrimaryColour=&H00FFFFFF"
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list)]
    if audio:
        cmd += ["-i", str(audio)]
    cmd += ["-vf", f"subtitles={srt}:force_style='{style}'", "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-shortest"] if audio else []
    return cmd + [str(out)]


def run(script: Script, workdir: Path, audio: Path | None = None) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    srt = workdir / "captions.srt"
    srt.write_text(to_srt(script))
    clips = build_clips(script, workdir)
    concat = workdir / "scenes.txt"
    concat.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    out = workdir / "video.mp4"
    _run(final_command(concat, srt, out, audio))
    return out
