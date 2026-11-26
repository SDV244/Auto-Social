from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Video:
    id: str
    title: str
    url: str
    channel: str
    views: int
    age_days: float  # -1 = unknown
    duration_s: int = 0
    velocity: float = 0.0  # views per day, computed by research.rank


@dataclass
class Beat:
    voiceover: str
    on_screen_text: str = ""
    visual: str = ""        # human-readable description of the shot
    visual_type: str = "card"  # card | screen | stock | demo
    visual_ref: str = ""    # screen: https URL; stock: search query; demo: the example prompt typed on screen
    demo_output: str = ""   # demo only: the example response that "generates" on screen


@dataclass
class Script:
    title: str
    hook: str
    beats: list[Beat]
    cta: str
    disclosure: str
    angle: str = ""  # the original take that makes this not a copy
    hook_variants: list[dict] = field(default_factory=list)  # [{"style","text"}] for A/B tests
    hook_visual: str = ""  # one-sentence shot description for a video background behind the hook
    save_text: str = ""  # the prompt/checklist shown on the closing card (save-worthy)

    def voiceover_text(self) -> str:
        parts = [self.hook] + [b.voiceover for b in self.beats] + [self.cta]
        return " ".join(p.strip() for p in parts if p.strip())

    def to_dict(self) -> dict:
        return asdict(self)


def script_from_dict(d: dict) -> Script:
    beats = [Beat(**b) for b in d["beats"]]
    return Script(**{**d, "beats": beats})
