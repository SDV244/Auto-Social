import json

import pytest

from auto_social.budget import Budget, BudgetExceeded
from auto_social.config import Config
from auto_social.models import Video
from auto_social.stages import publish, render, research, script as script_stage, transcribe

VTT = """WEBVTT
Kind: captions

00:00:00.000 --> 00:00:02.000
hello <c>there</c>

00:00:02.000 --> 00:00:04.000
hello there
this is a test
"""

GOOD = {
    "title": "t", "hook": "Stop wasting hours on email.", "angle": "uses a 3-step flow",
    "beats": [{"voiceover": f"beat {i}", "on_screen_text": "x", "visual": "screen"} for i in range(6)],
    "cta": "",
}


def test_rank_filters_and_orders_by_velocity():
    vs = [
        Video("a", "slow", "u", "c", 50_000, 10),
        Video("b", "fast", "u", "c", 50_000, 2),
        Video("c", "tiny", "u", "c", 100, 1),
        Video("d", "old", "u", "c", 900_000, 90),
    ]
    out = research.rank(vs, min_views=20_000, max_age_days=21)
    assert [v.id for v in out] == ["b", "a"]


def test_parse_vtt_dedupes_repeated_caption_lines():
    assert transcribe.parse_vtt(VTT) == "hello there this is a test"


def test_budget_blocks_overspend(tmp_path):
    b = Budget(1.0, tmp_path / "b.json")
    b.charge(0.6)
    with pytest.raises(BudgetExceeded):
        b.charge(0.5)
    assert b.spent() == pytest.approx(0.6)


def test_parse_script_uses_config_cta_and_disclosure():
    cfg = Config(affiliate_cta="link in bio", disclosure="AI-assisted")
    s = script_stage.parse_script("noise " + json.dumps(GOOD), cfg)
    assert s.cta == "link in bio" and s.disclosure == "AI-assisted"
    with pytest.raises(ValueError):
        script_stage.parse_script("no json here", cfg)


def test_srt_and_draft_flow(tmp_path):
    s = script_stage.parse_script(json.dumps(GOOD), Config(affiliate_cta="cta"))
    srt = render.to_srt(s)
    assert srt.startswith("1\n00:00:00,000 -->")
    d = publish.save_draft(tmp_path / "r1", s, None)
    assert publish.list_runs(tmp_path) == [("r1", "draft")]
    publish.set_status(d, "approved")
    assert publish.list_runs(tmp_path) == [("r1", "approved")]


def test_visual_types_are_validated_and_scenes_align():
    bad = dict(GOOD)
    bad["beats"] = [
        {"voiceover": "a b c", "visual_type": "screen", "visual_ref": "http://not-https"},  # -> card
        {"voiceover": "d e f", "visual_type": "screen", "visual_ref": "https://notion.so"},
        {"voiceover": "g h i", "visual_type": "weird", "visual_ref": "x"},  # -> card
        {"voiceover": "j k l", "visual_type": "stock", "visual_ref": "person typing"},
    ]
    s = script_stage.parse_script(json.dumps(bad), Config(affiliate_cta="cta"))
    assert [b.visual_type for b in s.beats] == ["card", "screen", "card", "stock"]
    sc = render.scenes(s)
    assert len(sc) == len(s.beats) + 2 == len(render.beat_timings(s))  # hook + beats + cta
    assert all(x["duration"] > 0 for x in sc)


def test_voice_duration_guard():
    from auto_social.stages import voice

    short = "Stop wasting time."
    assert voice.max_plausible_seconds(short) >= 3.0
    assert voice.max_plausible_seconds("word " * 20) > 20 / 2.3  # allows slower reads
    assert voice.max_plausible_seconds("word " * 11) < 20.6      # the 20.6 s rambling clip is rejected
