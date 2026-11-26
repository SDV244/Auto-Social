from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Video:
    id: str
    title: str
    url: str
    channel: str
    views: int
    age_days: float
    duration_s: int = 0
    velocity: float = 0.0  # views per day, computed by research.rank


@dataclass
class Beat:
    voiceover: str
    on_screen_text: str = ""
    visual: str = ""  # what to show: e.g. "screen recording: Notion AI summarizing a doc"


@dataclass
class Script:
    title: str
    hook: str
    beats: list[Beat]
    cta: str
    disclosure: str
    angle: str = ""  # the original take that makes this not a copy

    def voiceover_text(self) -> str:
        parts = [self.hook] + [b.voiceover for b in self.beats] + [self.cta]
        return " ".join(p.strip() for p in parts if p.strip())

    def to_dict(self) -> dict:
        return asdict(self)
