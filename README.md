# ✂️ Clipppers

**Find the hook. Clip the moment.** — a Wayin/Opus-style clip finder & clip maker for long videos.

Paste a link → Clipppers pulls the transcript, scores every 15–60s window for
virality, **grades the first-3-second hook of every clip separately** (that's what
stops the scroll), ranks the key moments, and cuts real downloadable 9:16 MP4s.

![flow](https://img.shields.io/badge/link%20%E2%86%92%20transcript%20%E2%86%92%20moments%20%E2%86%92%20MP4-purple)

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

No API keys. Transcripts come from the video's own captions (yt-dlp),
cutting is done by ffmpeg (bundled via `imageio-ffmpeg` — no system install).

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
