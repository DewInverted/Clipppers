"""Real clip cutting with ffmpeg (binary bundled via imageio-ffmpeg — no system install)."""
from __future__ import annotations

import os
import re
import subprocess

QUALITIES = {
    "1080": dict(vertical=(1080, 1920), horizontal=(1920, 1080), crf=18, label="1080p · best quality"),
    "720":  dict(vertical=(720, 1280),  horizontal=(1280, 720),  crf=21, label="720p · balanced (recommended)"),
    "480":  dict(vertical=(480, 854),   horizontal=(854, 480),   crf=24, label="480p · small file, fast upload"),
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


def _build_filter(w: int, h: int, vertical: bool, crop_mode: str,
                  caption_ass: str | None, start: float, end: float) -> str:
    """Build a single filter_complex graph that:
      1. trims [0:v] and [0:a] to [start..end] and resets PTS to 0
         (so all downstream filters see clip-relative time = 0 at clip start)
      2. applies vertical/horizontal framing
      3. burns in subtitles (which now see correct 0-based timestamps)
    This is THE fix for captions appearing on a completely different part
    of the video: the subtitles filter must run after PTS reset.
    """
    dur = max(0.1, end - start)
    parts = []
    # 1) Trim + reset PTS
    parts.append(
        f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,fps=30,setsar=1[vt];"
        f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[at];"
    )
    # 2) Framing on [vt] -> [vframed]
    if vertical and crop_mode == "crop":
        parts.append(
            f"[vt]crop='if(gt(iw/ih,9/16),ih*9/16,iw)':'if(gt(iw/ih,9/16),ih,iw*16/9)',"
            f"scale={w}:{h}:flags=lanczos,setsar=1[vframed];"
        )
    elif vertical:  # blur (default)
        parts.append(
            f"[vt]split=2[bg][fg];"
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},boxblur=20:2,setsar=1[bgblur];"
            f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1[fgfit];"
            f"[bgblur][fgfit]overlay=(W-w)/2:(H-h)/2:format=auto,setsar=1[vframed];"
        )
    else:
        parts.append(
            f"[vt]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[vframed];"
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
        crop_mode: str = "blur") -> str:
    q = QUALITIES.get(quality, QUALITIES["720"])
    w, h = q["vertical"] if vertical else q["horizontal"]
    dur = max(1.0, end - start)

    src_s = _short_path(src)
    out_s = _short_path(out)

    filter_complex, vmap = _build_filter(w, h, vertical, crop_mode, caption_ass, start, end)

    # IMPORTANT: do NOT pass -ss/-t with -vf when using trim/atrim in the filter
    # graph, and do NOT put -ss before -i. We map the labelled pads and use -t
    # as a safety cap. trim+setpts is what gives frame-accurate cuts with PTS
    # starting at 0, so the subtitles filter renders at the right time.
    cmd = [ffmpeg_bin(), "-y", "-i", src_s,
           "-filter_complex", filter_complex,
           "-map", vmap, "-map", "[at]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(q["crf"]),
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
           "-avoid_negative_ts", "make_zero",
           "-t", f"{dur + 0.1:.3f}", out_s]
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
