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


def timings(script: Script, durations: list[float] | None = None) -> list[tuple[float, float, str]]:
    """Scene timings: real audio durations when given, else estimated from word counts."""
    if not durations:
        return beat_timings(script)
    texts = [script.hook] + [b.voiceover for b in script.beats] + [script.cta]
    t, out = 0.0, []
    for text, d in zip(texts, durations):
        out.append((t, t + d, text))
        t += d
    return out


def phrases(text: str, max_words: int = 4) -> list[str]:
    words = text.split()
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)] or [text]


def to_srt(script: Script, durations: list[float] | None = None) -> str:
    """Short 3-4 word phrases, timed proportionally to character count inside each scene."""
    blocks, n = [], 0
    for a, b, text in timings(script, durations):
        parts = phrases(text)
        total = sum(len(p) for p in parts) or 1
        t = a
        for p in parts:
            d = (b - a) * len(p) / total
            n += 1
            blocks.append(f"{n}\n{_ts(t)} --> {_ts(t + d)}\n{p}\n")
            t += d
    return "\n".join(blocks)


def scenes(script: Script, durations: list[float] | None = None) -> list[dict]:
    """Scene list aligned with beat_timings: hook, each beat, cta."""
    items = [{"type": "card", "ref": "", "text": script.title}]
    for b in script.beats:
        items.append({"type": b.visual_type, "ref": b.visual_ref, "text": b.on_screen_text or b.voiceover})
    items.append({"type": "card", "ref": "", "text": script.cta})
    for it, (a, b, _) in zip(items, timings(script, durations)):
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


def build_clips(script: Script, workdir: Path, durations: list[float] | None = None) -> list[Path]:
    clips = []
    for i, sc in enumerate(scenes(script, durations)):
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


def run(script: Script, workdir: Path, scene_audio: list[Path] | None = None) -> Path:
    """Render video.mp4. With `scene_audio` (one WAV per scene) timing comes from the audio."""
    from . import voice

    workdir.mkdir(parents=True, exist_ok=True)
    durations = [voice.wav_duration(p) + 0.2 for p in scene_audio] if scene_audio else None
    srt = workdir / "captions.srt"
    srt.write_text(to_srt(script, durations))
    clips = build_clips(script, workdir, durations)
    concat = workdir / "scenes.txt"
    concat.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    audio = None
    if scene_audio:
        padded = []
        for i, p in enumerate(scene_audio):  # 0.2 s of silence after each scene keeps audio aligned with video
            q = workdir / f"voicepad_{i:02}.wav"
            _run(["ffmpeg", "-y", "-i", str(p), "-af", "apad=pad_dur=0.2", "-ar", "24000", "-ac", "1", str(q)])
            padded.append(q)
        audio = voice.concat_audio(padded, workdir / "voice.m4a")
    out = workdir / "video.mp4"
    _run(final_command(concat, srt, out, audio))
    return out
