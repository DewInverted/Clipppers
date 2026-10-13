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
        moments.append({
            "rank": rank, "start": c["start"], "end": c["end"],
            "duration": round(c["end"] - c["start"], 1),
            "score": c["score"], "label": c["label"], "wpm": c["wpm"],
            "hook": c["hook"], "title": _title(text),
            "caption": f"{_title(text)} 👀\n\n" + " ".join(_hashtags(text)),
            "hashtags": _hashtags(text), "transcript": text[:600],
            "why": _why(c)})
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


def parse_captions(raw: str) -> list[dict]:
    """Parse .vtt / .srt / plain 'mm:ss text' transcripts, de-dupe YouTube rolling captions."""
    raw = raw.strip()
    segs: list[dict] = []

    def ts(t: str) -> float:
        t = t.replace(",", ".")
        p = [float(x) for x in t.split(":")]
        return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]

    blocks = re.split(r"\n\s*\n", raw)
    timed = False
    for b in blocks:
        m = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}|\d{1,2}:\d{2}(?::\d{2})?)\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}|\d{1,2}:\d{2}(?::\d{2})?)", b)
        if m:
            timed = True
            text = b[m.end():]
            text = re.sub(r"<[^>]+>|\d+\s*$", " ", text, flags=re.M)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                segs.append({"start": ts(m.group(1)), "end": ts(m.group(2)), "text": text})
    if not timed:  # plain text: fake timestamps, ~2.6 words/sec
        words, t = raw.split(), 0.0
        for i in range(0, len(words), 18):
            chunk = " ".join(words[i:i + 18])
            segs.append({"start": t, "end": t + len(chunk.split()) / 2.6, "text": chunk})
            t += len(chunk.split()) / 2.6
    # de-dupe rolling auto-captions (each line repeats the previous one)
    out: list[dict] = []
    for s in segs:
        if out and (s["text"] == out[-1]["text"] or out[-1]["text"].endswith(s["text"])):
            out[-1]["end"] = s["end"]; continue
        if out and s["text"].startswith(out[-1]["text"]):
            s = {**s, "text": s["text"][len(out[-1]["text"]):].strip()}
            if not s["text"]: continue
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
