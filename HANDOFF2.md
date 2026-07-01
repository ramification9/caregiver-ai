# CareLog — Session Handoff 2
**Date:** 2026-07-01  
**Status:** Active development — Phase 1 due 2026-07-31

---

## What This Is
Browser-based AI logging tool for veteran and military family caregivers.  
ACL Caregiver AI Prize Challenge, Track 1. Up to $100K. Phase 1 due 2026-07-31 5:00 PM ET.

**Builder:** Veteran (not a caregiver). Builder directs, Claude builds.

---

## Deployment
| | |
|---|---|
| **Railway (live)** | https://web-production-88bed.up.railway.app |
| **GitHub** | https://github.com/ramification9/caregiver-ai |
| **GitHub Pages (test)** | https://ramification9.github.io/caregiver-ai/voice-test.html |
| **Local path** | /home/mrlog/caregiver-ai/ |

Railway auto-deploys from GitHub `master` branch. Procfile: `web: gunicorn app:app --bind 0.0.0.0:$PORT`

---

## Tech Stack
- **Backend:** Flask (Python 3), app.py (2196 lines)
- **Frontend:** Single-page Jinja2, templates/index.html (4939 lines)
- **DB:** SQLite, caregiver.db
- **Mode:** SANDBOX_MODE=True (keyword extraction, zero API calls) — Claude API wired but not activated
- **Port:** 5050 locally, $PORT on Railway

---

## DB State (as of 2026-07-01)
- 95 entries, 13 alerts, 4 medications, 49 wellbeing check-ins, 1 voice profile

**Tables:** entries, alerts, deletion_audit, patients, medications, med_log, caregivers, caregiver_checkins, caregiver_wellbeing, voice_profiles

---

## Demo Patient & Caregiver
- **Patient:** Robert (veteran, Spanish speaker, start of care: 2026-03-26)
- **Caregiver:** Jimmy
- **Seed data:** 3-month arc with emergency days and pattern alerts

---

## Hard Rules (never violate)
- Caregiver always has final say — AI flags and suggests, never acts autonomously
- Emergency detection: shows crisis resources, lets human decide, never delays
- Alert log: multi-party sign-off to delete — no single person can erase the record
- Caregiver voice: third person ("he didn't sleep" not "I didn't sleep")
- Caregiver is always treated as civilian (not a veteran)

---

## What's Built
- Log Today: voice/text entry, AI extraction, concern box, emoji tag chips
- Caregiver check-in: Step 2, 1–5 rating + note
- Emergency detection: 4-branch overlay (third_party > caregiver_safety > physical > mental)
- Pattern detection: accordion UI
- Clinician summary: print/export
- Medications: add/remove, NIH RxNorm interaction check
- Resources tab: veteran + civilian caregiver support
- Locked alert log: multi-party deletion (request → code → PIN), audit trail
- PIN lock screen: 5-attempt lockout, recovery question
- Patient setup, caregiver UUID (uuid4, never changes)
- Voice input: Web Speech API + Whisper.js fallback for iOS
- Voice ID enrollment: audio fingerprint, bandpass filter, voice-confirmed badge
- PWA: manifest, service worker, iOS meta, navy/gold C icon
- Translate tab: Spanish ↔ English (40+ languages), auto-saves, bubble UI
  - Auto read-back: caregiver→patient direction only (reads Spanish aloud to patient)
- History tab: calendar view, color-coded tiles, Month at a Glance, multi-day select
- Affirmation ticker: Great Vibes font, gold on navy

---

## What's NOT Built Yet (priority order)

### 1. Translate Tab — Tap-Anywhere TTS (IN PROGRESS THIS SESSION)
**What:** Tap any message bubble in the Translate chat → reads it aloud in the correct language.  
**Why:** Accessibility for blind users on Apple/iOS. Pure frontend — no backend needed.  
**How:** `speechSynthesis` (same pattern as voice-test.html `readAloud()`)  
**Logic:**
- Patient bubble → read translated text in `en-US`
- Caregiver bubble → read translated text in `SPEECH_LANG_MAP[patLang]`
- Tap again while speaking → cancel
- Visual: pulse/glow on speaking bubble

**Files to change:** `templates/index.html`  
**Key functions:** `tcAddMessage()` (~line 4783), CSS `.tc-bubble` (~line 520)  
**Pattern to follow:** `readAloud()` in `voice-test.html` lines 338–360

### 2. Real Claude API
SANDBOX_MODE=False, implement live_extract() ~line 580 app.py.  
Model: claude-haiku-4-5-20251001. User must provide ANTHROPIC_API_KEY env var in Railway.

### 3. Demo Video
Required for Phase 1 submission.

### 4. Caregiver Quotes
3 `[NOTE: Insert quote here]` placeholders in application/section1, section3, section4.

### 5. Application Cover Page
/home/mrlog/caregiver-ai/application/cover-page.md — name/email/phone/address blank.

### 6. SAM.gov UEI Registration
User must do this themselves (takes days).

### 7. Voice Login on Lock Screen
voice_profiles table exists, enrollment works, lock screen PIN UI doesn't offer voice auth yet.

### 8. Real App Icon
Placeholder C in place.

---

## Key Architecture
- **NAV_ORDER:** log → history → medications → patterns → summary → translate → resources → profile → alerts
- **PIN:** PBKDF2-SHA256, 200k iterations, 16-byte salt, in-memory lockout tracker
- **Caregiver UUID:** generated once, never changes even on PIN reset
- **Soft-delete alerts:** is_deleted flag, audit record always persists
- **SPEECH_LANG_MAP:** ~line 4567 in index.html — maps lang codes to BCP-47 tags

## Key Endpoints Added Recently
- GET /api/entries/dates — calendar metadata per day
- PUT /api/entry/<id>/update-note — translation auto-save
- GET /api/entries?dates=d1,d2,... — multi-date cal-panel fetch

---

## Application Docs
/home/mrlog/caregiver-ai/application/  
- cover-page.md, section1-need-and-solution.md, section2-implementation.md,  
  section3-usability-integration.md, section4-caregiver-ai-principles.md

---

## Session Context (2026-07-01)
Last session ended mid-work due to connection drop. We were starting the **tap-anywhere TTS** feature on translate bubbles. No backend code was written — starting fresh this session. Railway deploy is working. GitHub Pages voice-test.html is live and working.

**Git log (last 5):**
1. Add gunicorn and Procfile for Railway deployment
2. Use native SR on iOS Safari, only fall back to Whisper when SR unavailable
3. Add iOS voice input and auto read-back to Translate tab
4. Replace sandbox fake text with real Whisper.js transcription on iOS
5. Unlock SpeechSynthesis on first tap to fix iOS auto read-back
