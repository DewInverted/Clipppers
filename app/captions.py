"""Burned-in caption styles (the ones that dominate Shorts/TikTok/Reels).

Captions are rendered as an .ass subtitle file and burned in with ffmpeg.
Word timing is estimated evenly across the clip (captions from yt-dlp are
sentence-level), chunked 2-4 words at a time like real short-form captions.
"""
from __future__ import annotations

# name -> ffmpeg/ASS style definition
# accent: list of words that get colored pop; accent_color: ASS color BGR for those
STYLES = {
    "tiktok":   dict(label="⚡ TikTok Bounce — one word at a time, pop-in (Devin Jatho style)", font="DejaVu Sans", bold=1,
                     size=62, primary="&H00FFFFFF", highlight="&H0000E5FF", outline="&H00000000", back="&H00000000",
                     border=8, shadow=0, align=2, margin_v=260, uppercase=True, word_by_word=True, chunk=1,
                     pop=True),
    "hormozi":  dict(label="🟨 Hormozi — bold, word-by-word yellow highlight", font="DejaVu Sans", bold=1,
                     size=52, primary="&H00FFFFFF", highlight="&H0000E5FF", outline="&H00000000", back="&H00000000",
                     border=6, shadow=2, align=2, margin_v=220, uppercase=True, word_by_word=True, chunk=3),
    "mrbeast":  dict(label="🔥 MrBeast — huge centred pop captions", font="DejaVu Sans", bold=1,
                     size=58, primary="&H00FFFFFF", highlight="&H0033CCFF", outline="&H00000000", back="&H80000000",
                     border=7, shadow=0, align=2, margin_v=240, uppercase=True, word_by_word=False, chunk=3),
    "karaoke":  dict(label="🎤 Karaoke — word-by-word cyan sweep", font="DejaVu Sans", bold=1,
                     size=46, primary="&H88FFFFFF", highlight="&H00FFFF00", outline="&H00000000", back="&H00000000",
                     border=5, shadow=1, align=2, margin_v=200, uppercase=False, word_by_word=True, chunk=4),
    "neon":     dict(label="💜 Neon Pop — magenta glow, centre screen", font="DejaVu Sans", bold=1,
                     size=48, primary="&H00FF66FF", highlight="&H00FFFF00", outline="&H00660066", back="&H00000000",
                     border=4, shadow=3, align=2, margin_v=220, uppercase=True, word_by_word=False, chunk=3),
    "minimal":  dict(label="⬜ Minimal — clean small white, bottom", font="DejaVu Sans", bold=0,
                     size=36, primary="&H00FFFFFF", highlight="&H00FFFFFF", outline="&H00000000", back="&H90000000",
                     border=2, shadow=0, align=2, margin_v=140, uppercase=False, word_by_word=False, chunk=5),
    "cinematic": dict(label="🎬 Cinematic — elegant lower-third", font="DejaVu Serif", bold=0,
                     size=38, primary="&H00F5F5F5", highlight="&H00F5F5F5", outline="&H00000000", back="&H00000000",
                     border=2, shadow=1, align=1, margin_v=120, uppercase=False, word_by_word=False, chunk=6),
}

# Words that get colored accent in the 'tiktok' bounce style (money/negatives/
# superlatives/power). Colours are ASS BGR: yellow = &H0000E5FF, red = &H000000FF,
# cyan = &H00FFFF00, lime = &H0000FF66.
ACCENT_WORDS = {
    "&H0000E5FF": {"never","always","stop","secret","truth","lie","myth","biggest","worst","best",
                   "crazy","insane","massive","huge","literally","actually","exactly"},
    "&H000000FF": {"money","dollars","rich","broke","profit","revenue","scam","stupid","dangerous",
                   "illegal","banned","destroyed","ruined","killed"},
    "&H00FFFF00": {"you","your","yourself","you're","you'll","you've"},
    "&H0000FF66": {"%","$","million","billion","thousand","dollars"},
}

def _accent_color(word: str) -> str:
    w = word.lower().strip(".,!?;:\"'()")
    for col, words in ACCENT_WORDS.items():
        if w in words:
            return col
        if any(ch.isdigit() for ch in w) and col == "&H0000FF66":
            return col
    return "&H00FFFFFF"  # default white

STYLE_CHOICES = ["none"] + list(STYLES)


