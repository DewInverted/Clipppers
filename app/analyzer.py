"""
Heuristic clip-intelligence engine (no API key required).

Given a timestamped transcript it:
  * finds candidate key moments (15-60s windows around strong sentences)
  * scores every candidate for virality, and scores its first ~3 seconds
    separately as the HOOK (that's what decides swipe vs. watch)
  * classifies each moment (Hook / Insight / Funny / Story / Hot take ...)
  * writes a suggested title, caption, hashtags and hook rewrites

If an LLM key is later added, this output is the perfect structured
input to feed it - but the app is fully useful without one.
"""
from __future__ import annotations

import math
import re
from collections import Counter

# ---------------------------------------------------------------- lexicons
HOOK_OPENERS = [
    (r"\b(stop|wait|hold on|listen|look)\b", 14, "Direct command — stops the scroll"),
    (r"\?", 12, "Opens with a question — curiosity gap"),
    (r"\b(nobody|no one) (talks|tells|knows|says)\b", 16, "‘Nobody talks about this’ — insider secret"),
    (r"\b(secret|truth|lie|myth|mistake|wrong|never|always)\b", 12, "Pattern-interrupt word"),
    (r"\b(how|why) (i|you|we|to)\b", 10, "How/why promise"),
    (r"\b\d+(\.\d+)?\s?(k|m|million|billion|%|percent|dollars|days|years|seconds|steps|ways|things)\b", 14, "Specific number — concrete payoff"),
    (r"\b(i (made|lost|spent|earned|built| quit)|i was|i had)\b", 10, "Personal stakes / story"),
    (r"\b(you|your)\b", 8, "Speaks directly to the viewer"),
    (r"\b(imagine|what if|picture this)\b", 12, "‘Imagine…’ visualisation"),
    (r"\b(biggest|best|worst|first|last|only| craziest|wildest)\b", 9, "Superlative — raises stakes"),
    (r"\b(until|before|after) (i|you|we)\b", 8, "Before/after transformation"),
    (r"\b(not|don'?t|never|no)\b", 6, "Negation — contrarian tension"),
]
EMOTION = set("love hate crazy insane wild amazing shocked shock unbelievable incredible stupid brilliant genius afraid fear angry happy sad funny hilarious ridiculous obsessed addicted embarrassed proud regret mistake fail failed failure win won lose lost money rich broke free secret hidden truth lie destroy ruined perfect worst best".split())
POWER = set("prove proven exactly actually literally seriously honestly frankly finally suddenly immediately instantly step steps framework system method formula reason reasons because so therefore result results grow growth scale sell sales profit revenue audience viral hook retain retention algorithm".split())
STOPWORDS = set("the a an and or but if then else for to of in on at by with is are was were be been it its this that these those i you he she we they my your his her our their me him us them as so just like really very".split())

LABELS = [
    ("Hot Take", r"\b(unpopular opinion|truth is|nobody|no one|everyone is wrong|stop .*ing|don'?t)\b"),
    ("Funny", r"(\[laughter\]|\(laughter\)|\bhaha|\blol\b|😂|🤣)"),
    ("Story", r"\b(so (one day|then)|i remember|when i was|years ago|turns out|long story)\b"),
    ("Insight", r"\b(because|the reason|that'?s why|what (i|we) learned|framework|step|method)\b"),
    ("Money", r"(\$|\b\d+\s?(k|m|million|billion)\b|\bmoney\b|\brevenue\b|\bprofit\b)"),
    ("Controversy", r"\b(cancel|banned|illegal|scam|lie|lying|exposed|controversial)\b"),
]


def _words(t: str) -> list[str]:
    return re.findall(r"[a-z0-9'$%]+", t.lower())


