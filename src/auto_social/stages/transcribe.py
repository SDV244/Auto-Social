"""Get a transcript cheaply: public captions first (free, no download), Whisper as fallback."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

_TS = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{3} --> ")
_TAG = re.compile(r"<[^>]+>")


def parse_vtt(text: str) -> str:
    """Collapse a WebVTT file (YouTube auto-captions repeat lines) into plain text."""
    lines, prev = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or _TS.match(line):
            continue
        line = _TAG.sub("", line).strip()
        if line and line != prev:
            lines.append(line)
            prev = line
    return " ".join(lines)


def from_captions(url: str, lang: str = "en") -> str | None:
    import yt_dlp

    with tempfile.TemporaryDirectory() as tmp:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": [lang],
            "subtitlesformat": "vtt",
            "outtmpl": str(Path(tmp) / "%(id)s"),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        files = list(Path(tmp).glob("*.vtt"))
        return parse_vtt(files[0].read_text()) if files else None


def from_whisper(audio_path: str) -> str:
    """Fallback for videos without captions. Runs locally, so it costs $0 but needs CPU/GPU."""
    from faster_whisper import WhisperModel

    model = WhisperModel("small", compute_type="int8")
    segments, _ = model.transcribe(audio_path)
    return " ".join(s.text.strip() for s in segments)


def run(url: str, lang: str = "en") -> str | None:
    return from_captions(url, lang)
