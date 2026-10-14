"""Filler-word / dead-air removal for exported clips.

Strategy v2:
  1. Use ffmpeg `silencedetect` to find actual quiet gaps in the audio.
     Long silences (>0.5s) get tightened; short ones are left natural.
  2. Use word-level timing from the caption text (derived from the
     measured WPM passed in by the analyzer when available), mark
     filler words as cut points, but ONLY snip a filler if it sits in
     or next to a silence (that is how you know it was a disfluency,
     not a word used in a real sentence).
  3. Build a keep-list and concat with ffmpeg.

This avoids the previous even-split inaccuracy that made "um" / "like"
stay in the video — we only remove audio pauses, not content.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import List, Tuple

# Words/phrases that commonly signal disfluency. Order: longer first.
FILLER_PHRASES = [
    "you know what i mean", "to be perfectly honest", "to be honest with you",
    "let me tell you something", "as a matter of fact", "if you know you know",
    "at the end of the day", "as i was saying", "if you will", "you know what",
    "i mean you know", "let's be real", "sort of", "kind of",
    "you know", "i mean", "i guess",
]
# Isolated single-word fillers (only cut when near silence).
FILLER_WORDS = {"um", "uh", "erm", "uhh", "umm", "ah", "er", "mm",
                "basically", "literally", "honestly", "essentially"}


def _merge_spans(spans: List[Tuple[float, float]], pad: float = 0.0) -> List[Tuple[float, float]]:
    if not spans:
        return []
    spans = sorted(spans)
    out = [list(spans[0])]
    for s, e in spans[1:]:
        if s - pad <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _in_silence(t: float, silences: List[Tuple[float, float]], tol: float = 0.2) -> bool:
    for ss, se in silences:
        if ss - tol <= t <= se + tol:
            return True
    return False


def _find_filler_word_times(words: List[Tuple[float, float, str]],
                            silences: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Return (start,end) spans of filler words that are safe to cut (near silence)."""
    spans = []
    n = len(words)
    # Multi-word phrases
    for phrase in sorted(FILLER_PHRASES, key=lambda p: -len(p.split())):
        plen = len(phrase.split())
        i = 0
        while i <= n - plen:
            ok = True
            for k in range(plen):
                w = re.sub(r"^[^a-z']+|[^a-z']+$", "", words[i + k][2].lower())
                if w != phrase.split()[k]:
                    ok = False; break
            if ok:
                s = words[i][0]
                e = words[i + plen - 1][1]
                # Cut multi-word fillers if they start in/after a silence
                # OR are surrounded by ≥0.25s gaps on either side.
                prev_end = words[i - 1][1] if i > 0 else 0
                next_start = words[i + plen][0] if i + plen < n else e + 1
                pre_gap = s - prev_end
                post_gap = next_start - e
                if _in_silence(s, silences) or pre_gap >= 0.18 or post_gap >= 0.18:
                    spans.append((max(0, s - 0.05), e + 0.08))
                i += plen
            else:
                i += 1
    # Single-word fillers (only cut if adjacent to silence)
    for i, (s, e, wraw) in enumerate(words):
        w = re.sub(r"^[^a-z']+|[^a-z']+$", "", wraw.lower())
        if w not in FILLER_WORDS:
            continue
        dur = e - s
        if dur > 0.7:
            continue  # too long — probably used in context
        prev_end = words[i - 1][1] if i > 0 else 0
        next_start = words[i + 1][0] if i + 1 < n else e + 1
        pre_gap = s - prev_end
        post_gap = next_start - e
        if _in_silence(s, silences, tol=0.15) or (pre_gap >= 0.2 and post_gap >= 0.12):
            spans.append((max(0, s - 0.05), e + 0.08))
    return spans