def hook_analysis(text: str) -> dict:
    """Score the first line(s) of a clip as a scroll-stopping hook."""
    # a hook lives or dies in the first sentence (~first 3 seconds spoken)
    first = re.split(r"(?<=[.?!])\s+", text.strip())[0]
    if len(first.split()) < 5 and len(text.split()) > len(first.split()):
        first = " ".join(text.split()[:14])
    first = " ".join(first.split()[:16])
    low = first.lower()
    score, hits = 22, []
    for pat, pts, why in HOOK_OPENERS:
        if re.search(pat, low):
            score += pts
            hits.append(why)
    w = _words(first)
    if 4 <= len(w) <= 14:
        score += 8; hits.append("Tight length (4–14 words) — lands fast")
    elif len(w) > 22:
        score -= 8; hits.append("⚠ Hook takes too long — trim the wind-up")
    if any(x in low for x in ("...", "—")):
        score += 5; hits.append("Open loop / trailing thought")
    score = max(5, min(99, score))
    grade = "S" if score >= 85 else "A" if score >= 70 else "B" if score >= 55 else "C" if score >= 40 else "D"
    return {"score": score, "grade": grade, "text": first, "strengths": hits,
            "rewrites": suggest_hooks(text)}


def suggest_hooks(text: str) -> list[str]:
    """Rule-based hook rewrites built from the clip's own strongest phrase."""
    clean = re.sub(r"\s+", " ", text).strip().rstrip(".")
    words = clean.split()
    core = " ".join(words[:12]).rstrip(",")
    # pull out a number phrase if present - numbers make the strongest hooks
    m = re.search(r"[^.?!]*\b\d[\d,.]*\s?(?:k|m|million|billion|%|percent|dollars|days|years)?[^.?!]*", clean, re.I)
    num_phrase = m.group(0).strip()[:80] if m else None
    out = []
    if num_phrase:
        out.append(num_phrase[0].upper() + num_phrase[1:] + " — here's how 👇")
    out.append(f"Nobody talks about this: {core.lower()}…")
    out.append(f"Stop scrolling — {core.lower()}.")
    out.append(f"What if everything you know about this is wrong? {core[0].upper() + core[1:]}.")
    return out[:3]


def _label(text: str) -> str:
    low = text.lower()
    for name, pat in LABELS:
        if re.search(pat, low):
            return name
    return "Key Moment"


def score_window(segs: list[dict], duration_hint: float) -> dict:
    text = " ".join(s["text"] for s in segs)
    w = _words(text)
    secs = max(1.0, segs[-1]["end"] - segs[0]["start"])
    wpm = len(w) / secs * 60
    uniq = len(set(w) - STOPWORDS) / max(1, len(w))
    emotion = sum(1 for x in w if x in EMOTION)
    power = sum(1 for x in w if x in POWER)
    punct = text.count("!") * 3 + text.count("?") * 2
    laugh = len(re.findall(r"laughter|applause|cheering", text.lower())) * 10
    hook = hook_analysis(segs[0]["text"] + " " + (segs[1]["text"] if len(segs) > 1 else ""))
    # pace: 130-185 wpm is the short-form sweet spot
    pace_pts = 15 - min(15, abs(wpm - 158) / 6)
    score = (hook["score"] * 0.38 + min(20, emotion * 2.2) + min(14, power * 1.1)
             + pace_pts + min(10, uniq * 16) + min(10, punct) + min(12, laugh))
    # completeness bonus: ends on a sentence boundary
    if text.strip().endswith((".", "!", "?")):
        score += 5
    return {"score": round(max(3, min(99, score))), "hook": hook, "wpm": round(wpm),
            "emotion_hits": emotion, "label": _label(text)}


def _title(text: str) -> str:
    s = re.split(r"(?<=[.?!])\s+", text.strip())[0]
    s = re.sub(r"^(so|well|and|but|yeah|okay|right)[,\s]+", "", s, flags=re.I)
    s = s.strip().rstrip(".")
    return (s[0].upper() + s[1:])[:72] if s else "Untitled moment"


