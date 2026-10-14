"""Real clip cutting with ffmpeg (binary bundled via imageio-ffmpeg — no system install).

Platform aspect ratios (all padded into standard H.264 dimensions):
  tiktok / shorts / reels  → 9:16  (1080x1920) — TikTok, YT Shorts, IG Reels
  ig_square                → 1:1   (1080x1080) — Instagram feed square
  ig_portrait              → 4:5   (1080x1350) — Instagram feed portrait
  youtube / twitter / fb   → 16:9  (1920x1080) — YouTube long-form, Twitter/X, FB
  story                    → 9:16  (1080x1920) — IG/FB Stories (same as shorts)

Captions are positioned with platform-specific bottom-margin so they don't
get covered by UI chrome (TikTok caption box, IG reply bar, YouTube title).
"""
from __future__ import annotations

import os
import re
import subprocess

# (w, h) per platform at 1080 tier; 720/480 scale proportionally.
ASPECTS = {
    "tiktok":    (1080, 1920),   # 9:16
    "shorts":    (1080, 1920),   # 9:16 (YT Shorts = same as TikTok)
    "reels":     (1080, 1920),   # 9:16 (IG Reels = same)
    "story":     (1080, 1920),   # 9:16 (IG/FB Stories)
    "ig_square": (1080, 1080),   # 1:1 IG feed square
    "ig_portrait":(864, 1080),   # 4:5 IG feed portrait
    "youtube":   (1920, 1080),   # 16:9 YouTube long-form
    "horizontal":(1920, 1080),   # alias 16:9
}

# Safe-zone bottom-margin (pixels at 1280 canvas height) — how far from the
# bottom edge captions must sit to avoid platform UI chrome. Values are tuned
# to where each app puts its caption/like/comment bar.
PLATFORM_CAPTION_MARGIN = {
    "tiktok":      320,  # TikTok has caption/UI in bottom ~25%; push captions up
    "shorts":      280,  # YT Shorts bottom UI slightly smaller
    "reels":       300,  # IG Reels
    "story":       260,  # IG/FB Stories
    "ig_square":   140,  # square feed, generous
    "ig_portrait": 200,  # IG portrait feed
    "youtube":     120,  # landscape, lower third
    "horizontal":  120,
}

QUALITIES = {
    "1080": dict(label="1080p · best quality"),
    "720":  dict(label="720p · balanced (recommended)"),
    "480":  dict(label="480p · small file, fast upload"),
}

