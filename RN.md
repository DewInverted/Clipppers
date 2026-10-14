# Clipppers v1.5.3 — Better clip picks + Black bars / Zoom framing

Two big upgrades from feedback: the auto-clips were boring, and you wanted more framing options.

## 🔥 Auto-clips now pick the *interesting* moments
The old scorer was basically "how fast is this person talking + do they say a power word" — it picked generic tips and listicles every time. New scorer heavily rewards the things that actually perform on short-form:

- **Pattern-interrupt words** (stop / wait / never / nobody / exposed / scam / insane / literally …) — 4pts each, capped at 28. These are the words that MAKE people stop scrolling.
- **Conflict & stakes** (fired / sued / arrested / scam / lie / destroyed / illegal / dangerous …) — drama = views.
- **Before/after transformation** (used to / turned out / realized / lost / gained …) — story fuel.
- **Specific numbers** ($50k, 300%, 11 months, 7 steps) — concrete always beats vague.
- **Money talk** ($, dollars, profit, revenue, broke, rich, cash …) — 4pts per hit.
- **Direct "you/your" address** + contrast words ("but", "actually", "turns out") — creates tension.
- **Hooks are 35% of score** (was 38%, now the other categories are stronger too).
- Empty filler windows with <8 content words get a big penalty so you don't get random mumbling.

Tested against sample transcripts: generic "5 tips for drinking water" scores **42**; a "stop scrolling everyone is lying about making money online" rant scores **99**; an embarrassing/funny boss story scores **76**; a rags-to-riches story scores **58**.

**Discover (suggested videos)** search strategies also rewritten — instead of boring `fitness tips tutorial`, it searches `fitness #shorts`, `fitness exposed`, `fitness crazy story`, `fitness you won't believe`, `fitness the truth about`, `fitness tips that actually work`. More drama, more stories, less listicles.

## 📐 3 framing options (was 2)
Per clip, in batch defaults, and in the manual cutter:

- 🫧 **Blurred BG** (default) — classic Shorts/TikTok look with a zoomed-blurred copy of the footage behind the letterboxed speaker.
- 🔍 **Zoom & crop** — fills the frame edge-to-edge with a center crop (no bars, no blur). Renamed from "center-crop" to make it obvious this ZOOMS IN. Old `crop` value still accepted for saved projects.
- ⬛ **Black bars (cinematic)** — NEW. Letterboxes/pillarboxes on pure black instead of blur. Clean, cinematic, no distracting background — good for when the blurred BG looks messy or when you want that premium YouTube Shorts / Alex Hormozi clean look.

Works for every platform aspect ratio (9:16, 1:1, 4:5, 16:9).

## Fixes
- Backend validation accepts `blur|zoom|crop|black` (crop = backwards compat alias for zoom).
- Updated framing tooltip text.
- Version bump → 1.5.3.

Unzip, run `run.bat` (Windows) or `./run.sh` (Mac/Linux), open http://localhost:8000.