def _hashtags(text: str) -> list[str]:
    freq = Counter(w for w in _words(text) if w not in STOPWORDS and len(w) > 3)
    tags = [f"#{w}" for w, _ in freq.most_common(4)]
    return tags + ["#clips", "#shorts"]


def analyze_transcript(segments: list[dict], meta: dict | None = None,
                       target_len: float = 38.0) -> dict:
    """segments: [{start, end, text}] -> ranked clip candidates + hook report."""
    meta = meta or {}
    if not segments:
        return {"meta": meta, "moments": [], "opening_hook": None,
                "warning": "No transcript/captions found for this video. "
                           "Paste a transcript, upload a .srt/.vtt file, or use a video with captions."}
    duration = segments[-1]["end"]
    # candidate anchors: every segment, expanded to ~target_len windows
    candidates = []
    for i, seg in enumerate(segments):
        window, j = [seg], i
        while j + 1 < len(segments) and (window[-1]["end"] - seg["start"]) < target_len:
            j += 1; window.append(segments[j])
        if window[-1]["end"] - seg["start"] < 8:      # too short to be a clip
            continue
        sc = score_window(window, duration)
        candidates.append({"start": round(seg["start"], 1),
                           "end": round(window[-1]["end"], 1),
                           "text": " ".join(s["text"] for s in window), **sc})
    # non-max suppression: keep best, drop overlapping (>40%) neighbours
    candidates.sort(key=lambda c: -c["score"])
    kept: list[dict] = []
    for c in candidates:
        if all(min(c["end"], k["end"]) - max(c["start"], k["start"]) <
               0.4 * min(c["end"] - c["start"], k["end"] - k["start"]) for k in kept):
            kept.append(c)
        if len(kept) >= 12:
            break
    kept.sort(key=lambda c: c["start"])
    moments = []
    for rank, c in enumerate(sorted(kept, key=lambda c: -c["score"]), 1):
        text = c["text"]
        recipe = _edit_recipe(c)
        moments.append({
            "rank": rank, "start": c["start"], "end": c["end"],
            "duration": round(c["end"] - c["start"], 1),
            "score": c["score"], "label": c["label"], "wpm": c["wpm"],
            "hook": c["hook"], "title": _title(text),
            "caption": f"{_title(text)} 👀\n\n" + " ".join(_hashtags(text)),
            "hashtags": _hashtags(text), "transcript": text[:3000],
            "why": _why(c),
            "recipe": recipe})
    moments.sort(key=lambda m: m["rank"])
    opening = hook_analysis(" ".join(s["text"] for s in segments[:4]))
    return {"meta": {**meta, "duration": duration}, "moments": moments,
            "opening_hook": opening, "segment_count": len(segments)}


def _why(c: dict) -> list[str]:
    why = []
    if c["hook"]["score"] >= 70: why.append(f"Strong hook ({c['hook']['score']}/100) in the first 3 seconds")
    if c["emotion_hits"] >= 4: why.append("High emotional language — drives comments & shares")
    if 130 <= c["wpm"] <= 185: why.append(f"Fast, retentive pace ({c['wpm']} wpm)")
    if "?" in c["text"]: why.append("Contains a question — viewers stay for the answer")
    if re.search(r"\d", c["text"]): why.append("Specific numbers make the payoff feel concrete")
    return why or ["Self-contained moment with a clean start and end"]


