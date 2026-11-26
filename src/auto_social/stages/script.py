"""Turn a reference transcript into an ORIGINAL short script using Claude.

The prompt forbids copying and forces a distinct angle, which is also what keeps the
channel clear of YouTube's "inauthentic / repetitive content" demonetization.
"""
from __future__ import annotations

import json
import re

from ..budget import Budget
from ..config import Config
from ..models import Beat, Script, Video

SYSTEM = """You write 45-60 second faceless short-form video scripts for the niche: {niche}.
Audience: {market} viewers, language: {language}.

Rules:
- You receive a transcript of a video that is performing well. Use it ONLY to learn the topic and why it works (hook, pacing, structure). Never reuse its wording, examples or sequence.
- Add a distinct angle the source does not have (a concrete workflow, a comparison, a mistake to avoid, a number you can justify). State that angle in "angle".
- Do not invent facts, prices, features or statistics. If unsure, leave them out.
- 6-9 short beats. Each beat: voiceover (<= 25 words), on_screen_text (<= 6 words), visual (one-line description of the shot),
  visual_type and visual_ref:
    "screen": a screen recording of a real public web page. visual_ref = full https URL of the tool's public homepage/pricing/demo page. Use for beats that name a specific tool.
    "stock": generic b-roll. visual_ref = a 2-4 word search query (e.g. "person typing laptop").
    "card": a clean text card for rules, comparisons and takeaways. visual_ref = "".
  Use at most 3 "screen" beats and prefer "card" when unsure; never invent URLs you are not sure exist.
- Total spoken words (hook + all beats + cta) must be 90-120, so the video runs about 40-55 seconds.
- Hook in the first sentence, under 15 words, no clickbait that the video does not pay off.
Return ONLY JSON: {{"title","hook","angle","beats":[{{"voiceover","on_screen_text","visual","visual_type","visual_ref"}}],"cta"}}"""

# Rough Sonnet-class pricing used only for the budget guard (USD per million tokens).
IN_PER_M, OUT_PER_M = 2.0, 10.0


def build_user_prompt(video: Video, transcript: str, max_chars: int = 12000) -> str:
    return (
        f"Reference video: {video.title} ({video.views:,} views, {video.age_days:.0f} days old)\n\n"
        f"Transcript:\n{transcript[:max_chars]}"
    )


def parse_script(raw: str, cfg: Config) -> Script:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("model returned no JSON object")
    d = json.loads(m.group(0))
    beats = []
    for b in d["beats"]:
        vt = b.get("visual_type", "card")
        ref = b.get("visual_ref", "") or ""
        if vt == "screen" and not ref.startswith("https://"):
            vt, ref = "card", ""
        if vt not in ("card", "screen", "stock"):
            vt, ref = "card", ""
        beats.append(Beat(b.get("voiceover", ""), b.get("on_screen_text", ""), b.get("visual", ""), vt, ref))
    if not 4 <= len(beats) <= 12:
        raise ValueError(f"unexpected number of beats: {len(beats)}")
    return Script(
        title=d["title"],
        hook=d["hook"],
        angle=d.get("angle", ""),
        beats=beats,
        cta=d.get("cta") or cfg.affiliate_cta,
        disclosure=cfg.disclosure,
    )


def _call_openrouter(cfg: Config, system: str, user: str, model: str | None = None) -> str:
    """OpenAI-compatible endpoint. Lets one key reach many models and cap spend per key."""
    import os

    import httpx

    headers = {"Content-Type": "application/json"}
    if os.environ.get("OPENROUTER_API_KEY"):  # in the cloud sandbox the proxy injects the key instead
        headers["Authorization"] = f"Bearer {os.environ['OPENROUTER_API_KEY']}"
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json={
            "model": model or cfg.script_model,
            "max_tokens": 3500,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"].get("content") or ""  # empty -> retried by the caller


def _call_anthropic(cfg: Config, system: str, user: str, client=None, model: str | None = None) -> str:
    import anthropic

    client = client or anthropic.Anthropic()
    msg = client.messages.create(
        model=model or cfg.script_model,
        max_tokens=3500,
        # cache_control keeps the fixed instructions cheap across the daily batch
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text if msg.content else ""


def run(cfg: Config, budget: Budget, video: Video, transcript: str, client=None, final: bool = False) -> Script:
    model = cfg.final_model if final else cfg.script_model
    system = SYSTEM.format(niche=cfg.niche, market=cfg.market, language=cfg.language)
    user = build_user_prompt(video, transcript)
    est = (len(system) + len(user)) / 4 / 1e6 * IN_PER_M + 3500 / 1e6 * OUT_PER_M
    budget.charge(est, "script generation")
    if cfg.llm_provider not in ("openrouter", "anthropic"):
        raise ValueError(f"unknown llm provider: {cfg.llm_provider}")
    last: Exception | None = None
    for _ in range(2):  # one retry if the model returns malformed/truncated JSON
        raw = (
            _call_openrouter(cfg, system, user, model)
            if cfg.llm_provider == "openrouter"
            else _call_anthropic(cfg, system, user, client, model)
        )
        try:
            return parse_script(raw, cfg)
        except (ValueError, KeyError) as e:  # JSONDecodeError is a ValueError
            last = e
            budget.charge(est, "script retry")
    raise RuntimeError(f"model returned an unusable script twice: {last}")
