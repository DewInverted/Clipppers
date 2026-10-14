# Clipppers v1.5.2 — Bug-fix: Suggestions work, Instagram/TikTok download fixed

This release fixes real-world issues reported right after v1.5.1.

## Fixes
- **🔥 Suggested / Discover videos no longer crash.** The previous code tried to use `ytsearchshorts{N}:` which is **not** a real yt-dlp URL prefix — it threw `Unsupported url scheme: "ytsearchshorts8"`. yt-dlp only supports `ytsearchN:` (and `ytsearchdateN:` on some builds), so we now use standard `ytsearchN:` queries with varied query phrasing (`… viral`, `… #shorts`, `… tips`, `… 2025`) and still filter Shorts/songs/channels/playlists out of results.
- **📸 Instagram Reels / TikTok / Twitch etc downloads fixed.** We were accidentally injecting YouTube-specific extractor args (`player_client=tv_simply,android,web`, `player_skip=webpage,js,configs`, DASH/HLS manifest flags) into **every** yt-dlp call regardless of host, which confused non-YouTube extractors. Those are now only applied to YouTube URLs. Also switched to an iPhone Safari UA that Instagram serves public Reels to without login, and loosened the format selector to accept muxed MP4 (many non-YouTube hosts don't expose separate m4a audio tracks).
- **Reference videos**: the two Shorts links you sent (`l9S0OyxXojI`, `NPobjvv2zrs`) were only used as visual/style study for the bounce-caption look; they were never embedded, linked, or shipped in Clipppers. I confirmed neither ID appears anywhere in the app code — the bounce is implemented natively in ASS (`{\fscx150\fscy150\t(0,80ms,3,\fscx100\fscy100)}`) rather than clipping/importing any external footage.
- Server version bump → 1.5.2.

## Cross-platform export (from v1.5.1, retained)
- TikTok / YouTube Shorts / IG Reels / Stories / IG feed 1:1 / IG 4:5 / YouTube 16:9 / Twitter+FB.
- Platform-safe caption safe-zones, -14 LUFS loudnorm, generalized blur/crop/fit framing.
- Dual MP4 output (clean cut + captioned bounce edit).

Unzip, run `run.bat` (Windows) or `./run.sh` (Mac/Linux), open http://localhost:8000.
