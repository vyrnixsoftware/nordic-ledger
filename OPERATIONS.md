# Operations – how The Nordic Ledger runs (as built, Aug 2026)

Channel: https://www.youtube.com/@TheNordicLedger (UCNuvBvFInY5F2GCX6qjVZZg) · Repo: github.com/vyrnixsoftware/nordic-ledger

## Architecture (zero owner effort after setup)
1. **Scripts** – Claude researches and writes `scripts/NNN-slug.md` (scene-marked, sourced), runs `compliance_check`, commits via the owner's browser (GitHub web upload).
2. **Build** – GitHub Actions `build-videos` (cron Mon+Thu 03:00 UTC, or manual) renders every unbuilt script:
   Piper TTS (en-us-ryan-high, bundled from GitHub releases) → Pillow keyframes → ffmpeg → thumbnails, metadata, subtitles.
   Outputs go to a GitHub Release `vNNN-slug` and to the orphan branch `builds/` (kept to the newest 12) which raw.githubusercontent.com serves with CORS.
3. **Upload** – In the owner's Chrome (Claude-in-Chrome bridge), on YouTube Studio's upload dialog, `tools/youtube_upload_snippet.js`
   fetches `builds/<id>/video.mp4` and injects it into Studio's file input; Claude fills title/description/tags/thumbnail from `metadata.json`,
   sets "not made for kids", altered-content flag per `synthetic_label`, and schedules publish (Tue/Fri 15:00 UTC).
   Several videos are scheduled ahead in one sitting, so a browser session is needed only every few weeks.
4. **Growth loop** – Claude reviews Studio analytics monthly, adjusts topics/thumbnails, drafts sponsor outreach (`channel/sponsor-outreach.md`).

## Owner one-time items (only what nobody else can do)
- YouTube channel: created 15 Aug 2026 on the owner's Google account. AdSense: owner links it when YPP threshold is reached (Claude will say when).
- Optional: ELEVENLABS_API_KEY as an Actions secret for a better voice (owner enters the key; Claude never handles secrets).
- Keep the Claude desktop app + Chrome logged in when Claude announces an upload session.

## Guardrails
- ≤3 uploads/week; every script passes `compliance_check` (sources, chapters, ≥4 scene types, no clichés, scene length).
- Description always includes chapters, "How this video was made" (AI disclosure), numbered sources, disclosure line.
- `synthetic_label: true` only if realistic generated footage of real people/events is used (never by default). No third-party footage or music.
- One channel, one account. Corrections pinned publicly if a factual error is found.