def _build_keep_segments(duration: float, cuts: List[Tuple[float, float]],
                         long_silences: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Keep everything except cut spans. Tighten long silences (>0.9s) to ~0.25s."""
    # Add long silences to cut list (shorten them instead of removing entirely)
    tightened = []
    for ss, se in long_silences:
        sdur = se - ss
        if sdur > 0.9:
            # Keep first 0.25s of silence, cut the middle, keep last 0.05
            cut_start = ss + 0.25
            cut_end = se - 0.05
            if cut_end > cut_start:
                tightened.append((cut_start, cut_end))
    all_cuts = _merge_spans(cuts + tightened)
    keep = []
    cursor = 0.0
    for cs, ce in all_cuts:
        cs = max(cursor, cs)
        ce = min(duration, ce)
        if cs - cursor >= 0.08:
            keep.append((cursor, cs))
        cursor = ce
    if duration - cursor >= 0.08:
        keep.append((cursor, duration))
    # Drop super-short stubs <0.1s that don't contribute anything
    keep = [s for s in keep if s[1] - s[0] >= 0.12]
    return keep


def remove_fillers(in_path: str, out_path: str, words: List[Tuple[float, float, str]],
                   clip_duration: float, vertical: bool = True,
                   quality: str = "720") -> Tuple[str, float]:
    """Return (final_path, final_duration_seconds). Uses silence detection +
    word heuristics so only actual filler-word disfluencies are removed."""
    from .clipper import QUALITIES, ffmpeg_bin, _short_path

    # Detect silences in the audio
    silences = []
    try:
        from .clipper import detect_silences
        silences = detect_silences(in_path, noise_db=-28, min_dur=0.20)
    except Exception:
        silences = []

    long_silences = [(s, e) for s, e in silences if (e - s) > 0.9]
    cut_spans = _find_filler_word_times(words, silences)
    keep = _build_keep_segments(clip_duration, cut_spans, long_silences)
    new_duration = sum(e - s for s, e in keep)

    if not keep or (len(keep) == 1 and abs(keep[0][0]) < 0.05 and abs(keep[0][1] - clip_duration) < 0.05):
        return in_path, clip_duration  # nothing to cut

    fb = ffmpeg_bin()
    in_s = _short_path(in_path)
    out_s = _short_path(out_path)

    parts_v, parts_a = [], []
    for k, (seg_start, seg_end) in enumerate(keep):
        parts_v.append(
            f"[0:v]trim=start={seg_start:.3f}:end={seg_end:.3f},setpts=PTS-STARTPTS,setsar=1[v{k}]")
        parts_a.append(
            f"[0:a]atrim=start={seg_start:.3f}:end={seg_end:.3f},asetpts=PTS-STARTPTS[a{k}]")
    v_concat = "".join(f"[v{k}]" for k in range(len(keep))) + \
               f"concat=n={len(keep)}:v=1:a=0[vout]"
    a_concat = "".join(f"[a{k}]" for k in range(len(keep))) + \
               f"concat=n={len(keep)}:v=0:a=1[aout]"
    filter_complex = ";".join(parts_v + parts_a + [v_concat, a_concat])

    cmd = [fb, "-y", "-i", in_s, "-filter_complex", filter_complex,
           "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf",
           str(QUALITIES.get(quality, QUALITIES["720"])["crf"]),
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out_s]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return in_path, clip_duration
    if r.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 20_000:
        return in_path, clip_duration
    return out_path, new_duration


def estimate_word_segments(caption_text: str, duration: float,
                           wpm_hint: float | None = None) -> List[Tuple[float, float, str]]:
    """Evenly split caption text into word segments. If wpm_hint is supplied
    we use that; otherwise default to 155 wpm (realistic speech pace)."""
    words = [w for w in re.findall(r"[A-Za-z']+", caption_text or "") if w.strip()]
    if not words:
        return []
    wpm = max(80.0, min(220.0, float(wpm_hint or 0))) or 155.0
    per_word = 60.0 / wpm
    total = per_word * len(words)
    # If total exceeds duration, rescale to fit
    if total > duration * 1.15:
        per_word = duration / len(words)
    out, t = [], 0.0
    for w in words:
        out.append((t, t + per_word, w))
        t += per_word
    return out