def _edit_recipe(c: dict) -> dict:
    """Return a concrete, copy-pasteable edit plan for the clip: SFX timing,
    BGM suggestion, on-screen text, zoom/spotlight/arrow cues. Rule-based
    so it works without an LLM."""
    text = c["text"]; low = text.lower(); label = c["label"]; hook = c["hook"]
    steps = []
    sfx = []
    # 1) HOOK frame (first 0.4s) — always add a hard cut + subtitle pop
    sfx.append({"t": 0.0, "type": "pop", "note": "Hard cut + subtitle pop-in (0.3s scale 1.2→1)"})
    steps.append("0.00s — Hard cut in; caption word #1 slams on screen (easeOutBack, 0.25s)")
    # Detect pattern-specific cues
    has_number = bool(re.search(r"\b\d", text))
    has_question = "?" in text
    has_negation = bool(re.search(r"\b(never|nobody|stop|don'?t|worst|biggest mistake|lie|myth|secret)\b", low))
    has_reveal = bool(re.search(r"\b(here'?s why|the reason|turns out|here is what|this is why)\b", low))
    has_twist = bool(re.search(r"\b(but|however|until|except)\b", low))
    has_climax = bool(re.search(r"(!|crazy|insane|shocked|wild|unbelievable|blown away)", low))
    if has_number:
        m = re.search(r"\b(\d[\d,.]*\s?(?:k|m|million|billion|%|percent|dollars|days|years)?)", text, re.I)
        if m:
            sfx.append({"t": 0.3, "type": "whoosh", "note": f"Number '{m.group(0)}' flies in as a separate big text layer"})
            steps.append(f"0.30s — 🎯 Big bold number overlay '{m.group(0)}' (yellow, scale 1.4, lands with whoosh SFX)")
    if has_question:
        sfx.append({"t": 0.6, "type": "riser", "note": "Subtle riser SFX under the question"})
        steps.append("0.60s — ❓ Question mark '?' pops beside caption; riser SFX starts")
    if has_negation:
        sfx.append({"t": 0.9, "type": "impact", "note": "Impact/thud when dropping the contrarian claim"})
        steps.append("0.90s — ⚡ Red flash frame (1 frame) + thud SFX on the pattern-interrupt word (nobody/never/stop)")
    if has_reveal:
        sfx.append({"t": 1.5, "type": "reveal", "note": "Bright 'ding' + arrow pointing at speaker at reveal moment"})
        steps.append("1.50s — 💡 Ding SFX + 🔽 arrow pointing down (or at speaker) when you reveal the answer")
    if has_twist:
        sfx.append({"t": 2.0, "type": "record_scratch", "note": "Record scratch / tape stop for the 'but…' pivot"})
        steps.append("2.00s — 🎚 Quick zoom-in (1.05x) + tape-stop SFX on the twist word")
    if has_climax:
        sfx.append({"t": 2.5, "type": "impact", "note": "Cymbal/impact + slow zoom on climax"})
        steps.append("2.50s — 🔊 Impact/cymbal + 🔦 circular spotlight tightens on face; slow zoom 1.08x to end")
    # End-card: subscribe CTA in the last 0.8s
    steps.append(f"{round(max(3, (c['end']-c['start'])-0.8),1)}s — 📍 End card (0.8s): arrow/CTA ('Follow for part 2') fades in bottom-right")
    # BGM suggestion
    bgm_by_label = {
        "Hot Take": "Aggressive hard-trap loop (140 BPM) with 808 sub, sidechained to voice",
        "Funny": "Light playful ukulele or cartoon-boing SFX bed, low volume",
        "Story": "Cinematic piano pad that swells at the climax (60–80 BPM)",
        "Insight": "Minimal lo-fi beat or calm ambient (90 BPM), ducked 12dB under voice",
        "Money": "Hard-money trap beat (dark bells + 808) for finance",
        "Controversy": "Tense drone riser → impact drop on the reveal",
        "Key Moment": "Modern trending TikTok audio (dark Phonk or Jersey Club, 130–150 BPM)",
    }
    bgm = bgm_by_label.get(label, bgm_by_label["Key Moment"])
    # Text-on-screen beat: pop every ~2 words, bold keywords
    text_overlays = []
    if has_number and m:
        text_overlays.append(f"Giant '{m.group(0)}' (0.3–2.0s, yellow, centered above captions)")
    if has_question:
        text_overlays.append("Question as big text at top (0.6s–1.5s)")
    text_overlays.append("Caption style: bold white + 4px black outline, 3 words at a time, karaoke highlight on current word")
    # Zoom/effects
    effects = [
        "Slight 1.04x push-in over the whole clip (Ken Burns) — keeps eyes engaged",
        "First frame: zoom-punch 1.15x→1.00x over 0.3s (hard cut energy)",
    ]
    if has_climax:
        effects.append("At climax: 1.0→1.08x zoom + 0.5s shutter-flash (white flash 10% opacity)")
    if has_twist:
        effects.append("At twist: whip-pan transition or quick zoom spike")
    return {
        "bgm": bgm,
        "sfx": sfx,
        "steps": steps,
        "text_overlays": text_overlays,
        "effects": effects,
        "hook_rewrites": hook["rewrites"],
        "hook_line": hook["text"],
        "hook_grade": hook["grade"],
    }


