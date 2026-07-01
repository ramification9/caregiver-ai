# CareLog — Session Handoff 2
**Date:** 2026-07-01 (updated end of session)
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
**init_db() and migrate_db() run at module level** — works correctly under gunicorn.  
**Seed data:** GET `https://web-production-88bed.up.railway.app/api/seed` — populates Robert, Jimmy, 120 days.

---

## Tech Stack
- **Backend:** Flask (Python 3), app.py (~2230 lines)
- **Frontend:** Single-page Jinja2, templates/index.html (~5000 lines)
- **DB:** SQLite, caregiver.db
- **Mode:** SANDBOX_MODE=True (keyword extraction, zero API calls) — Claude API wired but not activated
- **Port:** 5050 locally, $PORT on Railway

### Backend libraries (requirements.txt)
- `flask`, `gunicorn`, `gTTS`, `deep-translator`, `SpeechRecognition`

---

## DB State (Railway resets on deploy — run /api/seed after each deploy)
**Tables:** entries, alerts, deletion_audit, patients, medications, med_log, caregivers, caregiver_checkins, caregiver_wellbeing, voice_profiles

---

## Demo Patient & Caregiver
- **Patient:** Robert (veteran, Spanish speaker, blind)
- **Caregiver:** Jimmy
- **Seed:** 120-day arc, emergency days, pattern alerts

---

## Hard Rules (never violate)
- Caregiver always has final say — AI flags and suggests, never acts autonomously
- Emergency detection: shows crisis resources, lets human decide, never delays
- Alert log: multi-party sign-off to delete — no single person can erase the record
- Caregiver voice: third person ("he didn't sleep" not "I didn't sleep")
- Caregiver is always treated as civilian (not a veteran)

---

## What's Built

### Translate Tab — COMPLETED THIS SESSION ✓
Full bidirectional translation with blind patient accessibility:

**Architecture:**
- **STT:** Backend `/api/stt` — MediaRecorder → POST audio → SpeechRecognition + Google STT → text. Zero client download, works on iOS and Android.
- **Translation:** Backend `/api/translate` — deep-translator + Google Translate. Server-side cache prevents inconsistent results.
- **TTS:** Backend `/api/tts` — gTTS → MP3 → `<audio>` tag. Works on all iOS versions (no speechSynthesis unreliability).

**Blind patient flow (Robert):**
- Caregiver speaks English → auto-translates → **reads Spanish aloud to Robert automatically**
- Robert speaks Spanish → translates → English bubble shown on screen for caregiver
- Tap anywhere in message window → replays last audio for Robert
- Tap any bubble → replays that specific bubble's audio
- Emergency detected → audio stops immediately, overlay takes over

**Protection layers:**
- Emergency check before audio plays — emergency always takes priority
- Audio stops on clearTranslate
- All conversations auto-saved to entries table
- 500-char limit on TTS, no content logging in STT/TTS endpoints

### Everything else built previously
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
- Voice ID enrollment: audio fingerprint, bandpass filter, voice-confirmed badge
- PWA: manifest, service worker, iOS meta, navy/gold C icon
- History tab: calendar view, color-coded tiles, Month at a Glance, multi-day select
- Affirmation ticker: Great Vibes font, gold on navy

---

## What's NOT Built Yet / Not Done (priority order)

### 1. SAM.gov UEI Registration ⚠️ MOST URGENT
**IN PROGRESS** — Francisco Ramirez (far2990@gmail.com) started 2026-07-01.
Left off at "Create New Entity" screen. Must complete and submit — takes 7-14 business days.
UEI number goes in cover-page.md when received.

### 2. Application Cover Page — PARTIALLY DONE
Name (Francisco Ramirez) and email (far2990@gmail.com) filled in.
Still missing: **phone, address, UEI number**.
File: /home/mrlog/caregiver-ai/application/cover-page.md

### 3. Caregiver Quotes — 4 PLACEHOLDERS REMAINING
- Section 1 line 63: 1 quote from caregiver feedback session
- Section 3 lines 78-80: 3 observations (quote, hesitation, intended use)
- Section 4 line 101: 1 quote
Francisco must provide these from his real caregiver testing session.

### 4. Partnerships Section
Application judged on multi-stakeholder involvement. Solo project needs explicit response addressing this gap. Suggest adding a paragraph to Section 2.

### 5. Demo Video
Required to show working prototype. Not recorded yet.

### 6. Real Claude API
SANDBOX_MODE=False, implement live_extract() ~line 580 app.py.
Model: claude-haiku-4-5-20251001. Need ANTHROPIC_API_KEY env var in Railway.

### 7. Appendices (max 10 pages)
Not started. Could include screenshots, sample output logs, caregiver feedback summary.

### 8. Data Output Logs
Required per Technical Requirements Guide. Not started.

### 9. Voice Login on Lock Screen
voice_profiles table exists, enrollment works, lock screen PIN UI doesn't offer voice auth.

### 10. Real App Icon
Placeholder C in place.

---

## Key Architecture
- **NAV_ORDER:** log → history → medications → patterns → summary → translate → resources → profile → alerts
- **PIN:** PBKDF2-SHA256, 200k iterations, 16-byte salt, in-memory lockout tracker
- **Caregiver UUID:** generated once, never changes even on PIN reset
- **Soft-delete alerts:** is_deleted flag, audit record always persists
- **SPEECH_LANG_MAP:** ~line 4567 in index.html — maps lang codes to BCP-47 tags
- **Translation cache:** `_translation_cache` dict in app.py — keyed by (text, from, to)

## Key Endpoints
- GET/POST `/api/seed` — populate demo data
- POST `/api/stt` — audio file → transcribed text (FormData: audio + lang)
- POST `/api/translate` — {text, from, to} → {translated}
- POST `/api/tts` — {text, lang} → MP3 audio
- GET `/api/entries/dates` — calendar metadata per day
- PUT `/api/entry/<id>/update-note` — translation auto-save
- GET `/api/entries?dates=d1,d2,...` — multi-date cal-panel fetch

---

## Application Docs
/home/mrlog/caregiver-ai/application/  
- cover-page.md, section1-need-and-solution.md, section2-implementation.md,  
  section3-usability-integration.md, section4-caregiver-ai-principles.md

---

## Git log (last 5 as of end of session)
1. Update handoff: SAM.gov in progress; fill in Francisco Ramirez name/email
2. Update HANDOFF2 — translate tab complete
3. Replace Whisper with backend STT via SpeechRecognition+Google — zero download
4. Add translation cache + retry — fixes inconsistent Google Translate results
5. Guard iOS MediaRecorder onstop against double-fire causing duplicate messages
