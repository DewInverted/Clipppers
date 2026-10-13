"""Fetch video metadata + captions from a link (YouTube, TikTok, Twitch, podcasts, direct files…) via yt-dlp."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

from .analyzer import parse_captions

WORK = os.path.join(tempfile.gettempdir(), "clipppers")
os.makedirs(WORK, exist_ok=True)


def _ytdlp(*args, timeout=180):
    return subprocess.run([sys.executable, "-m", "yt_dlp", *args],
                          capture_output=True, text=True, timeout=timeout)


def is_youtube(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url or ""))


def youtube_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{6,})", url or "")
    return m.group(1) if m else None


def fetch_link(url: str) -> dict:
    """Return {meta, segments}. Raises ValueError with a friendly message on failure."""
    if not re.match(r"https?://", url or ""):
        raise ValueError("That doesn't look like a link — paste a full https:// URL.")
    host = urlparse(url).netloc
    probe = _ytdlp("--dump-single-json", "--no-playlist", "--skip-download", url, timeout=90)
    if probe.returncode != 0:
        tail = (probe.stderr or "unknown error").strip().splitlines()[-1:]
        raise ValueError(f"Couldn't read that link ({host}). {' '.join(tail)[:220]}")
    info = json.loads(probe.stdout)
    meta = {"title": info.get("title"), "uploader": info.get("uploader") or info.get("channel"),
            "duration": info.get("duration"), "thumbnail": info.get("thumbnail"),
            "url": url, "platform": host.replace("www.", ""), "youtube_id": youtube_id(url),
            "view_count": info.get("view_count"), "description": (info.get("description") or "")[:500]}

    # chapters are gold when there's no transcript
    chapters = [{"start": float(c["start_time"]), "end": float(c["end_time"]),
                 "text": c.get("title", "")} for c in (info.get("chapters") or [])]

    with tempfile.TemporaryDirectory(dir=WORK) as td:
        cap = _ytdlp("--skip-download", "--write-subs", "--write-auto-subs",
                     "--sub-langs", "en.*,en", "--sub-format", "vtt",
                     "-o", os.path.join(td, "cap.%(ext)s"), url)
        vtts = [f for f in os.listdir(td) if f.endswith(".vtt")]
        if vtts:
            raw = open(os.path.join(td, vtts[0]), encoding="utf-8", errors="ignore").read()
            segments = parse_captions(raw)
            if segments:
                return {"meta": meta, "segments": segments, "source": "captions"}
    if chapters:
        return {"meta": meta, "segments": chapters, "source": "chapters",
                "warning": "No captions on this video — moments below come from its chapters. "
                           "For hook-level analysis, paste the transcript instead."}
    return {"meta": meta, "segments": [], "source": "none",
            "warning": "This video has no captions we could read. Paste its transcript "
                       "(or upload a .srt/.vtt) and we'll find the moments from that."}


def download_section(url: str, start: float, end: float, vertical: bool, out_dir: str) -> str:
    """Download just [start,end] and cut it with ffmpeg. Returns file path."""
    from .clipper import ffmpeg_bin, cut
    with tempfile.TemporaryDirectory(dir=WORK) as td:
        src = os.path.join(td, "src.%(ext)s")
        r = _ytdlp("-f", "bv*[height<=720]+ba/b[height<=720]/b", "--merge-output-format", "mp4",
                   "-o", src, url, timeout=300)
        files = [os.path.join(td, f) for f in os.listdir(td) if not f.endswith(".part")]
        if r.returncode != 0 or not files:
            raise ValueError("Download failed — the platform may be blocking automated downloads "
                             "for this video. Try uploading the file instead.")
        out = os.path.join(out_dir, f"clip_{int(start)}_{int(end)}.mp4")
        cut(files[0], start, end, out, vertical)
        return out
