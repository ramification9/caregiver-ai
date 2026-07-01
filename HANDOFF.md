# CareLog — Session Handoff
**Date:** 2026-06-24  
**Project:** ACL Caregiver AI Prize Challenge, Phase 1 — due 2026-07-31 5:00 PM ET  
**Path:** `/home/mrlog/caregiver-ai/`  
**Run:** `bash run.sh` (user runs it — never start Flask from Claude)  
**Port:** 5050  
**Stack:** Flask / Python 3, SQLite (`caregiver.db`), Jinja2, vanilla JS, Web Speech API

---

## What This Is

CareLog is a browser-based AI logging tool for veteran and military family caregivers. The caregiver speaks or types observations naturally; AI extracts structured data, detects patterns, flags emergencies, and generates clinician-ready summaries. The app is at TRL 3 — fully functional proof of concept, running in sandbox mode (keyword extraction, no live API calls).

The patient in the demo is **Robert** (veteran). The caregiver is **Jimmy**. Robert speaks Spanish. Start of care is **2026-03-26**.

---

## Current State

### Database
- 97 entries (3-month arc: Mar 26 → Jun 24)
- 8 alerts (2 mental, 3 physical, 3 pattern)
- 4 medications (Sertraline 100mg, Prazosin 2mg, Ibuprofen 400mg, Lisinopril 10mg)
- 48 caregiver wellbeing check-ins

### Code
- `templates/index.html` — 4503 lines (single-page app)
- `app.py` — 2028 lines
- `application/` — 5 markdown docs for the prize submission (cover-page.md through section4)

---

## Nav Order
`log → history → medications → patterns → summary → resources → alerts`

---

## What's Built (complete and working)

- **Log Today** — voice or text entry, AI extraction, emoji tag chips, concern box
- **Caregiver check-in** — Step 2, 1–5 rating + optional note, saves independently to `caregiver_wellbeing` table
- **Affirmation ticker** — Great Vibes font, gold, navy bg, 60s scroll
- **Emergency detection** — 4 branches: mental / physical / caregiver_safety / third_party. Overlay with appropriate resources. Post-crisis check-in.
- **Pattern detection** — repeating keywords flagged over 7-day windows, accordion UI in Patterns tab
- **Clinician-ready summary** — print/export, covers sleep/mood/appetite/medication/appointments
- **Medications tab** — add/remove, NIH RxNorm interaction check
- **Resources tab** — veteran resources + permanent civilian caregiver well-being section (SAMHSA, 988, etc.)
- **Locked alert log** — multi-party deletion: request → one-time code → PIN confirm. Full audit trail (`deletion_audit` table). Soft-delete only.
- **PIN lock screen** — PBKDF2-SHA256, 5-attempt lockout
- **Recovery question** — custom question, 5-attempt lockout, two-step flow
- **Patient setup** — name, veteran/civilian flag, relationship
- **Caregiver UUID** — persistent, survives PIN reset
- **Voice input** — Web Speech API, Chrome/Edge only. "Stop note" command ends recording.
- **Voice ID enrollment** — 5-sec audio fingerprint (pitch, energy, spectral centroid, 32-bin freq profile) stored in `voice_profiles` table. Bandpass filter during recording. Voice-confirmed badge on extraction.
- **PWA foundation** — manifest.json, service worker, iOS meta tags, navy/gold "C" icon
- **Translate tab** — Spanish ↔ English (or any language pair). Speak button per party. Translation = prominent bubble, original = subdued italic. Auto-saves to log on every utterance (no manual button — malpractice-proof). Uses Google Translate unofficial API.
- **History tab — Calendar view**
  - Single month grid, day tiles
  - Color-coded: emergency = red fill, pattern = amber fill, secondary vertical bars for additional types
  - Day 1 badge on start-of-care tile
  - Nav: prev/next month+year, « » buttons disabled at bounds, "⚑ Start of Care" + "Today ›" jump buttons
  - Multi-day selection (click any tiles, non-consecutive OK)
  - Cal-panel below shows selected days' entries grouped by date header
  - **Month at a Glance** — below the grid, shows: Days Logged, Total Entries stats (muted), + Emergency Days / Pattern Alerts / Translation stat tiles (clickable — selects all those dates at once). Alert rows fetched from `/api/alerts?date=YYYY-MM`, rendered with proper badge labels (PATTERN, MENTAL HEALTH CRISIS, etc.) matching the Alerts tab, left color bar. Clicking a row selects that date and loads entries.
