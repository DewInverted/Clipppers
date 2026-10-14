"""Burned-in caption styles (the ones that dominate Shorts/TikTok/Reels).

Captions are rendered as an .ass subtitle file and burned in with ffmpeg.
Word timing is estimated evenly across the clip (captions from yt-dlp are
sentence-level), chunked 2-4 words at a time like real short-form captions.
"""
from __future__ import annotations

# name -> ffmpeg/ASS style definition
STYLES = {
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

STYLE_CHOICES = ["none"] + list(STYLES)


def _ts(sec: float) -> str:
    # Clamp small negatives from rounding to 0
    sec = max(0.0, float(sec))
    h = int(sec // 3600); m = int(sec % 3600 // 60); s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(text: str, duration: float, style_key: str, out_path: str,
              width: int = 720, height: int = 1280,
              word_timings: list | None = None) -> str:
    """Build an ASS subtitle file.

    If word_timings is passed, it's a list of (start_sec_from_clip_start,
    end_sec_from_clip_start, word) — used to get accurate per-chunk timing
    instead of an even split across the whole clip. This fixes captions
    that drift or say the wrong thing because of pauses / music / gaps.
    """
    st = STYLES[style_key]
    words = [w for w in (text or "").replace("\n", " ").split() if w.strip()]
    if not words:
        raise ValueError("No caption text for that range — analyse with a transcript first, "
                         "or type caption text in the manual cutter.")
    if st["uppercase"]:
        words = [w.upper() for w in words]

    chunk = st["chunk"]

    # Build chunk-level (start, end, text) from either precise word timings
    # or an even split fallback.
    if word_timings and len(word_timings) >= len(words):
        # Use provided timings — already clip-relative seconds
        wt = [(max(0.0, s), max(0.0, e), w) for s, e, w in word_timings[:len(words)]]
        # Uppercase if needed
        if st["uppercase"]:
            wt = [(s, e, w.upper()) for s, e, w in wt]
        events = []
        for gi in range(0, len(wt), chunk):
            group = wt[gi:gi + chunk]
            g_start = group[0][0]
            g_end = group[-1][1]
            if st["word_by_word"]:
                per_word_durs = [(group[wi+1][0] - group[wi][0]) if wi+1 < len(group)
                                 else (group[wi][1] - group[wi][0])
                                 for wi in range(len(group))]
                clock = g_start
                for wi, (ws, we, w) in enumerate(group):
                    w_dur = max(0.08, we - ws)
                    shown = " ".join(
                        (f"{{\\1c{st['highlight']}\\b1}}{gw}{{\\r}}" if j == wi else gw)
                        for j, (_, _, gw) in enumerate(group))
                    events.append((clock, clock + w_dur, shown))
                    clock += w_dur
            else:
                events.append((g_start, g_end, " ".join(w for _, _, w in group)))
    else:
        # Fallback even split (used for manual cutter / when no timings available).
        # We still honour chunk durations and use realistic WPM.
        per_word = duration / max(1, len(words))
        groups = [words[i:i + chunk] for i in range(0, len(words), chunk)]
        events, clock = [], 0.0
        for group in groups:
            g_dur = per_word * len(group)
            if st["word_by_word"]:
                for wi, word in enumerate(group):
                    shown = " ".join(
                        (f"{{\\1c{st['highlight']}\\b1}}{w}{{\\r}}" if j == wi else w)
                        for j, w in enumerate(group))
                    events.append((clock, clock + per_word, shown))
                    clock += per_word
            else:
                events.append((clock, clock + g_dur, " ".join(group)))
                clock += g_dur
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
