"""Clipppers — paste a link, get the key moments, the hook breakdown, and ready-to-post clips."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
import traceback

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analyzer import DEMO, TOPICS, analyze_transcript, find_topic_clips, parse_captions, score_window, _hashtags, _title
from .captions import STYLE_CHOICES, STYLES, build_ass
from .clipper import FFMPEG_TIMEOUT, PLATFORM_CAPTION_MARGIN, PLATFORM_LUFS, QUALITIES, _res, cut, ffmpeg_bin, make_thumbnail, _short_path
from .fillers import remove_fillers, estimate_word_segments
from .projects import ProjectStore
from .sources import WORK, download_section, fetch_link, is_youtube, youtube_id, youtube_thumbnail_url, youtube_timestamp_url, _run_ytdlp, YtDlpError, _import_ytdlp


def _esc_path(p: str) -> str:
    return _short_path(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIPS = os.path.join(WORK, "clips")
THUMBS = os.path.join(WORK, "thumbs")
UPLOADS = os.path.join(WORK, "uploads")
os.makedirs(CLIPS, exist_ok=True)
os.makedirs(THUMBS, exist_ok=True)
os.makedirs(UPLOADS, exist_ok=True)
UPLOAD_MAP: dict[str, str] = {}   # upload_id -> local file path
SEG_CACHE: dict[str, list] = {}   # url/upload_id -> parsed segments (for accurate caption timing)

app = FastAPI(title="Clipppers")


@app.on_event("startup")
def _startup_checks():
    """Warn clearly if required Python deps are missing (server still starts)."""
    missing = []
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        missing.append("yt-dlp — needed to fetch videos from links")
    try:
        import imageio_ffmpeg  # noqa: F401
    except ImportError:
        missing.append("imageio-ffmpeg — provides ffmpeg for cutting clips")
    if missing:
        print("\n[Clipppers] ⚠ Missing dependencies:")
        for m in missing:
            print(f"    - {m}")
        print("  Stop the server and run:  pip install -r requirements.txt")
        print("  or simply re-run:  python start.py\n")


# --------------------------------------------------------- global error JSON
@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    """Guarantee every API error is JSON with an 'error' field — never an HTML traceback."""
    # Let HTTPException-style responses flow through if they carry a status code
    status = 500
    msg = str(exc) if str(exc) else exc.__class__.__name__
    if hasattr(exc, "status_code"):
        status = getattr(exc, "status_code", 500)
    if isinstance(exc, (ValueError, RuntimeError)):
        status = 400 if isinstance(exc, ValueError) else 500
    # Don't leak full tracebacks to the UI, but do include the real message
    tb = traceback.format_exc(limit=2) if os.environ.get("CLIPPPERS_DEBUG") else ""
    return JSONResponse(
        {"error": msg[:400], **({"trace": tb} if tb else {})},
        status_code=status,
    )


class AnalyzeIn(BaseModel):
    url: str = ""
    transcript: str = ""
    target_len: float = 38
    auto_export: int = 0          # 0 = don't auto-render; N = auto-render top N moments fully edited
    quality: str = "720"
    caption_style: str = "hormozi"
    vertical: bool = True
    remove_fillers: bool = True
    crop_mode: str = "blur"


class ClipIn(BaseModel):
    url: str = ""
    upload_id: str = ""
    start: float
    end: float
    vertical: bool = True
    quality: str = "720"          # 1080 | 720 | 480
    caption_style: str = "none"   # none | hormozi | mrbeast | karaoke | neon | minimal | cinematic
    caption_text: str = ""        # transcript text covering [start, end]
    remove_fillers: bool = False  # snip out um/uh/you know/…
    crop_mode: str = "blur"       # blur (default) | crop — vertical framing style
    font_size: int = 0            # 0 = use style default; else override font size (px on 1280 canvas)
    margin_v: int = 0             # 0 = use style default; else override bottom margin (px)
    platform: str = "tiktok"      # tiktok | shorts | reels | story | ig_square | ig_portrait | youtube | horizontal


VERSION = "1.5.4"


@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION}


@app.get("/api/options")
def options():
    return {"version": VERSION,
            "qualities": {k: v["label"] for k, v in QUALITIES.items()},
            "caption_styles": {"none": "🚫 No burned-in captions", **{k: v["label"] for k, v in STYLES.items()}}}


STORE = ProjectStore(os.path.join(WORK, "projects.json"))


# ------------------------------------------------------------- saved edits
@app.get("/api/projects")
def list_projects():
    return {"projects": STORE.list()}


@app.post("/api/projects")
def save_project(project: dict):
    if not isinstance(project, dict) or not project.get("edits"):
        return JSONResponse({"error": "Nothing to save yet — analyse a video first."}, 400)
    return STORE.upsert(project)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    return {"deleted": STORE.delete(pid)}



@app.post("/api/analyze")
def analyze(body: AnalyzeIn):
    if body.transcript.strip():                     # pasted transcript wins
        from .sources import youtube_id
        yid = youtube_id(body.url) if body.url else None
        segments = parse_captions(body.transcript)
        data = {"meta": {"title": "Pasted transcript", "url": body.url,
                         "youtube_id": yid,
                         "thumbnail": youtube_thumbnail_url(body.url) if yid else None},
                "segments": segments}
        cache_key = ("url:" + body.url) if body.url else ("transcript:" + str(uuid.uuid4())[:8])
        SEG_CACHE[cache_key] = segments
    elif body.url.strip():
        data = fetch_link(body.url.strip())
        warning = data.get("warning")
        segments = data.get("segments") or []
        SEG_CACHE["url:" + body.url.strip()] = segments
        # augment meta with youtube helpers
        m = data.get("meta", {})
        yid = m.get("youtube_id") or youtube_id(body.url)
        if yid and not m.get("thumbnail"):
            m["thumbnail"] = youtube_thumbnail_url(body.url)
        data["meta"] = m
        result = analyze_transcript(data["segments"], data["meta"], body.target_len)
        if warning and not result.get("warning"):
            result["warning"] = warning
        if data.get("source"):
            result["source"] = data["source"]
        return result
    else:
        return JSONResponse({"error": "Paste a video link or a transcript first."}, 400)
    result = analyze_transcript(data["segments"], data["meta"], body.target_len)
    if data.get("source"):
        result["source"] = data["source"]
    return result


@app.get("/api/demo")
def demo():
    result = analyze_transcript(DEMO, {"title": "Demo podcast — 'Grow on social media'",
                                       "uploader": "Clipppers Demo", "platform": "demo"})
    result["source"] = "demo"
    return result


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), transcript: str = Form("")):
    """Upload a video file (kept locally) and/or a caption file; returns moments + upload_id."""
    name = file.filename or "upload"
    uid = uuid.uuid4().hex[:10]
    if name.lower().endswith((".srt", ".vtt", ".txt")):
        raw = (await file.read()).decode("utf-8", "ignore")
        segs = parse_captions(raw)
        SEG_CACHE["upload:" + uid] = segs
        result = analyze_transcript(segs, {"title": name})
        result["upload_id"] = uid
        return result
    path = os.path.join(UPLOADS, f"{uid}_{name}")
    with open(path, "wb") as f:
        f.write(await file.read())
    UPLOAD_MAP[uid] = path
    segments = parse_captions(transcript) if transcript.strip() else []
    SEG_CACHE["upload:" + uid] = segments
    result = analyze_transcript(segments, {"title": name, "url": ""})
    result["upload_id"] = uid
    if not segments:
        result["warning"] = ("Video saved — now paste its transcript (or drop a .srt) so we can find "
                             "moments. You can still cut clips from it by typing timestamps below.")
    return result


# ------------------------------------------------------------- niche discover
NICHE_PRESETS = {
    "finance":   "personal finance tips viral",
    "fitness":   "gym fitness tips viral",
    "business":  "entrepreneur business advice viral",
    "tech":      "tech AI productivity tips viral",
    "motivation":"motivational speech life advice viral",
    "gaming":    "gaming highlights funny moments",
    "cooking":   "cooking recipe hack viral",
    "crypto":    "crypto trading advice viral",
    "self-improvement": "self improvement productivity habits",
    "relationship":"relationship dating advice viral",
    "trending":  "shorts trending viral this week",
}


@app.get("/api/discover")
def discover(q: str = "", niche: str = "", count: int = 8):
    """Find popular videos across niches using yt-dlp's YouTube search.

    Pass ?niche=finance|fitness|trending (any NICHE_PRESETS key) or a free-text
    ?q=... query. Returns {videos: [{id,title,channel,url,thumbnail,duration,views}]}.
    These are "already popular" candidates you can one-click load into Clipppers
    to find hooks and cut clips from.
    """
    query = q.strip()
    if not query and niche:
        query = NICHE_PRESETS.get(niche, NICHE_PRESETS["trending"])
    if not query:
        query = NICHE_PRESETS["trending"]
    n = max(3, min(int(count) + 3, 12))
    # Note: yt-dlp only supports ytsearch[N]: / ytsearchdate[N]: prefixes (no
    # "ytsearchshorts" / "ytsearchvideos" — those aren't real and fail with
    # "Unsupported url scheme: ytsearchshortsN"). We run regular ytsearch and
    # filter Shorts vs long-form on the results by looking for /shorts/ URLs
    # and aspect ratio metadata.
    raw_q = re.sub(r"^ytsearch\w*\d*:", "", query).strip()
    # Stack multiple viral / high-intent phrasings so we don't just get boring
    # top-level tutorial/explainer videos. Mixes shorts + drama + story + how-to.
    strategies = [
        f"ytsearch{n}:{raw_q} #shorts",
        f"ytsearch{n}:{raw_q} exposed",
        f"ytsearch{n}:{raw_q} crazy story",
        f"ytsearch{n}:{raw_q} you won't believe",
        f"ytsearch{n}:{raw_q} the truth about",
        f"ytsearch{n}:{raw_q} tips that actually work",
        f"ytsearch{n}:{raw_q}",
    ]
    last_err = None
    info = None
    used_entries: list = []
    for sq in strategies:
        try:
            cand = _run_ytdlp({
                "noplaylist": True, "skip_download": True, "quiet": True,
                "extract_flat": False,
                "format": "best",
                "extractor_args": {"youtube": {
                    "player_client": ["tv_simply", "android", "web"],
                    "player_skip": ["webpage", "js", "configs"],
                }},
                "youtube_include_dash_manifest": False,
                "youtube_include_hls_manifest": False,
            }, sq, download=False)
            es = (cand.get("entries") or []) if isinstance(cand, dict) else []
            # Filter to real videos only: must have an id, webpage_url, duration
            # >5s, and NOT be a channel/playlist/mix/song entry. yt-dlp marks
            # non-videos with ie_key like 'YoutubeChannel' or _type != 'url'.
            for v in es:
                if not v:
                    continue
                if v.get("_type") and v["_type"] != "url":
                    continue
                if v.get("ie_key") and v["ie_key"] not in ("Youtube", None):
                    continue
                vid = v.get("id") or v.get("display_id")
                dur = v.get("duration")
                if not vid or not dur or dur < 5:
                    continue
                title = (v.get("title") or "").lower()
                # Skip music/song/album/playlist entries
                if any(skip in title for skip in (" provided to youtube by", "official audio",
                                                 "official music video", "lyrics",
                                                 "topic -", " - topic", "full album")):
                    continue
                if v.get("channel_id") and v.get("channel_id","").startswith("UC") and any(
                    m in title for m in (" song", " soundtrack", " official video", " audio)", "mix)")):
                    continue
                # Dedupe by video id
                if any(u.get("id") == vid for u in used_entries):
                    continue
                used_entries.append(v)
            if len(used_entries) >= int(count):
                info = {"entries": used_entries}
                break
        except YtDlpError as e:
            last_err = e
            continue
    if used_entries and not info:
        info = {"entries": used_entries}
    if not info:
        msg = str(last_err) if last_err else "No results from YouTube search."
        if "TLS" in msg or "SSL" in msg or "EOF" in msg or "403" in msg:
            msg = ("YouTube search blocked on this network. Try: "
                   "1) pip install -U yt-dlp then restart, "
                   "2) disable VPN/firewall/antivirus web shield, "
                   "3) wait a minute (possible rate limit). "
                   "Details: " + msg[:160])
        return JSONResponse({"error": msg}, 502)
    entries = []
    source_entries = (used_entries or ((info.get("entries") or []) if isinstance(info, dict) else []))
    for v in source_entries:
        if not v:
            continue
        vid = v.get("id") or v.get("display_id")
        url = v.get("webpage_url") or v.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
        entries.append({
            "id": vid,
            "title": v.get("title"),
            "channel": v.get("uploader") or v.get("channel"),
            "url": url,
            "thumbnail": v.get("thumbnail") or (f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else ""),
            "duration": v.get("duration"),
            "views": v.get("view_count"),
            "platform": "youtube.com",
        })
        if len(entries) >= max(3, min(int(count), 12)):
            break
    return {"query": q or niche or "trending", "niche": niche or "custom", "videos": entries,
            "presets": {k: v for k, v in NICHE_PRESETS.items() if k != "trending"}}


class ThemeIn(BaseModel):
    url: str = ""
    upload_id: str = ""
    topic: str = "custom"       # key in TOPICS or 'custom'
    query: str = ""             # free-text keywords
    target_len: float = 25.0


@app.get("/api/themes")
def list_themes():
    return {"themes": [{"id": k, "label": k} for k in TOPICS.keys()] + [{"id":"custom","label":"✨ Type your own…"}]}


@app.post("/api/find-theme")
def find_theme(body: ThemeIn):
    """Scan the loaded video's transcript for moments matching a theme/topic.
    Returns a list of themed clip candidates (ranked) ready to one-click add
    to your moments list — each with a theme-matched edit recipe."""
    cache_key = None
    if body.upload_id:
        cache_key = "upload:" + body.upload_id
    elif body.url:
        cache_key = "url:" + body.url
    if not cache_key or cache_key not in SEG_CACHE or not SEG_CACHE[cache_key]:
        return JSONResponse({"error": "Analyse a video first so we have a transcript to scan."}, 400)
    segs = SEG_CACHE[cache_key]
    raw_cands = find_topic_clips(segs, body.topic, body.query, body.target_len or 25.0)
    out = []
    for rank, c in enumerate(raw_cands, 1):
        text = c["text"]
        duration = round(c["end"] - c["start"], 1)
        wpm = round(len(re.findall(r"[A-Za-z']+", text)) / max(0.5, duration) * 60)
        topic = c["_topic"]
        kw = (body.query or topic["label"]).split()[0] if (body.query or topic.get("label")) else ""
        recipe = {
            "bgm": topic["bgm"],
            "sfx": [{"t":0.0,"type":"pop","note":"Hard cut on the keyword moment"}] + [
                {"t":round(0.3+idx*0.25,2),"type":s,"note":s+" SFX on theme beat"}
                for idx, s in enumerate(topic.get("sfx",[])[:2])
            ],
            "steps": [
                "0.00s — Hard cut in right as the themed line starts; caption pops 1.2→1.0",
                f"0.20s — 💥 Bold keyword flash ('{kw or topic['label']}') in accent color",
                "0.60s — Slow Ken Burns push-in starts; captions 3 words at a time",
                f"{round(max(1,duration-0.8),1)}s — 📍 End card CTA arrow fades in",
            ],
            "effects": [
                "1.15→1.0 zoom punch on cut",
                f"Keyword '{kw or topic['label']}' flashes accent color for 0.3s",
                "Spotlight tightens on face at climax of the line",
            ],
            "text_overlays": [
                f"Big theme tag '{topic['label']}' 0.2–0.8s at top",
                "3-word karaoke captions (bold, 4px outline)",
            ],
            "hook_grade": "A",
            "hook_line": text[:100],
            "hook_rewrites": [
                f"{(body.query or topic['label']).upper()} — here's the truth 👇",
                f"Wait till you hear this about {(body.query or 'this')[:40]}…",
            ],
        }
        score = min(99, c["topic_score"] + (10 if 130 <= wpm <= 185 else 0))
        hook = {"score": min(99, c["topic_score"]+20), "grade": "A",
                "text": text[:120], "strengths": c["topic_hits"][:3],
                "rewrites": recipe["hook_rewrites"]}
        out.append({
            "rank": rank,
            "start": c["start"], "end": c["end"],
            "duration": duration,
            "title": _title(text),
            "score": score,
            "label": c["label"],
            "wpm": wpm,
            "hook": hook,
            "transcript": text,
            "caption": f"{_title(text)} 🔥\n\n" + " ".join(_hashtags(text)),
            "hashtags": _hashtags(text),
            "why": [f"Matched theme: {hit}" for hit in c["topic_hits"][:3]],
            "recipe": recipe,
        })
    return {"topic": body.topic, "query": body.query, "moments": out}


def _compute_word_timings(body: ClipIn) -> list[tuple[float, float, str]] | None:
    """Given a clip request, return list of (clip_rel_start, clip_rel_end, word)
    for each word in body.caption_text using the stored source segments if
    available. Words are placed within their source segment proportionally to
    segment duration (even within-segment split) — but *between* segments the
    real timings are preserved, so pauses/music gaps don't compress and captions
    stay in sync with audio. Returns None if no timing info is available.
    """
    import re as _re
    cache_key = None
    if body.upload_id:
        cache_key = "upload:" + body.upload_id
    elif body.url:
        cache_key = "url:" + body.url
    if not cache_key or cache_key not in SEG_CACHE:
        return None
    segs = SEG_CACHE[cache_key]
    if not segs:
        return None

    # Find segments overlapping [start, end]
    words_in_range = []   # list of (s_rel, e_rel, word)
    target_words = [w for w in _re.findall(r"[A-Za-z']+", body.caption_text or "")]
    twi = 0
    for seg in segs:
        ss, se = float(seg["start"]), float(seg["end"])
        if se <= body.start or ss >= body.end:
            continue
        # Clip segment to clip range
        cs = max(ss, body.start) - body.start
        ce = min(se, body.end) - body.start
        sw = [w for w in _re.findall(r"[A-Za-z']+", seg.get("text", ""))]
        if not sw:
            continue
        per_w = (ce - cs) / len(sw)
        t = cs
        for w in sw:
            if twi >= len(target_words):
                break
            # Match: accept either same word, or just use ordering (captions
            # may have been edited; we still assign timing positionally).
            words_in_range.append((t, t + per_w, w))
            t += per_w
            twi += 1
        if twi >= len(target_words):
            break
    if not words_in_range:
        return None
    # If the caption_text was edited (fewer/more words), stretch/compress the
    # word timings to cover [0..clip_dur] positionally so the output still
    # fills the clip.
    if len(words_in_range) != len(target_words):
        if not words_in_range:
            return None
        # Map N source words onto M target words by proportional position.
        n = len(words_in_range)
        m = len(target_words)
        out = []
        for j in range(m):
            src_idx = min(n - 1, int(j * n / m))
            s_rel = words_in_range[src_idx][0]
            e_rel = words_in_range[src_idx][1]
            out.append((s_rel, e_rel, target_words[j]))
        words_in_range = out
    return words_in_range


@app.post("/api/clip")
def make_clip(body: ClipIn):
    """Export a clip MP4 + JPEG preview thumbnail. Always returns JSON on success or failure."""
    if body.end <= body.start:
        return JSONResponse({"error": "End time must be after start time."}, 400)
    if body.end - body.start > 180:
        return JSONResponse({"error": "Keep clips under 3 minutes."}, 400)
    if body.quality not in QUALITIES:
        return JSONResponse({"error": f"Unknown quality '{body.quality}'."}, 400)
    if body.caption_style not in STYLE_CHOICES:
        return JSONResponse({"error": f"Unknown caption style '{body.caption_style}'."}, 400)
    if body.font_size and not (18 <= body.font_size <= 120):
        return JSONResponse({"error": "Font size must be between 18 and 120."}, 400)
    if body.margin_v and not (0 <= body.margin_v <= 600):
        return JSONResponse({"error": "Caption position must be between 0 and 600."}, 400)
    # Main work — RuntimeError/ValueError/ffmpeg failures all flow through the global handler
    # but we wrap here too so we can give specific, friendly messages.
    try:
        # Cache-busting suffix so we never re-serve a stale MP4 from a
        # previous export with different settings (different crop mode /
        # fillers on/off / caption style changed).
        nonce = uuid.uuid4().hex[:6]
        tag = f"{int(body.start)}_{int(body.end)}_{'v' if body.vertical else 'h'}_{body.quality}_{body.caption_style}_{nonce}"
        crop_mode = body.crop_mode if body.crop_mode in ("blur", "crop", "zoom", "black") else "blur"
        # Compute accurate per-word timings (using real source segment times,
        # clip-relative) so captions line up with speech.
        word_timings = _compute_word_timings(body)
        clip_duration = body.end - body.start
        raw_path = os.path.join(CLIPS, f"raw_{tag}.mp4")
        # Step 1: cut + frame (vertical/horizontal) but NO captions yet — we
        # need a clean base video in case filler removal is on (otherwise
        # splicing video after burning captions desyncs them from audio).
        if body.upload_id and body.upload_id in UPLOAD_MAP:
            cut(UPLOAD_MAP[body.upload_id], body.start, body.end, raw_path, body.vertical,
                body.quality, caption_ass=None, crop_mode=crop_mode, platform=body.platform)
            source_kind = "upload"
        elif body.url:
            raw_path = download_section(body.url, body.start, body.end, body.vertical, CLIPS,
                                        body.quality, caption_ass=None, crop_mode=crop_mode,
                                        out_tag=f"raw_{tag}", platform=body.platform)
            source_kind = "url"
        else:
            return JSONResponse({"error": "No video source for that clip."}, 400)

        # Step 2: filler removal (audio-silence based) — operates on clean video
        fillers_removed = 0
        if body.remove_fillers:
            try:
                from .fillers import estimate_word_segments, remove_fillers, _build_keep_segments, _find_filler_word_times  # noqa
                from .clipper import detect_silences
                # Use accurate word timings if available, else estimate
                word_segs = word_timings if word_timings else estimate_word_segments(
                    body.caption_text, clip_duration)
                # Run silence detection on the raw clip
                silences = detect_silences(raw_path, noise_db=-28, min_dur=0.20)
                # Compute cut spans (mirrors remove_fillers logic so we can re-map word timings)
                cuts = _find_filler_word_times(word_segs, silences)
                long_sil = [(s,e) for s,e in silences if (e-s) > 0.9]
                keep = _build_keep_segments(clip_duration, cuts, long_sil)
                out_fillers = os.path.join(CLIPS, f"fillers_{tag}.mp4")
                post_path, new_dur = remove_fillers(raw_path, out_fillers, word_segs, clip_duration,
                                                    body.vertical, body.quality)
                if post_path != raw_path:
                    fillers_removed = round(clip_duration - new_dur, 2)
                    clip_duration = new_dur
                    # Re-map word_timings to post-cut timeline: for each word,
                    # find which keep-segment its midpoint lands in and offset
                    # by the cumulative duration of kept segments before it.
                    if word_timings and keep:
                        cum = []
                        total_before = 0.0
                        for (ks,ke) in keep:
                            cum.append((ks, ke, total_before))
                            total_before += (ke-ks)
                        mapped = []
                        for ws, we, w in word_timings:
                            mid = (ws+we)/2
                            new_s = None
                            for ks, ke, tb in cum:
                                if ks - 0.001 <= mid < ke:
                                    # word is inside this kept segment
                                    new_s = tb + max(0, ws - ks)
                                    new_e = tb + min(ke, we) - ks
                                    if new_e <= new_s:
                                        new_e = new_s + max(0.08, (we-ws))
                                    break
                            if new_s is None:
                                # word got cut (filler) — skip
                                continue
                            mapped.append((new_s, new_e, w))
                        word_timings = mapped
                    raw_path = post_path
                else:
                    # remove_fillers returned the input (nothing cut)
                    pass
            except Exception as ferr:
                import traceback; traceback.print_exc()
                print(f"[clipppers] filler removal skipped: {ferr}")

        # Step 3: burn captions onto the (possibly filler-free) video.
        # We always save the filler-free / cut-only footage as a separate
        # "clean" MP4 so you have both: the edited raw video AND the
        # captioned/bg/sfx version.
        clean_path = os.path.join(CLIPS, f"clean_{tag}.mp4")
        import shutil
        shutil.copyfile(raw_path, clean_path)

        out = os.path.join(CLIPS, f"clip_{tag}.mp4")
        w, h = _res(body.platform, body.quality)
        q_crf = {"1080":18,"720":21,"480":24}.get(body.quality, 21)
        # Platform-safe caption margin override (clipped to canvas)
        safe_margin = PLATFORM_CAPTION_MARGIN.get(body.platform, 260)
        # Scale margin_v for non-1280 canvas heights (default margin_v is defined at 1280h)
        scaled_margin = int(safe_margin * h / 1280)
        eff_margin_v = body.margin_v or scaled_margin
        if body.caption_style != "none":
            ass_path = os.path.join(CLIPS, f"cap_{tag}.ass")
            caption_words = " ".join(t[2] for t in word_timings) if word_timings else body.caption_text
            build_ass(caption_words, clip_duration, body.caption_style, ass_path, w, h,
                      word_timings=word_timings,
                      font_size=body.font_size or None,
                      margin_v=eff_margin_v)
            caption_burn_cmd = [
                ffmpeg_bin(), "-y", "-i", raw_path,
                "-vf", f"subtitles='{_esc_path(ass_path)}'",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", str(q_crf),
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                "-af", f"loudnorm=I={PLATFORM_LUFS.get(body.platform,-14)}:TP=-1.5:LRA=11",
                out]
            r = subprocess.run(caption_burn_cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
            if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 1024:
                err = (r.stderr or "").strip().splitlines()[-1:]
                raise RuntimeError(f"Caption burn failed: {err}")
        else:
            shutil.copyfile(raw_path, out)

        # ----- Generate preview thumbnail (from captioned version) -----
        thumb_name = f"thumb_{tag}.jpg"
        thumb_path = os.path.join(THUMBS, thumb_name)
        try:
            make_thumbnail(out, thumb_path, offset=min(1.0, (body.end - body.start) / 2))
            thumb_url = f"/api/thumbs/{thumb_name}"
        except Exception as thumb_err:
            thumb_url = None
            print(f"[clipppers] thumbnail failed: {thumb_err}")

        yt_url = body.url or ""
        resp = {
            "download": f"/api/clips/{os.path.basename(out)}",
            "file": os.path.basename(out),
            "clean_download": f"/api/clips/{os.path.basename(clean_path)}",
            "clean_file": os.path.basename(clean_path),
            "thumbnail": thumb_url,
            "quality": body.quality,
            "caption_style": body.caption_style,
            "platform": body.platform,
            "size_kb": round(os.path.getsize(out) / 1024),
            "clean_size_kb": round(os.path.getsize(clean_path) / 1024),
            "duration": round(clip_duration, 1),
            "fillers_removed": fillers_removed,
            "source_kind": source_kind,
            "youtube_url": youtube_timestamp_url(yt_url, body.start, body.end) if is_youtube(yt_url) else "",
        }
        return resp
    except (ValueError, RuntimeError) as e:
        # These carry friendly messages already; re-raise as something the global handler JSONifies
        return JSONResponse({"error": str(e)[:400]}, 400)
    except Exception as e:
        # Catch-all: never leak HTML/stack trace; give user a real message
        msg = str(e) or e.__class__.__name__
        return JSONResponse({"error": f"Clip export failed: {msg[:360]}"}, 500)


class BatchIn(BaseModel):
    url: str = ""
    upload_id: str = ""
    clips: list[dict]              # [{start,end,caption_text, caption_style?, quality?, vertical?, remove_fillers?, crop_mode?, font_size?, margin_v?}]
    quality: str = "720"
    caption_style: str = "hormozi"
    vertical: bool = True
    remove_fillers: bool = True
    crop_mode: str = "blur"
    font_size: int = 0
    margin_v: int = 0
    platform: str = "tiktok"


@app.post("/api/clip/batch")
def batch_clip(body: BatchIn):
    """Render multiple clips for the same source in sequence."""
    out = []
    errors = 0
    for i, c in enumerate(body.clips or []):
        try:
            payload = ClipIn(
                url=body.url, upload_id=body.upload_id,
                start=float(c["start"]), end=float(c["end"]),
                vertical=c.get("vertical", body.vertical),
                quality=c.get("quality", body.quality),
                caption_style=c.get("caption_style", body.caption_style),
                caption_text=str(c.get("caption_text") or ""),
                remove_fillers=c.get("remove_fillers", body.remove_fillers),
                crop_mode=c.get("crop_mode", body.crop_mode),
                platform=c.get("platform", body.platform),
                font_size=int(c.get("font_size", body.font_size) or 0),
                margin_v=int(c.get("margin_v", body.margin_v) or 0),
            )
            resp = make_clip(payload)
            if isinstance(resp, JSONResponse):
                # make_clip can return JSONResponse on validation errors
                errors += 1
                out.append({"index": i, "error": resp.body.decode()[:200] if hasattr(resp,"body") else "error"})
                continue
            out.append({**resp, "index": i, "title": c.get("title","")})
        except Exception as e:
            errors += 1
            out.append({"index": i, "error": str(e)[:200]})
    return {"clips": out, "ok": sum(1 for x in out if "error" not in x),
            "errors": errors, "total": len(body.clips or [])}


@app.get("/api/clips/{name}")
def get_clip(name: str):
    path = os.path.join(CLIPS, os.path.basename(name))
    if not os.path.exists(path):
        return JSONResponse({"error": "clip not found"}, 404)
    return FileResponse(path, media_type="video/mp4", filename=name)


@app.get("/api/thumbs/{name}")
def get_thumb(name: str):
    path = os.path.join(THUMBS, os.path.basename(name))
    if not os.path.exists(path):
        return JSONResponse({"error": "thumbnail not found"}, 404)
    return FileResponse(path, media_type="image/jpeg")


app.mount("/", StaticFiles(directory=os.path.join(ROOT, "static"), html=True), name="static")
