"""Fetch video metadata + captions from a link (YouTube, TikTok, Twitch, podcasts, direct files…) via yt-dlp.

Uses yt_dlp as an in-process library (not a subprocess) so it works even when
the install path is long (Windows MAX_PATH / WinError 206).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.request
from urllib.parse import urlparse

from .analyzer import parse_captions

WORK = os.path.join(tempfile.gettempdir(), "clipppers")
os.makedirs(WORK, exist_ok=True)

YTDLP_TIMEOUT_FETCH = 90
YTDLP_TIMEOUT_DOWNLOAD = 600


class YtDlpError(RuntimeError):
    """Raised when yt-dlp fails with a friendly message."""


def _import_ytdlp():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        raise YtDlpError(
            "yt-dlp is not installed. Stop the server, move the Clipppers folder "
            "to a shorter path (closer to C:\\ or ~/) if needed, then run:\n"
            "    python start.py\n"
            "(or: pip install -r requirements.txt)"
        ) from None


def _ffmpeg_location() -> str:
    """Return a path to ffmpeg for yt-dlp to use for muxing. Uses the
    bundled imageio-ffmpeg binary, or 'ffmpeg' as a fallback. On Windows
    converts to 8.3 short path to avoid MAX_PATH issues."""
    try:
        from .clipper import ffmpeg_bin
        p = ffmpeg_bin()
        import os, subprocess
        if os.name == "nt" and not p.lower().endswith(".exe") is False and len(p) > 4:
            pass  # ffmpeg_bin already handles the 8.3 short-path conversion
        # Quick verify
        if os.path.isabs(p) and os.path.exists(p):
            return p
    except Exception:
        pass
    return "ffmpeg"


def _run_ytdlp(params: dict, url: str, *, download: bool = True):
    """Run yt-dlp in-process; return the info_dict (or None)."""
    yt_dlp = _import_ytdlp()
    import io
    err_buf = io.StringIO()

    class _Logger:
        def debug(self, msg): pass
        def warning(self, msg): err_buf.write(msg + "\n")
        def error(self, msg): err_buf.write(msg + "\n")

    base = {
        "quiet": True, "no_warnings": False, "noprogress": True,
        "socket_timeout": 30, "retries": 2, "fragment_retries": 2,
        "ignoreerrors": False, "no_color": True, "verbose": False,
        # Tell yt-dlp where ffmpeg is so '--merge-output-format mp4' works
        # even when ffmpeg isn't on PATH (e.g. fresh venv / Windows).
        "ffmpeg_location": _ffmpeg_location(),
        # Browser UA so YouTube search/metadata doesn't 403 or TLS-fail
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "extractor_args": {"youtube": {"player_client": ["tv_simply", "android", "web"],
                                        "player_skip": ["webpage", "js", "configs"]}},
        "youtube_include_dash_manifest": False,
        "youtube_include_hls_manifest": False,
    }
    params = {**base, **params, "logger": _Logger()}

    try:
        with yt_dlp.YoutubeDL(params) as ydl:
            return ydl.extract_info(url, download=download)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e).split(":", 1)[1].strip() if ":" in str(e) else str(e)
        msg = re.sub(r"^\[[^\]]+\]\s*", "", msg, count=1)
        raise YtDlpError(msg[:400]) from e
    except Exception as e:
        tail = err_buf.getvalue().strip().splitlines()[-3:]
        extra = " ".join(tail)[:260] if tail else str(e)
        raise YtDlpError(f"yt-dlp failed: {extra}") from e


def is_youtube(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url or ""))


def youtube_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{6,})", url or "")
    return m.group(1) if m else None


def youtube_timestamp_url(url: str, start: float, end: float | None = None) -> str:
    yid = youtube_id(url)
    if not yid:
        return url
    return f"https://www.youtube.com/watch?v={yid}&t={int(start)}s"


def youtube_thumbnail_url(url: str) -> str | None:
    yid = youtube_id(url)
    if not yid:
        return None
    return f"https://i.ytimg.com/vi/{yid}/hqdefault.jpg"


def _fetch_subs_from_info(info: dict) -> str:
    """As a fallback when yt-dlp doesn't write a subtitle file to disk, pick
    the best English caption URL from the info dict and download it directly.
    Returns raw caption text (vtt/ttml/json3), or '' if nothing is available.
    """
    def _pick_lang(subs_dict):
        if not isinstance(subs_dict, dict):
            return None
        # Preference order: exact 'en', then 'en-US'/'en-GB', then anything starting with 'en'
        for key in ("en", "en-US", "en-GB"):
            if key in subs_dict and subs_dict[key]:
                return subs_dict[key]
        for k, v in subs_dict.items():
            if k.lower().startswith("en") and v:
                return v
        return None

    sources = []
    for group in (info.get("subtitles"), info.get("automatic_captions")):
        picked = _pick_lang(group or {})
        if picked:
            sources.extend(picked)
    if not sources:
        return ""

    def _ext_priority(fmt: dict) -> int:
        # Lower = better. Prefer text-based formats easiest for us to parse.
        ext = (fmt.get("ext") or "").lower()
        return {
            "vtt": 0, "srt": 1, "ttml": 2, "srv1": 3, "srv2": 4,
            "srv3": 5, "xml": 6, "json3": 7,
        }.get(ext, 9)
    sources.sort(key=_ext_priority)

    for fmt in sources:
        url = fmt.get("url")
        if not url:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read().decode("utf-8", errors="ignore")
                if data and len(data) > 20:
                    return data
        except Exception:
            continue
    return ""


def fetch_link(url: str) -> dict:
    if not re.match(r"https?://", url or ""):
        raise ValueError("That doesn't look like a link — paste a full https:// URL.")
    host = urlparse(url).netloc

    info = _run_ytdlp({
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": YTDLP_TIMEOUT_FETCH,
    }, url, download=False)
    if not info:
        raise YtDlpError(f"Couldn't read that link ({host}) — yt-dlp returned no metadata.")

    meta = {"title": info.get("title"), "uploader": info.get("uploader") or info.get("channel"),
            "duration": info.get("duration"), "thumbnail": info.get("thumbnail"),
            "url": url, "platform": host.replace("www.", ""), "youtube_id": youtube_id(url),
            "view_count": info.get("view_count"),
            "description": (info.get("description") or "")[:500]}

    chapters = [{"start": float(c["start_time"]), "end": float(c["end_time"]),
                 "text": c.get("title", "")} for c in (info.get("chapters") or [])]

    segments: list[dict] = []
    with tempfile.TemporaryDirectory(dir=WORK) as td:
        out_tmpl = os.path.join(td, "cap.%(ext)s")
        cap_info = None
        # Try several subtitle-language combos in priority order: first try
        # English (manual + auto-caps), then * (any language). yt-dlp returns
        # what's actually available, so asking for "en.*,en,orig" doesn't
        # force English — it just says "prefer these".
        for langs in (["en.*","en","en-US","en-GB","en-orig","orig"], ["all","en.*","en"], ["all"]):
            try:
                cap_info = _run_ytdlp({
                    "skip_download": True,
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": langs,
                    # Ask for json3 first — most detailed timing; fall back
                    # through vtt/srv1/ttml/best if not available.
                    "subtitlesformat": "json3/vtt/srv1/srv2/srv3/ttml/srt/best",
                    "outtmpl": out_tmpl,
                    "noplaylist": True,
                    "socket_timeout": YTDLP_TIMEOUT_FETCH,
                    "quiet": True,
                    "convertsubtitles": "vtt",
                }, url, download=True)
            except YtDlpError:
                cap_info = None
            files = [f for f in os.listdir(td)
                     if os.path.isfile(os.path.join(td, f)) and not f.startswith(".")]
            # Did we actually get a subtitle file written?
            cap_files = [f for f in files if any(f.lower().endswith(ext) for ext in
                         (".vtt",".srt",".ttml",".srv1",".srv2",".srv3",".json3",".xml",".txt"))]
            if cap_files:
                break

        files = [f for f in os.listdir(td)
                 if os.path.isfile(os.path.join(td, f)) and not f.startswith(".")]
        preference = (".json3", ".vtt", ".srv3", ".srv2", ".srv1", ".ttml", ".srt", ".xml", ".txt")
        chosen = None
        for ext in preference:
            for f in files:
                if f.lower().endswith(ext):
                    chosen = f; break
            if chosen: break
        if not chosen and files:
            # Pick largest non-temp file as last resort
            cand = [f for f in files if not f.lower().endswith((".part",".temp",".tmp",".ytdl"))]
            if cand:
                chosen = sorted(cand, key=lambda p: os.path.getsize(os.path.join(td, p)), reverse=True)[0]

        raw = ""
        if chosen:
            try:
                with open(os.path.join(td, chosen), encoding="utf-8", errors="ignore") as fh:
                    raw = fh.read()
            except Exception:
                raw = ""
        if not raw and cap_info is not None:
            raw = _fetch_subs_from_info(cap_info)
        if raw:
            segments = parse_captions(raw)

    if segments:
        return {"meta": meta, "segments": segments, "source": "captions"}
    if chapters:
        return {"meta": meta, "segments": chapters, "source": "chapters",
                "warning": "No captions on this video. Moments below are pulled from chapters. "
                           "For word-by-word captions, you can paste the transcript (optional) — "
                           "clips will still render with chapter-based text."}
    return {"meta": meta, "segments": [], "source": "none",
            "warning": "Clipppers couldn't pull captions for this video (may be disabled by the uploader, "
                       "age-restricted, or non-English). You can still cut clips from the video directly "
                       "(use the manual cutter below), or paste a transcript for caption-burned clips."}


def download_section(url: str, start: float, end: float, vertical: bool, out_dir: str,
                     quality: str = "720", caption_ass: str | None = None,
                     crop_mode: str = "blur", out_tag: str | None = None) -> str:
    from .clipper import cut
    import time as _time
    with tempfile.TemporaryDirectory(dir=WORK) as td:
        src_tmpl = os.path.join(td, "src.%(ext)s")

        # Try a few format strings in order: strict-ish to anything-goes.
        # Some videos only expose muxed formats, some are Shorts/age-gated,
        # some don't have <=1080p separate video+audio streams.
        fmt_attempts = [
            "(bv*[height<=?1080][ext=mp4]+ba[ext=m4a])/b[height<=?1080][ext=mp4]/(bv*[height<=?1080]+ba/b[height<=?1080])",
            "(bv*[height<=?720][ext=mp4]+ba[ext=m4a])/b[height<=?720][ext=mp4]/(bv*[height<=?720]+ba/b[height<=?720])",
            "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
            "best/bestvideo+bestaudio/worst",
        ]
        last_err = None
        info = None
        for fmt in fmt_attempts:
            # Clean partial files between attempts
            for leftover in os.listdir(td):
                p = os.path.join(td, leftover)
                if os.path.isfile(p):
                    try: os.remove(p)
                    except OSError: pass
            try:
                info = _run_ytdlp({
                    "format": fmt,
                    "merge_output_format": "mp4",
                    "outtmpl": src_tmpl,
                    "noplaylist": True,
                    "socket_timeout": YTDLP_TIMEOUT_DOWNLOAD,
                    "overwrites": True,
                    "continuedl": False,
                }, url, download=True)
                # Check if we actually got a usable file
                files = sorted(
                    [os.path.join(td, f) for f in os.listdir(td)
                     if not f.endswith((".part", ".ytdl", ".temp", ".tmp"))
                     and os.path.isfile(os.path.join(td, f))],
                    key=lambda p: os.path.getsize(p), reverse=True)
                if files and os.path.getsize(files[0]) > 50_000:
                    break
            except YtDlpError as e:
                last_err = e
                continue
        files = sorted(
            [os.path.join(td, f) for f in os.listdir(td)
             if not f.endswith((".part", ".ytdl", ".temp", ".tmp"))
             and os.path.isfile(os.path.join(td, f))],
            key=lambda p: os.path.getsize(p), reverse=True)
        if not files:
            msg = f"Couldn't download a video stream for this link."
            if last_err:
                msg += f" ({str(last_err)[:200]})"
            msg += " Try uploading the video file directly, or try a different quality."
            raise YtDlpError(msg)
        src_file = files[0]
        tag = out_tag or f"yt_{int(start)}_{int(end)}_{'v' if vertical else 'h'}_{quality}"
        out = os.path.join(out_dir, f"{tag}.mp4")
        cut(src_file, start, end, out, vertical, quality, caption_ass=caption_ass, crop_mode=crop_mode)
        return out
