"""Real clip cutting with ffmpeg (binary bundled via imageio-ffmpeg — no system install)."""
from __future__ import annotations

import os
import subprocess


def ffmpeg_bin() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def cut(src: str, start: float, end: float, out: str, vertical: bool = True) -> str:
    dur = max(1.0, end - start)
    vf = []
    if vertical:
        # 9:16 centre crop + scale to 1080x1920 (pads instead if source is already portrait)
        vf.append("crop='if(gt(iw/ih,9/16),ih*9/16,iw)':'if(gt(iw/ih,9/16),ih,iw*16/9)',scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2")
    cmd = [ffmpeg_bin(), "-y", "-ss", f"{start:.2f}", "-i", src, "-t", f"{dur:.2f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]
    if vf:
        cmd += ["-vf", vf[0]]
    cmd.append(out)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not os.path.exists(out):
        raise ValueError("ffmpeg failed to cut that clip: " + (r.stderr or "")[-300:])
    return out
