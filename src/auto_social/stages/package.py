"""Upload kit: everything needed to post an approved draft by hand in YouTube Studio and the TikTok app."""
from __future__ import annotations

import shutil
from pathlib import Path

from ..config import Config
from ..models import Script

YT_TITLE_MAX = 100


def _clean(text: str) -> str:
    return " ".join(text.replace("\\n", " ").split())


def youtube_title(script: Script) -> str:
    title = _clean(script.title)
    return title if len(title) <= YT_TITLE_MAX else title[: YT_TITLE_MAX - 1].rstrip() + "…"


def youtube_description(script: Script, cfg: Config) -> str:
    save = script.save_text.replace("\\n", "\n").strip()
    parts = [script.hook.strip()]
    if save:
        parts.append("Save this:\n" + save)
    if cfg.affiliate_cta:
        parts.append(cfg.affiliate_cta)
    parts.append(cfg.disclosure)
    parts.append(" ".join(["#Shorts"] + cfg.hashtags))
    return "\n\n".join(parts)


def tiktok_caption(script: Script, cfg: Config, limit: int = 150) -> str:
    """Short caption: the hook plus hashtags, kept within `limit` characters."""
    tags = " ".join(cfg.hashtags[:3])
    hook = _clean(script.hook)
    room = limit - len(tags) - 1
    if len(hook) > room:
        hook = hook[: room - 1].rstrip() + "…"
    return f"{hook} {tags}"


CHECKLIST = """UPLOAD CHECKLIST  ({title})

Suggested time: {post_time}

YouTube (YouTube Studio > Create > Upload video, or the YouTube app)
 [ ] Upload video.mp4 (vertical, under 3 min = Short)
 [ ] Title: paste youtube_title.txt
 [ ] Description: paste youtube_description.txt
 [ ] Audience: "No, it's not made for kids"
 [ ] Altered content: answer YES (it contains realistic AI-generated video). Do not skip this.
 [ ] Visibility: Public (or Schedule for the suggested time)
 [ ] After it is live: add pinned_comment.txt as a comment and pin it

TikTok (app > + > Upload)
 [ ] Pick video.mp4
 [ ] Caption: paste tiktok_caption.txt
 [ ] Turn ON "AI-generated content" in More options
 [ ] Cover: pick a frame where the hook text is readable
 [ ] Post, then add pinned_comment.txt as a comment and pin it

Remember: the video was generated with AI (script, voice, clips). Keep the disclosure on.
"""


def build(run_dir: Path, script: Script, cfg: Config) -> Path:
    out = run_dir / "upload"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(run_dir / "video.mp4", out / "video.mp4")
    (out / "youtube_title.txt").write_text(youtube_title(script))
    (out / "youtube_description.txt").write_text(youtube_description(script, cfg))
    (out / "tiktok_caption.txt").write_text(tiktok_caption(script, cfg))
    save = script.save_text.replace("\\n", "\n").strip()
    (out / "pinned_comment.txt").write_text(save or script.cta)
    (out / "CHECKLIST.txt").write_text(CHECKLIST.format(title=youtube_title(script), post_time=cfg.post_time))
    return out
