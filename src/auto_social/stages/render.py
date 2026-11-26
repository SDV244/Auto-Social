"""Scene-based renderer: one clip per scene (hook, beats, cta), concatenated with audio + captions.

Each scene uses its beat's visual (AI video clip / screen recording / demo / text card); anything that
fails or is not configured degrades to a text card, so a render always completes.
"""
from __future__ import annotations

import hashlib
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..models import Script
from . import visuals

FPS = 30
CACHE = Path("assets/cache")


@dataclass
class VideoContext:
    """Paid AI-video generation settings for one render; `used` counts billed seconds."""
    model: str
    budget: object
    max_seconds: int = 14
    used: int = 0

    def billed(self, duration: float) -> int:
        return next((s for s in (4, 6, 8) if s >= duration), 8)  # Veo bills 4/6/8 s clips
PAD = 0.08  # seconds of silence after each scene (per_scene voice mode); keeps cuts snappy
HOOK_PAD = 0.18  # a beat after the hook in continuous mode, where the hook is a separate read


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
    if len(durations) != len(script.beats) + 2:
        raise ValueError(f"expected {len(script.beats) + 2} scene durations, got {len(durations)}")
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


def _ass_time(sec: float) -> str:
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Cap,Inter,86,&H0000E5FF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,9,0,2,60,60,430,1
Style: Title,Inter,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,8,2,8,70,70,260,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""


def group_words(words: list[str], max_words: int = 3, max_chars: int = 18) -> list[list[str]]:
    """Split into short caption lines that fit the 1080px frame at the caption font size."""
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or len(" ".join(cur + [w])) > max_chars):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def to_ass(script: Script, durations: list[float] | None = None, words_per_line: int = 3) -> str:
    """Kinetic captions: 3-word lines, big, the word being spoken turns yellow, short pop-in."""
    lines = []
    for a, b, text in timings(script, durations):
        words = text.split()
        groups = group_words(words, words_per_line) or [[text]]
        total = sum(len(w) + 1 for g in groups for w in g) or 1
        t = a
        for g in groups:
            glen = sum(len(w) + 1 for w in g)
            gd = (b - a) * glen / total
            ks = "".join(
                f"{{\\k{max(int(round(gd * (len(w) + 1) / glen * 100)), 1)}}}{w.upper()} " for w in g
            ).strip()
            pop = "{\\fscx82\\fscy82\\t(0,110,\\fscx100\\fscy100)}"
            lines.append(f"Dialogue: 0,{_ass_time(t)},{_ass_time(t + gd)},Cap,,0,0,0,,{pop}{ks}")
            t += gd
    for sc in scenes(script, durations):  # headline over AI-video scenes (cards already show their own text)
        if sc["type"] == "video" and sc["text"].strip():
            a = sc["start"]
            lines.append(f"Dialogue: 1,{_ass_time(a)},{_ass_time(a + sc['duration'])},Title,,0,0,0,,{{\\fad(120,0)}}{sc['text']}")
    return ASS_HEADER + "\n".join(lines) + "\n"


def scenes(script: Script, durations: list[float] | None = None) -> list[dict]:
    """Scene list aligned with beat_timings: hook, each beat, cta."""
    items = [{"type": "video" if script.hook_visual else "card", "ref": script.hook_visual, "text": script.hook, "output": ""}]
    for b in script.beats:
        items.append({"type": b.visual_type, "ref": b.visual_ref, "text": b.on_screen_text or b.voiceover,
                      "output": b.demo_output})
    save = script.save_text.replace("\\n", "\n").strip()  # tolerate literal "\\n" from the model
    items.append({"type": "card", "ref": "", "text": f"SAVE THIS\n{save}" if save else script.cta})
    for it, (a, b, _) in zip(items, timings(script, durations)):
        it["duration"] = b - a
        it["start"] = a
    return items


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def _still_clip(png: Path, dur: float, out: Path, zoom_out: bool = False) -> None:
    frames = int(dur * FPS)
    z = "if(eq(on,0),1.12,max(zoom-0.0009,1.0))" if zoom_out else "min(zoom+0.0009,1.12)"
    vf = f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps={FPS},format=yuv420p"
    _run(["ffmpeg", "-y", "-i", str(png), "-vf", vf, "-frames:v", str(frames), "-c:v", "libx264", str(out)])


def _video_clip(src: Path, dur: float, out: Path) -> None:
    vf = f"scale=1080:1920,fps={FPS},tpad=stop_mode=clone:stop_duration={dur:.2f},format=yuv420p"
    _run(["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-t", f"{dur:.2f}", "-an", "-c:v", "libx264", str(out)])


