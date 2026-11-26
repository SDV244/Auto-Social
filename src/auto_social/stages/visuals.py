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

# Sites often show a bot wall to headless/datacenter browsers; recording it would ruin the video.
BLOCK_PHRASES = (
    "not a bot", "verify you are human", "verifying you are human", "security service",
    "access denied", "captcha", "just a moment", "enable javascript", "unusual traffic",
    "request blocked", "403 forbidden", "attention required",
)


def looks_blocked(title: str, body_text: str) -> bool:
    hay = f"{title}\n{body_text[:1500]}".lower()
    return any(p in hay for p in BLOCK_PHRASES)

CARD_HTML = """<html><body style="margin:0;width:{w}px;height:{h}px;display:flex;align-items:center;justify-content:center;
background:linear-gradient(160deg,#101820 0%,#1b2a41 60%,#0f4c5c 100%);font-family:Inter,Helvetica,Arial,sans-serif">
<div style="color:#fff;font-size:{size}px;font-weight:800;line-height:1.15;text-align:center;padding:0 90px 360px 90px;box-sizing:border-box;width:100%;
text-shadow:0 6px 30px rgba(0,0,0,.45)">{text}</div></body></html>"""


def _launch(p):
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
    if not exe and Path("/opt/pw-browsers/chromium").exists():
        exe = "/opt/pw-browsers/chromium"  # preinstalled in the cloud sandbox
    kwargs = {"executable_path": exe} if exe else {}
    return p.chromium.launch(args=["--no-sandbox"], **kwargs)


def card_png(text: str, out: Path) -> Path:
    from playwright.sync_api import sync_playwright

    size = 120 if len(text) < 40 else 92 if len(text) < 90 else 72 if len(text) < 150 else 54
    with sync_playwright() as p:
        browser = _launch(p)
        page = browser.new_page(viewport={"width": W, "height": H})
        page.set_content(CARD_HTML.format(w=W, h=H, size=size, text=html.escape(text).replace("\n", "<br>")))
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
            if looks_blocked(page.title(), page.inner_text("body")):
                browser.close()
                return None  # caller falls back to a text card
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


DEMO_HTML = """<html><body style="margin:0;width:1080px;height:1920px;background:linear-gradient(160deg,#0b1220,#16233b 60%,#0e3a4a);
font-family:Inter,Helvetica,Arial,sans-serif;color:#fff;overflow:hidden">
<div style="position:absolute;top:150px;left:60px;right:60px">
 <div style="display:inline-block;background:#1f6feb;border-radius:40px;padding:10px 28px;font-size:34px;font-weight:700">AI assistant &middot; example</div>
 <div id="q" style="margin-top:50px;background:#22304d;border-radius:36px;padding:40px 44px;font-size:52px;line-height:1.3;min-height:120px;white-space:pre-wrap"></div>
 <div id="a" style="margin-top:44px;background:#f4f7fb;color:#101820;border-radius:36px;padding:40px 44px;font-size:50px;line-height:1.35;white-space:pre-wrap;display:none"></div>
</div>
<script>
const P=__PROMPT__, A=__OUTPUT__, D=__DUR__;
function setT(t){
  const pq=Math.min(1,t/(D*0.32)), pa=Math.max(0,Math.min(1,(t-D*0.38)/(D*0.55)));
  const q=P.slice(0,Math.floor(pq*P.length)), caret=(Math.floor(t*3)%2===0)?'\u258c':'';
  document.getElementById('q').textContent=q+(pa===0?caret:'');
  const a=document.getElementById('a');
  if(pa>0){a.style.display='block';a.textContent=A.slice(0,Math.ceil(pa*A.length))+(pa<1?caret:'');}
}
setT(0);
</script></body></html>"""


def demo_clip(prompt: str, output: str, duration: float, out: Path, fps: int = 15) -> Path | None:
    """Animated 'chat': a prompt is typed, then the answer streams in. Frames -> ffmpeg. None on failure."""
    import json
    import subprocess

    from playwright.sync_api import sync_playwright

    tmp = Path(tempfile.mkdtemp())
    try:
        page_html = (
            DEMO_HTML.replace("__PROMPT__", json.dumps(prompt))
            .replace("__OUTPUT__", json.dumps(output.replace("\\n", "\n")))
            .replace("__DUR__", str(max(duration - 0.4, 1.0)))
        )
        n = max(int(duration * fps), fps)
        with sync_playwright() as p:
            browser = _launch(p)
            page = browser.new_page(viewport={"width": W, "height": H})
            page.set_content(page_html)
            for i in range(n):
                page.evaluate(f"setT({i / fps})")
                page.screenshot(path=str(tmp / f"f{i:04}.jpg"), type="jpeg", quality=85)
            browser.close()
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(tmp / "f%04d.jpg"), "-vf", "fps=30",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
            check=True, capture_output=True,
        )
        return out
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# USD per second of generated video at 720p WITHOUT audio, from OpenRouter's published pricing (checked 2026-11).
AI_VIDEO_USD_PER_SEC = {"google/veo-3.1-lite": 0.03, "alibaba/wan-3.0": 0.10, "minimax/hailuo-3-max": 0.08}


def ai_video_clip(prompt: str, seconds: int, out: Path, model: str = "google/veo-3.1-lite", budget=None,
                  timeout_s: int = 360) -> Path | None:
    """Generate a real AI video clip through OpenRouter (9:16, 720p, no audio). None on any failure.

    Always sends explicit resolution/duration/audio: defaults can be 5-10x more expensive.
    """
    import time

    import httpx

    price = AI_VIDEO_USD_PER_SEC.get(model)
    if price is None:
        raise ValueError(f"no known price for {model}; add it to AI_VIDEO_USD_PER_SEC first")
    if budget is not None:
        budget.charge(price * seconds, f"ai video ({model}, {seconds}s)")
    headers = {"Content-Type": "application/json"}
    if os.environ.get("OPENROUTER_API_KEY"):  # in the cloud sandbox the proxy injects the key
        headers["Authorization"] = f"Bearer {os.environ['OPENROUTER_API_KEY']}"
    body = {"model": model, "prompt": prompt, "aspect_ratio": "9:16", "resolution": "720p",
            "duration": seconds, "generate_audio": False}
    try:
        r = httpx.post("https://openrouter.ai/api/v1/videos", json=body, headers=headers, timeout=60)
        r.raise_for_status()
        poll = r.json()["polling_url"]
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(8)
            j = httpx.get(poll, headers=headers, timeout=60).json()
            if j.get("status") == "completed":
                url = (j.get("unsigned_urls") or j.get("urls") or [None])[0]
                data = httpx.get(url, headers=headers, timeout=180, follow_redirects=True)
                data.raise_for_status()
                out.write_bytes(data.content)
                return out
            if j.get("status") == "failed":
                return None
        return None
    except Exception:
        return None


def stock_clip(query: str, duration: float, out: Path) -> Path | None:
    """Plug a stock provider here (Pixabay API key needed). None = use a card instead."""
    return None
