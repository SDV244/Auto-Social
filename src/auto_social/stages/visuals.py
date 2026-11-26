"""Per-scene visuals. `card` and `screen` need no API keys and cost $0.

card   -> HTML text card rendered to a PNG by headless Chromium (brand colours, big text)
screen -> real screen recording of a public web page (slow scroll), via Playwright
stock  -> optional provider (Pixabay); falls back to a card when not configured
"""
from __future__ import annotations

import html
import os
import shutil
import tempfile
from pathlib import Path

W, H = 1080, 1920

CARD_HTML = """<html><body style="margin:0;width:{w}px;height:{h}px;display:flex;align-items:center;justify-content:center;
background:linear-gradient(160deg,#101820 0%,#1b2a41 60%,#0f4c5c 100%);font-family:Inter,Helvetica,Arial,sans-serif">
<div style="color:#fff;font-size:{size}px;font-weight:800;line-height:1.15;text-align:center;padding:0 90px;
text-shadow:0 6px 30px rgba(0,0,0,.45)">{text}</div></body></html>"""


def _launch(p):
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
    if not exe and Path("/opt/pw-browsers/chromium").exists():
        exe = "/opt/pw-browsers/chromium"  # preinstalled in the cloud sandbox
    kwargs = {"executable_path": exe} if exe else {}
    return p.chromium.launch(args=["--no-sandbox"], **kwargs)


def card_png(text: str, out: Path) -> Path:
    from playwright.sync_api import sync_playwright

    size = 120 if len(text) < 40 else 92 if len(text) < 90 else 72
    with sync_playwright() as p:
        browser = _launch(p)
        page = browser.new_page(viewport={"width": W, "height": H})
        page.set_content(CARD_HTML.format(w=W, h=H, size=size, text=html.escape(text)))
        page.screenshot(path=str(out))
        browser.close()
    return out


def screen_clip(url: str, duration: float, out: Path) -> Path | None:
    """Record `duration` seconds of a page at phone size (slow scroll). None on any failure.

    Frames are screenshots encoded by the system ffmpeg, which avoids Playwright's own
    video recorder (it needs a separately installed ffmpeg build).
    """
    import subprocess

    from playwright.sync_api import sync_playwright

    tmp = Path(tempfile.mkdtemp())
    try:
        n = max(int(duration * 8), 8)
        with sync_playwright() as p:
            browser = _launch(p)
            ctx = browser.new_context(viewport={"width": 540, "height": 960}, device_scale_factor=2)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1500)
            for i in range(n):
                page.screenshot(path=str(tmp / f"f{i:04}.png"))
                page.mouse.wheel(0, 14)
                page.wait_for_timeout(60)
            browser.close()
        fps = n / duration
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", f"{fps:.3f}", "-i", str(tmp / "f%04d.png"),
             "-vf", "scale=1080:1920", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
            check=True, capture_output=True,
        )
        return out
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def stock_clip(query: str, duration: float, out: Path) -> Path | None:
    """Plug a stock provider here (Pixabay API key needed). None = use a card instead."""
    return None
