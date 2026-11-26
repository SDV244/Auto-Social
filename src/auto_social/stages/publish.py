"""Approval queue. Nothing is published until a human moves a draft to `approved`.

`outbox` (default) keeps drafts as folders under runs/<id>/. Wiring a real scheduler
(Postiz API/MCP) is intentionally a later step: do it after the first drafts look good,
and keep the human approval gate.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Script


def save_draft(run_dir: Path, script: Script, video: Path | None) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    caption = f"{script.title}\n\n{script.cta}\n\n{script.disclosure}"
    (run_dir / "caption.txt").write_text(caption)
    (run_dir / "script.json").write_text(json.dumps(script.to_dict(), indent=2))
    (run_dir / "status").write_text("draft")
    return run_dir


def set_status(run_dir: Path, status: str) -> None:
    if status not in {"draft", "approved", "rejected"}:
        raise ValueError(status)
    (run_dir / "status").write_text(status)


def list_runs(root: Path) -> list[tuple[str, str]]:
    return sorted(
        (p.name, (p / "status").read_text().strip()) for p in root.glob("*") if (p / "status").exists()
    )
