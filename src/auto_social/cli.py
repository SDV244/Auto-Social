from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .budget import Budget
from .config import Config
from .stages import publish, render, research, script as script_stage, transcribe, voice

RUNS = Path("runs")


def cmd_research(cfg: Config, args) -> int:
    for i, v in enumerate(research.run(cfg, args.top), 1):
        print(f"{i:>2}. {v.velocity:>9,.0f} views/day  {v.title[:70]}  [{v.channel}]  {v.url}")
    return 0


def make_drafts(cfg: Config, budget: Budget, vid: str, s, n_variants: int = 1) -> list[Path]:
    """Voice + render a script, optionally as N hook variants (A/B/C). Only the hook scene differs."""
    variants = (s.hook_variants[:n_variants]) or [{"style": "main", "text": s.hook}]
    s = dataclasses.replace(s, hook=variants[0]["text"])
    multi = len(variants) > 1
    dirs = [RUNS / (f"{vid}_{'ABC'[k]}" if multi else vid) for k in range(len(variants))]
    ctx = render.VideoContext(cfg.video_model, budget, cfg.video_max_seconds) if cfg.video_provider == "openrouter" else None
    base_audio = voice.synthesize_scenes(cfg, budget, s, dirs[0])
    done: list[Path] = []
    for d, var in zip(dirs, variants):
        sv = dataclasses.replace(s, hook=var["text"])
        audio = base_audio
        if base_audio and done:  # only the hook is re-voiced; every other scene is reused
            audio = [voice.synthesize_one(cfg, budget, var["text"], d / "voice_00.wav")] + base_audio[1:]
        video = render.run(sv, d, audio, reuse_from=done[0] if done else None, video_ctx=ctx, continuous=cfg.voice_mode == "continuous")
        publish.save_draft(d, sv, video)
        (d / "variant.json").write_text(json.dumps(var))
        done.append(d)
        print(f"draft ready: {d}  hook[{var['style']}]: {var['text']}  (spent ${budget.spent():.2f}/${cfg.monthly_budget_usd:.0f})")
    return done


def cmd_make(cfg: Config, args) -> int:
    budget = Budget(cfg.monthly_budget_usd)
    candidates = research.run(cfg, args.top)
    made = 0
    for v in candidates:
        if made >= args.count:
            break
        try:
            text = transcribe.run(v.url, cfg.language)
        except Exception as e:  # e.g. YouTube bot-check on this video: try the next one
            print(f"skip {v.id}: {str(e)[:80]}")
            continue
        if not text:
            continue
        s = script_stage.run(cfg, budget, v, text, final=args.final)
        make_drafts(cfg, budget, v.id, s, args.variants)
        made += 1
    return 0


def cmd_rerender(cfg: Config, args) -> int:
    """Re-render a draft from its saved script and existing voice clips (no new voice cost)."""
    import json

    from .models import script_from_dict

    d = RUNS / args.run_id
    s = script_from_dict(json.loads((d / "script.json").read_text()))
    n = len(voice.scene_texts(s))
    base = RUNS / (args.run_id.rsplit("_", 1)[0] + "_A") if args.run_id[-2:-1] == "_" else d
    # variants only store their own hook audio; every other scene's voice lives in the first variant
    clips = [p for p in ((d if (d / f"voicefast_{i:02}.wav").exists() else base) / f"voicefast_{i:02}.wav" for i in range(n)) if p.exists()]
    if clips and len(clips) != n:
        raise SystemExit(f"incomplete voice clips for {args.run_id}: found {len(clips)} of {n}")
    ctx = render.VideoContext(cfg.video_model, Budget(cfg.monthly_budget_usd), cfg.video_max_seconds) if cfg.video_provider == "openrouter" else None
    out = render.run(s, d, clips or None, video_ctx=ctx, continuous=cfg.voice_mode == "continuous")
    print(f"re-rendered: {out}")
    return 0


def cmd_review(cfg: Config, args) -> int:
    for name, status in publish.list_runs(RUNS):
        print(f"{status:<9} {name}")
    return 0


def cmd_set(cfg: Config, args) -> int:
    publish.set_status(RUNS / args.run_id, args.status)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="auto-social")
    p.add_argument("--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("research", help="rank trending videos in the niche")
    r.add_argument("--top", type=int, default=10)
    r.set_defaults(fn=cmd_research)
    m = sub.add_parser("make", help="research -> transcript -> script -> render -> draft")
    m.add_argument("--top", type=int, default=10)
    m.add_argument("--count", type=int, default=1)
    m.add_argument("--variants", type=int, default=1, help="render N hook variants (A/B/C) of the same video")
    m.add_argument("--final", action="store_true", help="use the premium model for the script")
    m.set_defaults(fn=cmd_make)
    rr = sub.add_parser("rerender", help="re-render a draft from its saved script and voice clips")
    rr.add_argument("run_id")
    rr.set_defaults(fn=cmd_rerender)
    sub.add_parser("review", help="list drafts and status").set_defaults(fn=cmd_review)
    for name in ("approve", "reject"):
        a = sub.add_parser(name)
        a.add_argument("run_id")
        a.set_defaults(fn=cmd_set, status="approved" if name == "approve" else "rejected")
    args = p.parse_args(argv)
    return args.fn(Config.load(args.config), args)


if __name__ == "__main__":
    sys.exit(main())