# Resolve (w,h) per quality tier + platform. For non-1080 tiers, scale the
# native 1080p canvas so its longer side matches the tier (720 or 480).
def _res(platform: str, quality: str) -> tuple[int, int]:
    pw, ph = ASPECTS.get(platform, ASPECTS["tiktok"])
    q = quality if quality in QUALITIES else "720"
    if q == "1080":
        return (pw, ph)
    long_side = 720 if q == "720" else 480
    native_long = max(pw, ph)
    return (round(pw * long_side / native_long), round(ph * long_side / native_long))
    return (pw * 480 // (ph if pw >= ph else pw), ph * 480 // (ph if pw >= ph else pw))

# Target integrated loudness per platform (LUFS). ffmpeg loudnorm is used to
# hit these so clips don't sound quiet vs. the platform norm.
PLATFORM_LUFS = {
    "tiktok":      -14,
    "shorts":      -14,
    "reels":       -14,   # IG/FB ~-14 LUFS
    "story":       -14,
    "ig_square":   -14,
    "ig_portrait": -14,
    "youtube":     -14,
    "horizontal":  -14,
}

FFMPEG_TIMEOUT = 900
THUMB_OFFSET = 1.0


def _short_path(p: str) -> str:
    """Windows 8.3 short-path helper to bypass MAX_PATH / WinError 206."""
    if os.name != "nt" or not p:
        return p
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        buf = ctypes.create_unicode_buffer(512)
        n = k32.GetShortPathNameW(p, buf, 512)
        if n and n < 512 and buf.value:
            return buf.value
    except Exception:
        pass
    return p


def ffmpeg_bin() -> str:
    import shutil
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        return sys_ff
    try:
        import imageio_ffmpeg
        return _short_path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return "ffmpeg"


def _build_filter(w: int, h: int, crop_mode: str,
                  caption_ass: str | None, start: float, end: float,
                  lufs: float = -14.0):
    """Build filter_complex: trim+PTS reset, framing to exact w/h, audio loudnorm, optional subs."""
    parts = []
    # Target aspect as a rational expression for ffmpeg crop eval
    target_ar = f"{w}/{h}"
    # 1) Trim + reset PTS + audio loudnorm (broadcast -14 LUFS)
    parts.append(
        f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,fps=30,setsar=1[vt];"
        f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,"
        f"loudnorm=I={lufs}:TP=-1:LRA=11[at];"
    )
    # 2) Framing [vt] -> [vframed]
    # Normalize mode: accept "crop" (old name) as alias for "zoom"
    mode = crop_mode
    if mode == "crop":
        mode = "zoom"
    if mode == "zoom":
        # Zoom & center-crop to fill the target canvas exactly (no bars, no blur)
        parts.append(
            f"[vt]crop='if(gt(iw/ih,{target_ar}),ih*{target_ar},iw)':"
            f"'if(gt(iw/ih,{target_ar}),ih,iw/({target_ar}))',"
            f"scale={w}:{h}:flags=lanczos,setsar=1[vframed];"
        )
    elif mode == "black":
        # Letterbox/pillarbox on pure black (cinematic, no blur)
        parts.append(
            f"[vt]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[vframed];"
        )
    elif mode == "blur":
        parts.append(
            f"[vt]split=2[bg][fg];"
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},boxblur=20:2,setsar=1[bgblur];"
            f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1[fgfit];"
            f"[bgblur][fgfit]overlay=(W-w)/2:(H-h)/2:format=auto,setsar=1[vframed];"
        )
    else:  # fallback = blur
        parts.append(
            f"[vt]split=2[bg][fg];"
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},boxblur=20:2,setsar=1[bgblur];"
            f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1[fgfit];"
            f"[bgblur][fgfit]overlay=(W-w)/2:(H-h)/2:format=auto,setsar=1[vframed];"
        )
    # 3) Subtitles on [vframed] -> [vout]
    if caption_ass:
        escaped = _short_path(caption_ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        parts.append(f"[vframed]subtitles='{escaped}'[vout]")
        v_label = "[vout]"
    else:
        v_label = "[vframed]"
    return "".join(parts), v_label


def cut(src: str, start: float, end: float, out: str, vertical: bool = True,
        quality: str = "720", caption_ass: str | None = None,
        crop_mode: str = "blur", platform: str = "tiktok") -> str:
    # platform drives canvas dimensions; `vertical` kept for backward compat but ignored
    w, h = _res(platform, quality)
    crf = {"1080": 18, "720": 21, "480": 24}.get(quality, 21)
    lufs = PLATFORM_LUFS.get(platform, -14)
    dur = max(1.0, end - start)
    src_s = _short_path(src); out_s = _short_path(out)
    filter_complex, vmap = _build_filter(w, h, crop_mode, caption_ass, start, end, lufs=lufs)
    cmd = [ffmpeg_bin(), "-y", "-i", src_s,
           "-filter_complex", filter_complex,
           "-map", vmap, "-map", "[at]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
           "-avoid_negative_ts", "make_zero",
           "-t", f"{dur+0.1:.3f}", out_s]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        if os.path.exists(out_s):
            try: os.remove(out_s)
            except OSError: pass
        raise RuntimeError(f"ffmpeg timed out after {FFMPEG_TIMEOUT}s — try a shorter clip or 480p.")
    except FileNotFoundError as e:
        raise RuntimeError(
            f"ffmpeg binary could not be launched ({e}). Make sure ffmpeg or imageio-ffmpeg is installed.")
    if r.returncode != 0 or not os.path.exists(out_s) or os.path.getsize(out_s) < 1024:
        err_tail = (r.stderr or "").strip().splitlines()
        err_msg = err_tail[-1] if err_tail else "unknown ffmpeg error"
        raise RuntimeError(f"ffmpeg failed: {err_msg[-400:]}")
    return out


def detect_silences(video_path: str, noise_db: float = -30.0, min_dur: float = 0.25) -> list[tuple[float, float]]:
    """Run ffmpeg silencedetect and return a list of (start, end) silent intervals in seconds."""
    vp = _short_path(video_path)
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostats", "-i", vp,
           "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
           "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:
        return []
    out = r.stderr or ""
    silences = []
    starts = re.findall(r"silence_start:\s*([0-9.]+)", out)
    ends   = re.findall(r"silence_end:\s*([0-9.]+)", out)
    for s, e in zip(starts, ends):
        try:
            silences.append((float(s), float(e)))
        except ValueError:
            continue
    return silences


def make_thumbnail(video_path: str, out_path: str, offset: float = THUMB_OFFSET,
                   width: int = 480) -> str:
    if not os.path.exists(video_path):
        raise RuntimeError("cannot make thumbnail — clip file missing")
    vp = _short_path(video_path)
    op = _short_path(out_path)
    for try_off in (offset, 0.5, 0.1):
        cmd = [ffmpeg_bin(), "-y", "-ss", f"{try_off:.2f}", "-i", vp,
               "-frames:v", "1", "-q:v", "3", "-vf", f"scale={width}:-2", op]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return out_path
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
    cmd = [ffmpeg_bin(), "-y", "-i", vp, "-frames:v", "1", "-q:v", "3",
           "-vf", f"scale={width}:-2", op]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        raise RuntimeError(f"thumbnail generation failed: {e}")
    if r.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError("ffmpeg could not extract a thumbnail frame")
    return out
