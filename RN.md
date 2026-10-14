# Clipppers v1.5.4 — Fixed black bars (top+bottom only, full width) + harsher ramble filter

## ⬛ Black bars mode fixed (your exact ask)
Previous v1.5.3 "black bars" was fitting to the full canvas with `force_original_aspect_ratio=decrease`, which put black on the **SIDE** when the source was wider or narrower than the target — that made the video look narrow (pillarboxed). Wrong.

New behaviour (verified with pixel-perfect render probe):

- Video **always fills the full width** of the canvas (406px wide for 720p Shorts, 1080px for 1080p, etc.)
- Pure black strips appear **only on the top and bottom**, evenly centered — never on the sides.
- If the source is taller than the target (phone footage going into horizontal YouTube), it gets center-cropped vertically rather than shrunk, so it still fills full width.
- If the source is wider than the target (horizontal video going into Shorts), it scales to full width and black pads top+bottom.

Verified on rendered frames: 16:9 → 9:16 TikTok 720p produces a 406×720 frame with the video 406×228 dead-center (246px black top, 246px black bottom, 0px side pillars).

- 🫧 **Blurred BG** (default TikTok/Shorts look, same as before)
- 🔍 **Zoom & crop** (edge-to-edge fill, no bars)
- ⬛ **Black bars — top+bottom only, full width** (new/corrected)

All three work across every platform canvas (9:16 / 1:1 / 4:5 / 16:9). Backend also fixed `_res()` to always return even dimensions so h264 doesn't round widths down and cause 1-3px side gaps.

## 🧠 Clip ranking — ramble / "I went to blablabla then what yeah" now killed
v1.5.3 added conflict/stakes/pattern-interrupt scoring but still let through "story" windows that were just sequential narration with zero payoff ("so I went to this place, and then we talked, and then… i'unno"). New scoring changes:

- **Story payoff detector**: looks for twist/reveal/resolution phrases (`turns out`, `ended up`, `you won't believe`, `that's when`, `suddenly`, `stunned`, `got caught`, `plot twist`, `the kicker`, `on the spot`, …). Stories WITH a payoff get +4pts per hit.
- **Ramble penalty**: counts "and then / so then / then I / then we" — when those outnumber payoffs by 2+, deduct up to 20 points.
- **Story-without-payoff penalty**: if there are ≥2 story markers but zero payoff, zero conflict, and zero pattern-interrupts → deduct 30 points.

Test scores (v1.5.4):
| Clip | Score | Before |
|---|---|---|
| Boring "5 tips for productivity" | **3** | 42 |
| Ramble "I went to blablabla then yeah" | **25** | 37 |
| Story with twist/payoff ("turns out he was the CEO… 500k") | **74** | 69 |
| Controversy rant ("worst scam on the internet") | **66** | 66 |
| Drama / pattern-interrupt ("stop scrolling everyone is lying") | **97** | 99 |

So the top-3 batch export will now pick drama, reveals, controversies and stories WITH a punchline — not random "I went to the store" rambling.

## UI / misc
- Framing dropdown labels updated to make black-bars behaviour unambiguous: "⬛ Black bars (full width, top+bottom only)".
- Version bump → 1.5.4.

Unzip, run `run.bat` (Windows) or `./run.sh` (Mac/Linux), open http://localhost:8000.