def parse_captions(raw: str) -> list[dict]:
    """Parse .vtt / .srt / .ttml / youtube .json3 / plain 'mm:ss text' transcripts, de-dupe YouTube rolling captions."""
    raw = raw.strip()
    segs: list[dict] = []

    # Try JSON3 (YouTube's native caption format — yt-dlp often delivers this)
    try:
        import json as _json
        if raw.lstrip().startswith(("{","[")):
            j = _json.loads(raw)
            events = j.get("events") if isinstance(j, dict) else None
            if events:
                for ev in events:
                    t_start = ev.get("tStartMs")
                    dur = ev.get("dDurationMs", 0)
                    segs_utf8 = ev.get("segs") or []
                    text = "".join(s.get("utf8","") for s in segs_utf8).strip()
                    # Skip non-speech events (newlines, music markers) and blank lines
                    if t_start is None or not text or text in ("\n","\r\n"):
                        continue
                    # Clean YouTube annotation tokens like [Music], [Applause]
                    text = _clean_caption_text(text)
                    if text:
                        segs.append({"start": t_start/1000.0,
                                     "end": (t_start + dur)/1000.0 if dur else t_start/1000.0 + 2.0,
                                     "text": text})
                if segs:
                    return _dedup(segs)
    except Exception:
        pass

    def ts(t: str) -> float:
        t = t.replace(",", ".")
        p = [float(x) for x in t.split(":")]
        return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]

    blocks = re.split(r"\n\s*\n", raw)
    timed = False
    for b in blocks:
        m = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3}|\d{1,2}:\d{2}(?::\d{2})?)\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3}|\d{1,2}:\d{2}(?::\d{2})?)", b)
        if m:
            timed = True
            text = b[m.end():]
            # Strip HTML/XML tags (cues like <c>, <00:00:00.000>, <i>, {an8} alignment)
            text = re.sub(r"<[^>]+>", " ", text, flags=re.M)
            # Strip SRT cue numbers (bare lines of digits at end of cue)
            text = re.sub(r"^\s*\d+\s*$", " ", text, flags=re.M)
            text = re.sub(r"\s+", " ", text).strip()
            text = _clean_caption_text(text)
            if text:
                segs.append({"start": ts(m.group(1)), "end": ts(m.group(2)), "text": text})
            continue
        # TTML / SAMI: try <p begin="..." end="...">text</p>
        for pm in re.finditer(r'<p[^>]*\b(?:begin|start)="([^"]+)"[^>]*\b(?:end|dur)="([^"]+)"[^>]*>(.*?)</p>', b, flags=re.S|re.I):
            timed = True
            try:
                s = ts(_ttml_ts(pm.group(1))); e = ts(_ttml_ts(pm.group(2)))
                text = re.sub(r"<[^>]+>", " ", pm.group(3))
                text = re.sub(r"\s+", " ", text).strip()
                text = _clean_caption_text(text)
                if text:
                    segs.append({"start": s, "end": e, "text": text})
            except Exception:
                continue

    if not timed:
        # Strip noisy "mm:ss[.cc] seconds" lead-ins that show up when a non-VTT
        # caption blob (e.g. YouTube srv1/srv2 text) falls through to plain text.
        cleaned = re.sub(r"\d{1,2}:\d{2,3}(?:\.\d+)?\s*seconds", " ", raw)
        cleaned = _clean_caption_text(cleaned)
        words = cleaned.split()
        if words:
            t = 0.0
            for i in range(0, len(words), 18):
                chunk = " ".join(words[i:i + 18])
                segs.append({"start": t, "end": t + len(chunk.split()) / 2.6, "text": chunk})
                t += len(chunk.split()) / 2.6

    return _dedup(segs)