def _ts(sec: float) -> str:
    # Clamp small negatives from rounding to 0
    sec = max(0.0, float(sec))
    h = int(sec // 3600); m = int(sec % 3600 // 60); s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(text: str, duration: float, style_key: str, out_path: str,
              width: int = 720, height: int = 1280,
              word_timings: list | None = None,
              font_size: int | None = None,
              margin_v: int | None = None) -> str:
    """Build an ASS subtitle file.

    If word_timings is passed, it's a list of (start_sec_from_clip_start,
    end_sec_from_clip_start, word) — used to get accurate per-chunk timing
    instead of an even split across the whole clip. This fixes captions
    that drift or say the wrong thing because of pauses / music / gaps.

    font_size / margin_v let callers override per-export (so users can
    resize / reposition captions without editing styles.py).
    """
    st = dict(STYLES[style_key])
    if font_size is not None:
        st["size"] = int(font_size)
    if margin_v is not None:
        st["margin_v"] = int(margin_v)
    words = [w for w in (text or "").replace("\n", " ").split() if w.strip()]
    if not words:
        raise ValueError("No caption text for that range — analyse with a transcript first, "
                         "or type caption text in the manual cutter.")
    if st["uppercase"]:
        words = [w.upper() for w in words]

    chunk = st["chunk"]
    GAP = 0.04  # 40ms gap between caption groups to prevent overlap flash

    # Build chunk-level (start, end, text) from either precise word timings
    # or an even split fallback.
    if word_timings and len(word_timings) >= len(words):
        # Use provided timings — already clip-relative seconds
        wt = [(max(0.0, s), max(0.0, e), w) for s, e, w in word_timings[:len(words)]]
        # Uppercase if needed
        if st["uppercase"]:
            wt = [(s, e, w.upper()) for s, e, w in wt]
        # Ensure monotonic non-overlap: cap each word's end to the next word's start
        for i in range(len(wt) - 1):
            s, e, w = wt[i]
            ns = wt[i+1][0]
            if e > ns:
                e = ns - 0.005  # tiny safety gap
            wt[i] = (s, max(s + 0.08, e), w)
        # Re-cap last word
        s, e, w = wt[-1]
        wt[-1] = (s, min(duration, max(s + 0.08, e)), w)

        events = []
        for gi in range(0, len(wt), chunk):
            group = wt[gi:gi + chunk]
            g_start = group[0][0]
            g_end = group[-1][1]
            # Ensure no gap between groups is negative (start of this group must be >= end of last event)
            if events and g_start < events[-1][1] + 0.001:
                g_start = events[-1][1] + 0.001
            if st.get("word_by_word"):
                for wi, (ws, we, w) in enumerate(group):
                    if wi + 1 < len(group):
                        w_end = group[wi+1][0] - 0.005
                    else:
                        w_end = we
                    # Bounce pop style: one word per frame, accent color, scale 1.6→1.0
                    if st.get("pop"):
                        w_dur = max(0.22, w_end - ws)
                        col = _accent_color(w)
                        pop_cs = 8  # 8 cs = 0.08s fast bounce
                        # Start word at 150% scale then \tween down to 100% with
                        # a slight overshoot (paccel=3 gives an ease-out bounce).
                        pop_tag = (f"{{\\an5\\1c{col}\\b1\\bord8\\shad0\\fscx150\\fscy150"
                                   f"\\t(0,{pop_cs},3,\\fscx100\\fscy100)}}")
                        shown = pop_tag + w
                    else:
                        w_dur = max(0.10, w_end - ws)
                        shown = " ".join(
                            (f"{{\\1c{st['highlight']}\\b1}}{gw}{{\\r}}" if j == wi else gw)
                            for j, (_, _, gw) in enumerate(group))
                    w_start = ws
                    if events and w_start < events[-1][1] + 0.001:
                        w_start = events[-1][1] + 0.001
                    w_end = w_start + w_dur
                    events.append((w_start, min(duration, w_end), shown))
            else:
                events.append((g_start, min(duration, g_end), " ".join(w for _, _, w in group)))
    else:
        # Fallback even split (used for manual cutter / when no timings available).
        per_word = duration / max(1, len(words))
        groups = [words[i:i + chunk] for i in range(0, len(words), chunk)]
        events, clock = [], 0.0
        for group in groups:
            g_dur = per_word * len(group) - GAP
            if st["word_by_word"]:
                wpw = per_word - 0.005
                for wi, word in enumerate(group):
                    shown = " ".join(
                        (f"{{\\1c{st['highlight']}\\b1}}{w}{{\\r}}" if j == wi else w)
                        for j, w in enumerate(group))
                    events.append((clock, clock + wpw, shown))
                    clock += wpw
                clock += GAP
            else:
                events.append((clock, clock + g_dur, " ".join(group)))
                clock += g_dur + GAP
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{st['font']},{st['size']},{st['primary']},&H000000FF,{st['outline']},{st['back']},{-st['bold']},0,0,0,100,100,0,0,1,{st['border']},{st['shadow']},{st['align']},40,40,{st['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    body = "\n".join(f"Dialogue: 0,{_ts(a)},{_ts(b)},Main,,0,0,0,,{t}" for a, b, t in events)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + body + "\n")
    return out_path
