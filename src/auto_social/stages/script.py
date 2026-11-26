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

SYSTEM = """You write 30-45 second faceless short-form video scripts for the niche: {niche}.
Audience: {market} viewers, language: {language}.

Rules:
- You receive EITHER a transcript of a video that is performing well OR a "TOPIC BRIEF" with no source video. For a brief, create the video from the topic alone, with concrete, accurate examples.
- For a transcript: Use it ONLY to learn the topic and why it works (hook, pacing, structure). Never reuse its wording, examples or sequence.
- Add a distinct angle the source does not have (a concrete workflow, a comparison, a mistake to avoid, a number you can justify). State that angle in "angle".
- Do not invent facts, prices, features or statistics. If unsure, leave them out.

STRUCTURE (retention-first, in this order):
 1. HOOK (first 3 seconds, <= 12 words): promise a concrete result or call out a costly mistake. No intro, no greeting, no "in this video".
    Give 3 "hook_variants" with different styles: "question", "mistake" (a common error, described without invented costs) and "number". Put the best one in "hook".
    HARD RULE on numbers: the "number" style may ONLY count things that appear in this video (e.g. "3 prompts", "2 steps", "4 tools"). Never state prices, dollar amounts, percentages, time saved, speeds or earnings unless the source transcript states them. A hook must promise only what the video actually shows.
 2. PAYOFF FIRST: the first beat SHOWS the result (a "demo" beat) before explaining it.
 3. 3-5 short beats that explain how, one idea each.
 4. RE-HOOK around the middle: one beat that opens a new loop ("but here is the part most people skip").
 5. CLOSE: a save-worthy takeaway (the exact prompt, checklist or rule to copy) in "save_text" (<= 30 words, short lines separated by \\n),
    and a "cta" (<= 12 words) that says to save it and ties back to the hook so the video loops.
- Each beat: voiceover (<= 22 words), on_screen_text (<= 6 words), visual (one-line description of the shot),
  visual_type and visual_ref:
    "demo": an animated chat where a prompt is typed and an answer is generated live. visual_ref = the prompt (<= 20 words),
      "demo_output" = a concrete example answer (<= 45 words, short lines separated by \\n). It is an illustrative example,
      so write something genuinely useful and accurate.
    "screen": a screen recording of a real public web page. visual_ref = full https URL of the tool's public page. Only when a beat names a specific tool.
    "video": real-looking AI-generated b-roll. visual_ref = ONE sentence describing the shot (subject, setting, camera move, lighting).
      Realistic and generic: no text, no logos, no brands, no recognisable faces, no screens that need readable content. Hands, desks, rooms, cities, objects work best.
    "card": a clean text card for rules, comparisons and takeaways. visual_ref = "".
  Use 2 "demo" beats (the first one is the payoff), at most 1 "screen" beat, 2-3 "video" beats, the rest "card".
  Also give "hook_visual": one sentence describing a realistic video background for the hook (same rules as "video"). Never invent URLs you are not sure exist.
- Total spoken words (hook + beats + cta) must be 75-100, so the video runs about 30-40 seconds. Every beat under 7 seconds spoken.
Return ONLY JSON: {{"title","hook","hook_visual","hook_variants":[{{"style","text"}}],"angle","beats":[{{"voiceover","on_screen_text","visual","visual_type","visual_ref","demo_output"}}],"save_text","cta"}}"""

# Rough Sonnet-class pricing used only for the budget guard (USD per million tokens).
IN_PER_M, OUT_PER_M = 2.0, 10.0


