# Clipppers v1.5.1 — Cross-platform export

New in this release: render clips sized correctly for every platform you post to.

## New
- **📲 Platform presets** (dropdown per clip + manual cutter + batch):
  - 📱 TikTok (9:16 · 1080×1920)
  - ▶️ YouTube Shorts (9:16)
  - 📸 Instagram Reels (9:16)
  - ⭕ Instagram / Facebook Stories (9:16)
  - ⬜ Instagram feed square (1:1 · 1080×1080)
  - 📸 Instagram feed portrait (4:5 · 864×1080)
  - 📺 YouTube long-form / horizontal (16:9 · 1920×1080)
  - ▬ Twitter / X / Facebook horizontal (16:9)
- **Platform-safe caption zones** — captions automatically push up above each app's bottom UI chrome (TikTok/Shorts/Reels have the largest margins, landscape YouTube has a small lower-third margin).
- **🔊 Audio loudness normalization (-14 LUFS)** applied to both the clean cut and the captioned export so your clips hit platform loudness targets without extra post.
- Framing filters generalized: blur/crop/fit now work for any aspect ratio (not just 9:16). Pick horizontal 16:9 and the crop-blur framing + bounce captions still behave correctly.
- Platform badge shown on each clip card and in the post-export modal so you can see at a glance what size was rendered.

## Fixes
- Caption burn and cut pipeline both apply loudnorm now (clean path + captioned path both normalized).
- Quality tiers (480p/720p/1080p) scale the long side correctly for square, 4:5 and 16:9 canvases.
- Manual cutter platform select auto-toggles vertical/horizontal.

## From v1.5.0
- **⚡ TikTok Bounce captions** (default): one huge word dead-center, pops from 150% → 100% with overshoot, 8px black outline, power-word coloring (yellow = pattern-interrupts, red = money/danger, cyan = "you/your", lime = numbers/percent/dollar).
- **Dual MP4 output** — every export produces `clean_{tag}.mp4` (filler-free, framed, no captions) + `clip_{tag}.mp4` (same video with bounce captions burned). Two download buttons in every card.

Unzip, run `run.bat` (Windows) or `./run.sh` (Mac/Linux), open http://localhost:8000.
