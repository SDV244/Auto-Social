from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    niche: str = "AI tools for business and productivity"
    language: str = "en"
    market: str = "US"
    search_queries: list[str] = field(default_factory=list)
    max_candidates: int = 25
    max_age_days: int = 21
    min_views: int = 20000
    monthly_budget_usd: float = 100.0
    script_model: str = "claude-sonnet-5-5"
    voice_provider: str = "none"
    voice_id: str = ""
    publish_provider: str = "outbox"
    affiliate_cta: str = ""
    disclosure: str = "AI-assisted video."

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        models = raw.get("models", {})
        voice = raw.get("voice", {})
        publish = raw.get("publish", {})
        return cls(
            niche=raw.get("niche", cls.niche),
            language=raw.get("language", cls.language),
            market=raw.get("market", cls.market),
            search_queries=list(raw.get("search_queries", [])),
            max_candidates=int(raw.get("max_candidates", cls.max_candidates)),
            max_age_days=int(raw.get("max_age_days", cls.max_age_days)),
            min_views=int(raw.get("min_views", cls.min_views)),
            monthly_budget_usd=float(raw.get("monthly_budget_usd", cls.monthly_budget_usd)),
            script_model=models.get("script", cls.script_model),
            voice_provider=voice.get("provider", cls.voice_provider),
            voice_id=voice.get("voice_id", cls.voice_id),
            publish_provider=publish.get("provider", cls.publish_provider),
            affiliate_cta=raw.get("affiliate_cta", cls.affiliate_cta),
            disclosure=raw.get("disclosure", cls.disclosure),
        )