def _ttml_ts(s: str) -> str:
    """Normalise TTML/SAMI time '00:00:02.200' / '2.2s' / '00:00:02:200' to HH:MM:SS.mmm."""
    s = s.strip().rstrip("s").replace(",", ".")
    if re.match(r"^\d+(\.\d+)?$", s):
        # just seconds
        v = float(s); h=int(v//3600); m=int((v%3600)//60); sec=v%60
        return f"{h}:{m:02d}:{sec:06.3f}"
    # colon-separated; convert last separator from ':' to '.' if it looks like frames/ms
    parts = s.split(":")
    if len(parts) == 4:
        # HH:MM:SS:ff
        return f"{parts[0]}:{parts[1]}:{parts[2]}.{parts[3]}"
    if len(parts) == 3 and "." not in parts[2]:
        return f"{parts[0]}:{parts[1]}:{parts[2]}.000"
    return s


def _clean_caption_text(text: str) -> str:
    """Strip caption noise: tags, speaker labels, non-speech markers, alignment codes."""
    if not text:
        return ""
    # Strip HTML/XML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Strip SSA/ASS style overrides like {\an8}
    text = re.sub(r"\{\\[^}]+\}", " ", text)
    # Strip bracketed non-speech events: [Music], [Applause], [Laughter], [ __ ] etc.
    text = re.sub(r"\[[^\[\]]{1,40}\]", " ", text, flags=re.I)
    # Strip ">>" speaker prefixes
    text = re.sub(r"^[>\s-]+", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _dedup(segs: list[dict]) -> list[dict]:
    """De-dupe rolling auto-captions (each line repeats the previous one)."""
    out: list[dict] = []
    for s in segs:
        if out and (s["text"] == out[-1]["text"] or out[-1]["text"].endswith(s["text"])):
            out[-1]["end"] = s["end"]; continue
        if out and s["text"].startswith(out[-1]["text"]):
            new_text = s["text"][len(out[-1]["text"]):].strip()
            if not new_text:
                out[-1]["end"] = s["end"]; continue
            s = {**s, "text": new_text}
        out.append(s)
    return out


# ---------------------------------------------------------------- demo data
DEMO_TEXT = [
    "welcome back to the show so today we are talking about growing on social media",
    "nobody talks about this but the first three seconds decide everything about your video",
    "stop posting content and start posting moments that make people feel something real",
    "i lost eleven thousand dollars on my first launch and here is exactly what i learned",
    "the reason you are not growing is because your hook promises nothing specific at all",
    "imagine posting one video and waking up to two hundred thousand new followers overnight",
    "here is the framework first open with a number then create a curiosity gap immediately",
    "second never start with your logo nobody cares about your logo in second one ever",
    "the biggest mistake creators make is saving the best part for the end of the video",
    "what if i told you one clip made more money than my entire first year of posting",
    "you do not need better content you need a better first sentence that creates tension",
    "and that is why every viral clip starts in the middle of the action not the beginning",
    "try this tomorrow post the ending first and watch your retention double in a week",
    "thanks for watching subscribe for more creator breakdowns every single week right here",
]
DEMO, _t = [], 0.0
for _txt in DEMO_TEXT:                      # ~2.6 spoken words/sec, like a real transcript
    _dur = len(_txt.split()) / 2.6
    DEMO.append({"start": round(_t, 1), "end": round(_t + _dur, 1), "text": _txt})
    _t += _dur + 0.4