def _ai_video(sc: dict, ctx: VideoContext, out: Path) -> Path | None:
    """Generate (or reuse from cache) an AI clip for this scene, within the per-video seconds cap.

    Cache key = model + shot description. A cached clip is reused whenever it is at least as long as
    the scene needs, so hook variants of different length do not pay for the same shot twice.
    """
    secs = ctx.billed(sc["duration"])
    key = hashlib.sha1(f"{ctx.model}|{sc['ref']}".encode()).hexdigest()[:16]
    for cached in sorted(CACHE.glob(f"{key}_*s.mp4")):
        if int(cached.stem.rsplit("_", 1)[1].rstrip("s")) >= secs:
            return cached
    if ctx.used + secs > ctx.max_seconds:
        return None  # over the cap: the caller falls back to a text card
    CACHE.mkdir(parents=True, exist_ok=True)
    clip = visuals.ai_video_clip(sc["ref"], secs, CACHE / f"{key}_{secs}s.mp4", ctx.model, ctx.budget)
    if clip:
        ctx.used += secs
    return clip


def build_clips(script: Script, workdir: Path, durations: list[float] | None = None, reuse_from: Path | None = None,
                video_ctx: VideoContext | None = None) -> list[Path]:
    """`reuse_from`: a previous render of the same script; scenes after the hook are copied, not rebuilt."""
    clips = []
    for i, sc in enumerate(scenes(script, durations)):
        out = workdir / f"scene_{i:02}.mp4"
        if reuse_from and i > 0 and (reuse_from / f"scene_{i:02}.mp4").exists():
            shutil.copy(reuse_from / f"scene_{i:02}.mp4", out)
            clips.append(out)
            continue
        raw = None
        if sc["type"] == "screen":
            raw = visuals.screen_clip(sc["ref"], sc["duration"], workdir / f"scene_{i:02}_screen.mp4")
        elif sc["type"] == "demo":
            raw = visuals.demo_clip(sc["ref"], sc["output"], sc["duration"], workdir / f"scene_{i:02}_demo.mp4")
        elif sc["type"] == "video" and video_ctx and sc["ref"]:
            raw = _ai_video(sc, video_ctx, workdir / f"scene_{i:02}_ai.mp4")
        if raw:
            _video_clip(raw, sc["duration"], out)
        else:
            png = visuals.card_png(sc["text"], workdir / f"scene_{i:02}.png")
            _still_clip(png, sc["duration"], out, zoom_out=i % 2 == 1)
        clips.append(out)
    return clips


def final_command(concat_list: Path, ass: Path, out: Path, audio: Path | None = None) -> list[str]:
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list)]
    if audio:
        cmd += ["-i", str(audio)]
    cmd += ["-vf", f"ass={ass}", "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-shortest"] if audio else []
    return cmd + [str(out)]


def run(script: Script, workdir: Path, scene_audio: list[Path] | None = None, reuse_from: Path | None = None,
        video_ctx: VideoContext | None = None, continuous: bool = False) -> Path:
    """Render video.mp4. With `scene_audio` (one WAV per scene) timing comes from the audio."""
    from . import voice

    workdir.mkdir(parents=True, exist_ok=True)
    # continuous take: scenes are cut from one read, so no extra silence between them (only a beat after the hook)
    pads = ([HOOK_PAD] + [0.0] * (len(scene_audio) - 1) if continuous else [PAD] * len(scene_audio)) if scene_audio else []
    durations = [voice.wav_duration(p) + pad for p, pad in zip(scene_audio, pads)] if scene_audio else None
    (workdir / "captions.srt").write_text(to_srt(script, durations))  # plain captions, handy for upload
    ass = workdir / "captions.ass"
    ass.write_text(to_ass(script, durations))
    clips = build_clips(script, workdir, durations, reuse_from, video_ctx)
    concat = workdir / "scenes.txt"
    concat.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    audio = None
    if scene_audio:
        padded = []
        for i, (p, pad) in enumerate(zip(scene_audio, pads)):  # silence after a scene keeps audio aligned with video
            q = workdir / f"voicepad_{i:02}.wav"
            _run(["ffmpeg", "-y", "-i", str(p), "-af", f"apad=pad_dur={pad}", "-ar", "24000", "-ac", "1", str(q)])
            padded.append(q)
        audio = voice.concat_audio(padded, workdir / "voice.m4a")
    out = workdir / "video.mp4"
    _run(final_command(concat, ass, out, audio))
    return out
