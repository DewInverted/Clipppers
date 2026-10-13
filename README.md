# ✂️ Clipppers

**Find the hook. Clip the moment.** — a Wayin/Opus-style clip finder & clip maker for long videos.

## ⚡ Open it fast

**Option A — in your browser, zero install (GitHub Codespaces):**
click **`< > Code` → Codespaces → Create codespace on main**, wait ~1 min, and the
site opens automatically (port 8000 is forwarded for you — config in `.devcontainer/`).

**Option B — on your computer, one command:**

```bash
python3 start.py        # Windows: double-click run.bat · creates .venv, installs, opens your browser
```

Then it's at **http://localhost:8000**. Prefer manual?

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

No API keys. Transcripts come from the video's own captions (yt-dlp),
cutting is done by ffmpeg (bundled via `imageio-ffmpeg` — no system install).

## 💾 Your work is saved

- Every trim, title, caption and style/quality choice **auto-saves as you type** —
  refresh or close the tab and your last session is restored.
- **My library** keeps saved projects/edits both in your browser (localStorage)
  and on the server (`/api/projects`), with one-click reload, re-download,
  delete, and **export/import of the whole library as JSON**.

## 🎨 Caption styles & 📦 export quality

Burned into the MP4 by ffmpeg (word timing estimated from the transcript):
🟨 **Hormozi** (word-by-word yellow highlight) · 🔥 **MrBeast** (huge centred pop) ·
🎤 **Karaoke** (cyan word sweep) · 💜 **Neon Pop** · ⬜ **Minimal** · 🎬 **Cinematic** — or none.

Every export can be **1080p** (best), **720p** (balanced) or **480p** (small/fast),
in 9:16 vertical or 16:9.

## What you get

| Feature | How |
|---|---|
| 🔗 **Link analysis** | YouTube, TikTok, Twitch, podcasts, direct files (anything yt-dlp supports). Falls back to video chapters, then to a pasted transcript / `.srt` / `.vtt` upload |
| 🎣 **Hook scoring** | Every candidate's opening line is scored 0–100 (S–D grade): questions, numbers, "nobody talks about…", direct commands, curiosity gaps, length, direct address |
| 📺 **Opening-hook report** | Grades your video's *actual* first seconds and writes 3 stronger opening hooks for it |
| 🏆 **Key moments** | Ranked cards labelled Hot Take / Story / Insight / Funny / Money / Controversy, each with *why it works*, pace (wpm), title, caption & hashtags |
| 🗺️ **Moment map** | Colour-coded timeline of the whole video — click a block to jump to that clip |
| ✍️ **Hook rewrites** | 3 scroll-stopping rewrites per clip, built from the clip's own strongest phrase (numbers first) |
| ✂️ **Clip maker** | One click downloads just that section and cuts a vertical **1080×1920** (or 16:9) MP4; plus a manual timestamp cutter. Upload your own video file if a platform blocks downloads |
| 🎬 **In-page preview** | YouTube moments play inline at the exact start/end before you cut |

Scoring is transparent heuristics (`app/analyzer.py`) — emotion & power words,
speech pace (130–185 wpm sweet spot), questions/numbers, laughter markers,
information density, and clean sentence boundaries. It's designed so an LLM
can later be dropped in on top of the same structured output, but none is required.

## Layout

```
app/main.py      FastAPI API + static hosting   (/api/analyze, /api/clip, /api/upload, /api/demo)
app/analyzer.py  hook + virality scoring, moment finding, caption/title generation, VTT/SRT parsing
app/sources.py   yt-dlp metadata/caption fetching, section download
app/clipper.py   ffmpeg cutting (9:16 crop/pad via imageio-ffmpeg)
static/          the web UI (no build step)
```

## Notes & limits

- Clips are capped at 3 minutes; downloads fetch ≤720p to stay fast.
- Some platforms block automated downloads from some networks — if a cut
  fails, upload the video file instead (same analysis, local cutting).
- Uploaded videos are stored only in the OS temp dir (`clipppers/uploads`).
