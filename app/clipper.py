"""Real clip cutting with ffmpeg (binary bundled via imageio-ffmpeg — no system install)."""
from __future__ import annotations

import os
import subprocess

# export quality -> (width, height) per orientation + x264 crf (lower = better/bigger)
QUALITIES = {
    "1080": dict(vertical=(1080, 1920), horizontal=(1920, 1080), crf=18, label="1080p · best quality"),
    "720":  dict(vertical=(720, 1280),  horizontal=(1280, 720),  crf=21, label="720p · balanced (recommended)"),
    "480":  dict(vertical=(480, 854),   horizontal=(854, 480),   crf=24, label="480p · small file, fast upload"),
}


def ffmpeg_bin() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def cut(src: str, start: float, end: float, out: str, vertical: bool = True,
        quality: str = "720", caption_ass: str | None = None) -> str:
    q = QUALITIES.get(quality, QUALITIES["720"])
    w, h = q["vertical"] if vertical else q["horizontal"]
    dur = max(1.0, end - start)
    vf = []
    if vertical:
        vf.append(f"crop='if(gt(iw/ih,9/16),ih*9/16,iw)':'if(gt(iw/ih,9/16),ih,iw*16/9)',"
                  f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
    else:
        vf.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
    if caption_ass:
        escaped = caption_ass.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        vf.append(f"subtitles='{escaped}'")
    cmd = [ffmpeg_bin(), "-y", "-ss", f"{start:.2f}", "-i", src, "-t", f"{dur:.2f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(q["crf"]),
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
           "-vf", ",".join(vf), out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not os.path.exists(out):
        raise ValueError("ffmpeg failed to cut that clip: " + (r.stderr or "")[-300:])
    return out