def build_user_prompt(video: Video, transcript: str, max_chars: int = 12000) -> str:
    if transcript.startswith("TOPIC BRIEF:"):
        return transcript[:max_chars]
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
        demo_out = b.get("demo_output", "") or ""
        if vt == "demo" and not (ref and demo_out):
            vt, ref, demo_out = "card", "", ""
        if vt == "stock":  # legacy alias
            vt = "video"
        if vt not in ("card", "screen", "video", "demo"):
            vt, ref, demo_out = "card", "", ""
        beats.append(Beat(b.get("voiceover", ""), b.get("on_screen_text", ""), b.get("visual", ""), vt, ref, demo_out))
    if not 4 <= len(beats) <= 12:
        raise ValueError(f"unexpected number of beats: {len(beats)}")
    variants = [
        {"style": str(v.get("style", "")), "text": str(v.get("text", "")).strip()}
        for v in d.get("hook_variants", [])
        if isinstance(v, dict) and str(v.get("text", "")).strip()
    ]
    hook = d.get("hook") or (variants[0]["text"] if variants else "")
    if not hook:
        raise ValueError("script has no hook")
    # the chosen hook is always variant A; keep up to 3 distinct variants after it
    variants = [v for v in variants if v["text"] != hook]
    variants.insert(0, {"style": "main", "text": hook})
    variants = variants[:3]
    return Script(
        title=d["title"],
        hook=hook,
        hook_variants=variants,
        save_text=str(d.get("save_text", "") or ""),
        hook_visual=str(d.get("hook_visual", "") or ""),
        angle=d.get("angle", ""),
        beats=beats,
        cta=d.get("cta") or cfg.affiliate_cta,
        disclosure=cfg.disclosure,
    )


def structure_problems(s: Script, transcript: str = "") -> list[str]:
    """Rule checks the model often breaks: payoff-first order, enough demos, no invented numbers in hooks."""
    problems = []
    if not s.beats or s.beats[0].visual_type != "demo":
        problems.append('the FIRST beat must be a "demo" beat that shows the result (payoff first)')
    if sum(b.visual_type == "demo" for b in s.beats) < 2:
        problems.append('use 2 "demo" beats')
    evidence = " ".join([transcript, s.save_text] + [f"{b.voiceover} {b.on_screen_text} {b.visual_ref} {b.demo_output}" for b in s.beats]).lower()
    for v in s.hook_variants or [{"text": s.hook}]:
        for num in re.findall(r"\d[\d,.]*", v["text"]):
            if num.strip(",.") not in evidence:
                problems.append(f'hook "{v["text"]}" states the number {num}, which the video never shows; drop it or count only things shown')
                break
    return problems


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
            "max_tokens": 7000,
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
        max_tokens=7000,
        # cache_control keeps the fixed instructions cheap across the daily batch
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text if msg.content else ""


def run(cfg: Config, budget: Budget, video: Video, transcript: str, client=None, final: bool = False) -> Script:
    model = cfg.final_model if final else cfg.script_model
    system = SYSTEM.format(niche=cfg.niche, market=cfg.market, language=cfg.language)
    user = build_user_prompt(video, transcript)
    est = (len(system) + len(user)) / 4 / 1e6 * IN_PER_M + 5000 / 1e6 * OUT_PER_M
    budget.charge(est, "script generation")
    if cfg.llm_provider not in ("openrouter", "anthropic"):
        raise ValueError(f"unknown llm provider: {cfg.llm_provider}")
    last: Exception | None = None
    best: Script | None = None
    feedback = ""
    for _ in range(3):  # retries for malformed JSON or rule violations
        prompt = user + (f"\n\nYour previous attempt broke these rules, fix them: {feedback}" if feedback else "")
        raw = (
            _call_openrouter(cfg, system, prompt, model)
            if cfg.llm_provider == "openrouter"
            else _call_anthropic(cfg, system, prompt, client, model)
        )
        try:
            parsed = parse_script(raw, cfg)
        except (ValueError, KeyError) as e:  # JSONDecodeError is a ValueError
            last = e
            budget.charge(est, "script retry")
            continue
        problems = structure_problems(parsed, transcript)
        if not problems:
            return parsed
        best = best or parsed
        feedback = "; ".join(problems)
        budget.charge(est, "script retry")
    if best:  # accept the first parseable draft; the human approval step catches the rest
        return best
    raise RuntimeError(f"model returned an unusable script 3 times: {last}")
