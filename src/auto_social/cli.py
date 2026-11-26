from __future__ import annotations

import argparse
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
        d = RUNS / v.id
        audio = voice.synthesize(cfg, budget, s.voiceover_text(), d / "voice.mp3") if cfg.voice_provider != "none" else None
        video = render.run(s, d, audio)
        publish.save_draft(d, s, video)
        print(f"draft ready: {d}  (spent ${budget.spent():.2f}/${cfg.monthly_budget_usd:.0f})")
        made += 1
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
    m.add_argument("--final", action="store_true", help="use the premium model for the script")
    m.set_defaults(fn=cmd_make)
    sub.add_parser("review", help="list drafts and status").set_defaults(fn=cmd_review)
    for name in ("approve", "reject"):
        a = sub.add_parser(name)
        a.add_argument("run_id")
        a.set_defaults(fn=cmd_set, status="approved" if name == "approve" else "rejected")
    args = p.parse_args(argv)
    return args.fn(Config.load(args.config), args)


if __name__ == "__main__":
    sys.exit(main())
