"""Clipppers — paste a link, get the key moments, the hook breakdown, and ready-to-post clips."""
from __future__ import annotations

import os
import uuid

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analyzer import DEMO, analyze_transcript, parse_captions
from .captions import STYLE_CHOICES, STYLES, build_ass
from .clipper import QUALITIES, cut
from .projects import ProjectStore
from .sources import WORK, download_section, fetch_link

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIPS = os.path.join(WORK, "clips"); UPLOADS = os.path.join(WORK, "uploads")
os.makedirs(CLIPS, exist_ok=True); os.makedirs(UPLOADS, exist_ok=True)
UPLOAD_MAP: dict[str, str] = {}   # upload_id -> local file path

app = FastAPI(title="Clipppers")


class AnalyzeIn(BaseModel):
    url: str = ""
    transcript: str = ""
    target_len: float = 38


class ClipIn(BaseModel):
    url: str = ""
    upload_id: str = ""
    start: float
    end: float
    vertical: bool = True
    quality: str = "720"          # 1080 | 720 | 480
    caption_style: str = "none"   # none | hormozi | mrbeast | karaoke | neon | minimal | cinematic
    caption_text: str = ""        # transcript text covering [start, end]


STORE = ProjectStore(os.path.join(WORK, "projects.json"))


@app.get("/api/options")
def options():
    return {"qualities": {k: v["label"] for k, v in QUALITIES.items()},
            "caption_styles": {"none": "🚫 No burned-in captions", **{k: v["label"] for k, v in STYLES.items()}}}


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


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/analyze")
def analyze(body: AnalyzeIn):
    try:
        warning = None
        if body.transcript.strip():                     # pasted transcript wins
            from .sources import youtube_id
            data = {"meta": {"title": "Pasted transcript", "url": body.url,
                             "youtube_id": youtube_id(body.url)}, "segments": parse_captions(body.transcript)}
        elif body.url.strip():
            data = fetch_link(body.url.strip())
            warning = data.get("warning")
        else:
            return JSONResponse({"error": "Paste a video link or a transcript first."}, 400)
        result = analyze_transcript(data["segments"], data["meta"], body.target_len)
        if warning and not result.get("warning"):
            result["warning"] = warning
        if data.get("source"):
            result["source"] = data["source"]
        return result
    except ValueError as e:
        return JSONResponse({"error": str(e)}, 400)
    except Exception as e:                               # never leak a stack trace to the UI
        return JSONResponse({"error": f"Something went wrong analysing that: {e}"[:300]}, 500)


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
        result = analyze_transcript(parse_captions(raw), {"title": name})
        result["upload_id"] = uid
        return result
    path = os.path.join(UPLOADS, f"{uid}_{name}")
    with open(path, "wb") as f:
        f.write(await file.read())
    UPLOAD_MAP[uid] = path
    segments = parse_captions(transcript) if transcript.strip() else []
    result = analyze_transcript(segments, {"title": name, "url": ""})
    result["upload_id"] = uid
    if not segments:
        result["warning"] = ("Video saved — now paste its transcript (or drop a .srt) so we can find "
                             "moments. You can still cut clips from it by typing timestamps below.")
    return result


@app.post("/api/clip")
def make_clip(body: ClipIn):
    if body.end <= body.start:
        return JSONResponse({"error": "End time must be after start time."}, 400)
    if body.end - body.start > 180:
        return JSONResponse({"error": "Keep clips under 3 minutes."}, 400)
    if body.quality not in QUALITIES:
        return JSONResponse({"error": f"Unknown quality '{body.quality}'."}, 400)
    if body.caption_style not in STYLE_CHOICES:
        return JSONResponse({"error": f"Unknown caption style '{body.caption_style}'."}, 400)
    try:
        tag = f"{int(body.start)}_{int(body.end)}_{'v' if body.vertical else 'h'}_{body.quality}_{body.caption_style}"
        ass = None
        caption_args = {}
        if body.caption_style != "none":
            ass_path = os.path.join(CLIPS, f"cap_{tag}.ass")
            q = QUALITIES[body.quality]
            w, h = q["vertical"] if body.vertical else q["horizontal"]
            build_ass(body.caption_text, body.end - body.start, body.caption_style, ass_path, w, h)
            caption_args = {"caption_ass": ass_path}
        if body.upload_id and body.upload_id in UPLOAD_MAP:
            out = os.path.join(CLIPS, f"clip_{body.upload_id}_{tag}.mp4")
            cut(UPLOAD_MAP[body.upload_id], body.start, body.end, out, body.vertical, body.quality, **caption_args)
        elif body.url:
            out = download_section(body.url, body.start, body.end, body.vertical, CLIPS,
                                   body.quality, caption_args.get("caption_ass"))
        else:
            return JSONResponse({"error": "No video source for that clip."}, 400)
        return {"download": f"/api/clips/{os.path.basename(out)}", "file": os.path.basename(out),
                "quality": body.quality, "caption_style": body.caption_style,
                "size_kb": round(os.path.getsize(out) / 1024)}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, 400)


@app.get("/api/clips/{name}")
def get_clip(name: str):
    path = os.path.join(CLIPS, os.path.basename(name))
    if not os.path.exists(path):
        return JSONResponse({"error": "clip not found"}, 404)
    return FileResponse(path, media_type="video/mp4", filename=name)


app.mount("/", StaticFiles(directory=os.path.join(ROOT, "static"), html=True), name="static")
