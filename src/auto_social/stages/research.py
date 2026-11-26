"""Find what is working in the niche right now, ranked by view velocity (views/day).

We only read public metadata; we never reuse another creator's footage, audio or script.
The output is *inspiration for structure and topic*, not material to copy.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..config import Config
from ..models import Video


def rank(videos: list[Video], min_views: int, max_age_days: int) -> list[Video]:
    out = []
    for v in videos:
        if v.views < min_views:
            continue
        if v.age_days < 0:  # age unknown (YouTube blocked the detail lookup): assume ~90 days
            v.velocity = v.views / 90
            out.append(v)
            continue
        if v.age_days > max_age_days:
            continue
        v.velocity = v.views / max(v.age_days, 1.0)
        out.append(v)
    return sorted(out, key=lambda v: v.velocity, reverse=True)


def _age_days(upload_date: str | None) -> float:
    if not upload_date:
        return -1.0
    d = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - d).total_seconds() / 86400


def search_youtube(query: str, limit: int) -> list[Video]:
    """Flat search (views, title, channel, duration), then best-effort upload-date lookup.

    The detail lookup can be refused with "sign in to confirm you're not a bot" from
    datacenter IPs; in that case age stays unknown (-1) and ranking falls back to views.
    """
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "extract_flat": True}) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    videos = []
    for e in info.get("entries", []) or []:
        videos.append(
            Video(
                id=e["id"],
                title=e.get("title", ""),
                url=e.get("url") or f"https://www.youtube.com/watch?v={e['id']}",
                channel=e.get("channel", ""),
                views=int(e.get("view_count") or 0),
                age_days=_age_days(e.get("upload_date")),
                duration_s=int(e.get("duration") or 0),
            )
        )
    return videos


def enrich_age(videos: list[Video]) -> None:
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        for v in videos:
            if v.age_days >= 0:
                continue
            try:
                v.age_days = _age_days(ydl.extract_info(v.url, download=False).get("upload_date"))
            except Exception:
                break  # blocked: stop hammering YouTube, keep the rest unknown


def run(cfg: Config, top: int = 10) -> list[Video]:
    seen: dict[str, Video] = {}
    for q in cfg.search_queries:
        for v in search_youtube(q, cfg.max_candidates):
            seen.setdefault(v.id, v)
    pool = sorted(seen.values(), key=lambda v: v.views, reverse=True)[: top * 2]
    enrich_age(pool)
    return rank(pool, cfg.min_views, cfg.max_age_days)[:top]