- **Seed data** — 3-month arc. Button on lock screen still says "14 days" (known label bug, minor).

---

## Key Technical Details

### SANDBOX_MODE
`app.py` line 17: `SANDBOX_MODE = True`  
Flip to `False` and implement `live_extract()` (line ~580) to go live. The function signature and comment are already there — just needs the Anthropic API call.

### SpeechRecognition gotcha
Chrome only allows one SR instance at a time. `stopWakeListener()` nulls `onend`/`onerror` before calling `.stop()` to prevent the wake listener from rescheduling and killing the translate recognition. Guard in `startWakeListener`: `if (!SR || isRecording || wakeActive || tcLive) return;`

### Translation auto-save
`tcSessionEntryId` tracks the DB entry ID. First `tcAddMessage()` call POSTs `/api/entry` and stores the ID. Each subsequent call PUTs `/api/entry/${tcSessionEntryId}/update-note`. Power loss = last utterance already saved.

### Calendar data flow
- `/api/entries/dates` → returns all entry dates with `{date, entry_count, has_emergency, has_translation, has_pattern}` → stored in `calEntryDates` object
- `calFirstDate` / `calFirstYear` / `calFirstMonth` — set from first entry date, gates backward nav
- `calSelected` — Set of "YYYY-MM-DD" strings, drives multi-day panel
- `/api/entries?dates=date1,date2,...` — comma-param for multi-date cal-panel fetch

### Alert priority in tiles
emergency (red fill) > pattern (amber fill) > observation (navy vbar only)  
Translation always a secondary blue vbar, never the primary fill.

### Endpoints added this session
- `GET /api/entries/dates` — calendar metadata
- `PUT /api/entry/<id>/update-note` — translation auto-save
- `GET /api/entries?dates=...` — multi-date fetch (existing endpoint extended)

---

## What's NOT Built Yet (priority order)

1. **Real Claude API** — `SANDBOX_MODE = False`, implement `live_extract()`. User needs to provide API key. Model: `claude-haiku-4-5-20251001` (cheapest, ~5–6 cents/caregiver/month).
2. **Demo video** — required for Phase 1 submission.
3. **Caregiver quotes** — 3 `[NOTE: Insert quote here]` placeholders: Section 1 line 63, Section 3 (check file), Section 4 (check file).
4. **Application cover page** — `/application/cover-page.md` — name, email, phone, address blank.
5. **SAM.gov UEI** — user must register (federal prize eligibility, can take days).
6. **Voice login on lock screen** — `voice_profiles` table exists, enrollment works, but lock screen PIN UI doesn't offer voice auth yet.
7. **Deploy to Railway** — needs gunicorn, Procfile, PORT env var, SQLite volume pinned.
8. **Real app icon** — placeholder "C" in place.
9. **Seed data button label** — says "14 days" on lock screen, should say "3 months".

---

## Application Docs (`/application/`)

| File | Status |
|------|--------|
| `cover-page.md` | Blank — needs name, email, phone, address |
| `section1-need-and-solution.md` | Complete except quote placeholder line 63 |
| `section2-implementation.md` | Check for placeholders |
| `section3-usability-integration.md` | Check for placeholders |
| `section4-caregiver-ai-principles.md` | Check for placeholders |

---

## Hard Rules (never break)

- Caregiver has final say — AI flags and suggests, never acts autonomously
- Emergency detection surfaces resources, lets human decide, never delays
- Alert log requires multi-party sign-off to delete — no single person can erase it
- Caregiver is always treated as civilian (not a veteran)
- Voice in third person: "he didn't sleep" not "I didn't sleep"
- Never start Flask from Claude — user runs it
- Never add Co-Authored-By or AI attribution to commits

---

## Where We Left Off

Last work: **Month at a Glance** in the History tab. The alert rows now fetch real data from `/api/alerts?date=YYYY-MM` and render with proper badge labels (same as Alerts tab). Clickable stat tiles (Emergency Days, Pattern Alerts, Translations) select all dates of that type and scroll to the entry panel. "Logged Entries" section header separates the alert summary from the entry cards below.

User was checking visual alignment of the layout before the session ended.

**Next logical step:** Flip `SANDBOX_MODE = False` and wire in a real Claude API call, or record the demo video — whichever the user prioritizes.
