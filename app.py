from flask import Flask, request, jsonify, render_template
import sqlite3
import json
import random
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
import os
import uuid
import hashlib
import secrets

app = Flask(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

SANDBOX_MODE = True   # set False and implement live_extract() to go live
DB_PATH = os.path.join(os.path.dirname(__file__), "caregiver.db")

# ── Database ───────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS entries (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            raw_note            TEXT NOT NULL,
            extracted_tags      TEXT DEFAULT '{}',
            corrected_tags      TEXT DEFAULT NULL,
            is_emergency_flagged INTEGER DEFAULT 0,
            emergency_phrase    TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            entry_id            INTEGER REFERENCES entries(id),
            alert_type          TEXT NOT NULL,
            alert_message       TEXT NOT NULL,
            deletion_status     TEXT DEFAULT 'locked'
        );

        CREATE TABLE IF NOT EXISTS patients (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            name                TEXT NOT NULL,
            is_veteran          INTEGER DEFAULT 0,
            local_crisis_number TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS caregivers (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at        TEXT DEFAULT (datetime('now','localtime')),
            name              TEXT NOT NULL,
            relationship      TEXT DEFAULT NULL,
            caregiver_id      TEXT NOT NULL UNIQUE,
            pin_hash          TEXT DEFAULT NULL,
            auto_lock_minutes INTEGER DEFAULT 15
        );

        CREATE TABLE IF NOT EXISTS deletion_audit (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            alert_id        INTEGER REFERENCES alerts(id),
            requested_by    TEXT NOT NULL,
            reason          TEXT,
            status          TEXT DEFAULT 'denied'
        );

        CREATE TABLE IF NOT EXISTS medications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            name            TEXT NOT NULL,
            dosage          TEXT DEFAULT NULL,
            frequency       TEXT DEFAULT NULL,
            scheduled_time  TEXT DEFAULT NULL,
            notes           TEXT DEFAULT NULL,
            is_active       INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS med_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            entry_id    INTEGER REFERENCES entries(id),
            med_name    TEXT NOT NULL,
            status      TEXT NOT NULL,
            notes       TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS caregiver_checkins (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            entry_id    INTEGER REFERENCES entries(id),
            response    TEXT NOT NULL,
            wanted_support INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS caregiver_wellbeing (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            rating      INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            notes       TEXT DEFAULT NULL
        );
    """)
    conn.commit()
    conn.close()

def migrate_db():
    """Add columns introduced after initial schema — safe to run on every start."""
    conn = get_db()
    entry_cols = [row[1] for row in conn.execute("PRAGMA table_info(entries)").fetchall()]
    if "custom_tags" not in entry_cols:
        conn.execute("ALTER TABLE entries ADD COLUMN custom_tags TEXT DEFAULT NULL")
        conn.commit()
    if "caregiver_rating" not in entry_cols:
        conn.execute("ALTER TABLE entries ADD COLUMN caregiver_rating INTEGER DEFAULT NULL")
        conn.commit()
    cg_cols = [row[1] for row in conn.execute("PRAGMA table_info(caregivers)").fetchall()]
    if "pin_hash" not in cg_cols:
        conn.execute("ALTER TABLE caregivers ADD COLUMN pin_hash TEXT DEFAULT NULL")
        conn.commit()
    if "auto_lock_minutes" not in cg_cols:
        conn.execute("ALTER TABLE caregivers ADD COLUMN auto_lock_minutes INTEGER DEFAULT 15")
        conn.commit()
    if "security_question" not in cg_cols:
        conn.execute("ALTER TABLE caregivers ADD COLUMN security_question TEXT DEFAULT NULL")
        conn.commit()
    if "security_answer_hash" not in cg_cols:
        conn.execute("ALTER TABLE caregivers ADD COLUMN security_answer_hash TEXT DEFAULT NULL")
        conn.commit()
    wb_tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='caregiver_wellbeing'").fetchone()
    if not wb_tables:
        conn.execute("""CREATE TABLE caregiver_wellbeing (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            rating      INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            notes       TEXT DEFAULT NULL
        )""")
        conn.commit()
    else:
        wb_cols = [row[1] for row in conn.execute("PRAGMA table_info(caregiver_wellbeing)").fetchall()]
        if "notes" not in wb_cols:
            conn.execute("ALTER TABLE caregiver_wellbeing ADD COLUMN notes TEXT DEFAULT NULL")
            conn.commit()
    conn.close()

# ── Mock AI Extraction (swap this block for Claude API in production) ──────────

CAREGIVER_SAFETY_PHRASES = [
    "stabbed me", "he stabbed me", "she stabbed me",
    "shot me", "he shot me", "she shot me",
    "attacked me", "he attacked me", "she attacked me",
    "hit me with", "hit me hard", "struck me",
    "choked me", "he choked me", "she choked me",
    "came at me with", "came after me with",
    "threatened me with", "pointed a gun at me", "pointed a knife at me",
    "has a knife", "has a gun", "pulled a knife", "pulled a gun",
    "pulled out a gun", "pulled out a knife",
    "hurt me", "he hurt me", "she hurt me",
    "threw something at me", "threw him at me",
    "i am not safe", "i'm not safe", "im not safe",
    "he is violent", "she is violent", "getting violent with me",
    "being attacked", "under attack",
    "slapped me", "he slapped me", "she slapped me",
    "slapped her wife", "slapped his wife", "slapped her husband",
    "hit me", "he hit me", "she hit me", "hit her wife", "hit his wife",
    "punched me", "he punched me", "she punched me",
    "kicked me", "he kicked me", "she kicked me",
    "pushed me", "he pushed me", "she pushed me", "shoved me",
    "grabbed me", "he grabbed me", "she grabbed me",
    "threw something at me", "swung at me",
    "is hitting me", "keeps hitting me", "hit me again",
    "threatening me", "threatened me", "got physical with me"
]

THIRD_PARTY_VIOLENCE_PHRASES = [
    # physical assault toward others
    "hit his wife", "hit her wife", "hit his husband", "hit her husband",
    "hit his daughter", "hit his son", "hit her daughter", "hit her son",
    "hit the neighbor", "hit a neighbor",
    "beat his wife", "beat her wife", "beat his husband", "beat his daughter",
    "beat his son", "beat her daughter", "beat her son", "beat the neighbor",
    "punched his wife", "punched her wife", "punched his husband",
    "punched the neighbor", "punched a neighbor",
    "choked his wife", "choked her wife", "choked his husband",
    "choked the neighbor", "choked a neighbor",
    "shoved his wife", "shoved her wife", "shoved his husband",
    "attacked his wife", "attacked her wife", "attacked his husband",
    "attacked the neighbor", "attacked a neighbor",
    "grabbed his wife", "grabbed her wife", "grabbed his husband",
    "threw her against", "threw him against", "slammed her", "slammed him",
    "threatened his wife", "threatened her wife", "threatened his husband",
    "threatened the neighbor", "threatened a neighbor",
    # weapons toward others
    "shot the neighbor", "shot a neighbor", "shot his wife", "shot her wife",
    "shot his husband", "shot at someone", "shot at the",
    "stabbed the neighbor", "stabbed a neighbor", "stabbed his wife",
    "stabbed her wife", "stabbed his husband", "stabbed someone",
    "stabbed the dog", "shot the dog", "hurt the dog", "kicked the dog",
    "knife at his wife", "knife at her", "gun at his wife", "gun at her",
    "pulled a gun on", "pulled a knife on", "pointed a gun at his",
    "pointed a gun at her", "pointed a knife at his", "pointed a knife at her",
    # general harm to others
    "hurt his wife", "hurt her wife", "hurt his husband",
    "hurt the neighbor", "hurt someone else", "hurt a neighbor",
    "attacked someone", "hurt a child", "hurt the kids",
    "violent toward", "violent with his wife", "violent with her",
    "got violent with", "becoming violent toward",
]

SELF_REPORT_PHRASES = [
    "i slapped", "i hit him", "i hit her",
    "i pushed him", "i pushed her", "i shoved him", "i shoved her",
    "i grabbed him", "i grabbed her", "i struck him", "i struck her",
    "i punched him", "i punched her", "i kicked him", "i kicked her",
    "i yelled at him", "i yelled at her", "i screamed at him", "i screamed at her",
    "i threw something at", "i lost it with him", "i lost it with her",
    "i hurt him", "i hurt her", "i restrained him", "i restrained her"
]

MENTAL_EMERGENCY_PHRASES = [
    "wants to die", "want to die", "wants to end it", "end it all",
    "kill himself", "kill herself", "killing himself", "killing herself",
    "hurt himself", "hurt herself", "hurting himself", "hurting herself",
    "suicidal", "suicide", "taking his life", "taking her life",
    "no reason to live", "doesn't want to live", "doesn't want to be here",
    "not worth living", "better off dead", "better off without",
    "self-harm", "self harm"
]

PHYSICAL_EMERGENCY_PHRASES = [
    # falls
    "fell down the stairs", "fell down stairs", "fell down and",
    "fell and can't get up", "fell and cant get up",
    "can't get up", "cant get up", "fell hard", "took a fall",
    # not responding
    "not moving", "isn't moving", "wont move", "won't move",
    "not responding", "isn't responding", "no response",
    "not waking up", "won't wake up", "wont wake up",
    "unconscious", "unresponsive", "passed out", "blacked out",
    # breathing
    "not breathing", "stopped breathing", "isn't breathing", "can't breathe",
    # injury
    "spinal", "possible spinal", "head injury",
    "hit his head", "hit her head", "bleeding heavily",
    "heavy bleeding", "won't stop bleeding", "wont stop bleeding",
    # cardiac/medical
    "chest pain", "heart attack", "stroke", "seizure", "having a seizure",
    # ems
    "waiting for ems", "waiting for ambulance", "called 911", "called ems",
    "ems is coming", "ambulance is coming",
    # can't move
    "can't move him", "can't move her", "cant move him", "cant move her",
    "don't move him", "don't move her", "dont move him", "dont move her",
    "afraid to move", "scared to move",
    # overdose
    "overdose", "drug overdose",
    # self-harm with injury — physical AND mental, treat as physical emergency
    "slit his wrist", "slit her wrist", "slit his wrists", "slit her wrists",
    "cut his wrist", "cut her wrist", "cut his wrists", "cut her wrists",
    "cut himself", "cut herself", "cutting himself", "cutting herself",
    "stabbed himself", "stabbed herself", "shot himself", "shot herself",
    "hung himself", "hung herself", "hanging himself", "hanging herself",
    "tried to hang", "attempted suicide", "suicide attempt",
    "took too many pills", "took all his pills", "took all her pills",
    "swallowed too many", "swallowed a bottle"
]

EXTRACTION_RULES = {
    "sleep": {
        "concerning": [
            # caregiver reporting on veteran
            "didn't sleep", "couldn't sleep", "didn't get much sleep", "barely slept",
            "up all night", "was up all night", "awake all night", "up most of the night",
            "up at 2", "up at 3", "up at 4", "up at 1", "woke up at 2", "woke up at 3",
            "woke up at 4", "woke up at 1", "woke up screaming", "woke up yelling",
            "restless night", "bad night", "nightmare", "nightmares", "thrashing",
            "insomnia", "poor sleep", "not sleeping", "slept maybe", "slept only",
            "kept waking", "couldn't get him to sleep", "couldn't get her to sleep",
            "was up most", "no sleep"
        ],
        "positive": [
            "slept well", "slept through", "slept through the night", "good sleep",
            "good night", "rested", "full night", "got a full night", "stayed asleep",
            "slept about", "slept around"
        ],
        "neutral": [
            "sleep", "slept", "nap", "napping", "tired", "exhausted", "fatigue", "drowsy"
        ]
    },
    "mood": {
        "concerning": [
            # third person — caregiver describing veteran's mood
            "on edge", "seemed on edge", "was on edge",
            "anxious", "anxiety", "agitated", "seemed agitated", "was agitated",
            "angry", "got angry", "was angry", "irritable", "seemed irritable",
            "upset", "seemed upset", "was upset", "frustrated",
            "withdrawn", "very withdrawn", "seemed withdrawn",
            "paranoid", "seemed paranoid", "was paranoid",
            "depressed", "depression", "seemed depressed", "low mood",
            "not himself", "not herself", "not his usual self", "not her usual self",
            "distant", "seemed distant", "was distant",
            "aggressive", "got aggressive", "combative", "got combative",
            "was crying", "started crying", "cried",
            "breaking down", "had a breakdown",
            "overwhelmed", "seemed overwhelmed",
            "hypervigilant", "jumpy", "startled easily",
            "snapped at me", "snapped at", "lashed out", "shut down",
            "couldn't reach him", "couldn't reach her",
            "wouldn't respond", "wouldn't engage", "shut himself off", "shut herself off"
        ],
        "positive": [
            "calm", "was calm", "seemed calm", "happy", "seemed happy",
            "good mood", "in a good mood", "positive", "content", "relaxed",
            "cheerful", "laughed", "was laughing", "smiling", "upbeat",
            "in good spirits", "more like himself", "more like herself",
            "opened up", "engaged well"
        ],
        "neutral": [
            "mood", "emotional", "feelings", "seemed", "appeared"
        ]
    },
    "appetite": {
        "concerning": [
            "skipped meal", "didn't eat", "refused food", "refused to eat",
            "not eating", "no appetite", "barely ate", "wouldn't eat",
            "refusing to eat", "lost appetite", "skipped dinner", "skipped breakfast",
            "skipped lunch", "didn't finish", "pushed the plate away",
            "only ate a few bites", "ate very little", "didn't touch his food",
            "didn't touch her food"
        ],
        "positive": [
            "ate well", "good appetite", "ate everything", "ate a full",
            "finished his plate", "finished her plate", "enjoyed his meal",
            "enjoyed her meal", "good meal", "ate a full breakfast",
            "ate a full dinner", "ate a full lunch", "had a big meal"
        ],
        "neutral": [
            "ate", "meal", "food", "eating", "breakfast", "lunch", "dinner", "snack"
        ]
    },
    "medication": {
        "concerning": [
            "refused medication", "refused his medication", "refused her medication",
            "skipped medication", "forgot medication", "missed his dose", "missed her dose",
            "missed dose", "wouldn't take his meds", "wouldn't take her meds",
            "wouldn't take", "spit out", "refused meds", "skipped meds",
            "not taking his meds", "not taking her meds",
            "refused his meds", "refused her meds", "fought me on his meds",
            "fought me on her meds", "had to remind him", "had to remind her"
        ],
        "positive": [
            "took his medication", "took her medication", "took his meds", "took her meds",
            "medication on time", "no issues with meds", "took all his", "took all her",
            "no problems with meds", "took them without", "took it without"
        ],
        "neutral": [
            "medication", "meds", "pill", "pills", "prescription", "dose", "refill"
        ]
    },
    "appointments": {
        "concerning": [
            "missed his appointment", "missed her appointment", "missed the appointment",
            "skipped his appointment", "skipped her appointment",
            "refused to go", "wouldn't go", "cancelled his", "cancelled her",
            "no show", "didn't make it", "missed his pt", "missed her pt",
            "skipped pt", "skipped therapy", "missed therapy",
            "refused his appointment", "refused her appointment"
        ],
        "positive": [
            "went to his appointment", "went to her appointment",
            "made it to", "kept his appointment", "kept her appointment",
            "attended therapy", "went to therapy", "went to the va",
            "showed up", "completed his session", "completed her session"
        ],
        "neutral": [
            "appointment", "physical therapy", "pt appointment", "therapy",
            "doctor", "va ", "clinic", "session", "counseling", "check-up"
        ]
    },
    "social": {
        "concerning": [
            "isolated himself", "isolated herself", "isolating",
            "refused to talk", "wouldn't talk to anyone", "wouldn't come out",
            "stayed in his room", "stayed in her room", "stayed in the room",
            "avoiding everyone", "pushed me away", "pushed everyone away",
            "no contact with", "shut himself in", "shut herself in",
            "ignoring everyone", "wouldn't see anyone", "closed himself off",
            "closed herself off", "didn't want to be around anyone"
        ],
        "positive": [
            "talked with", "visited with", "had a visit", "called family",
            "spent time with", "had visitors", "engaged with",
            "connected with", "brightened up", "opened up to",
            "laughed with", "socialized"
        ],
        "neutral": [
            "family", "friends", "neighbor", "group", "community", "phone call", "visit"
        ]
    },
    "physical": {
        "concerning": [
            "pain", "fell", "fall", "injury", "hurt himself", "limping", "weak", "dizzy",
            "confused", "disoriented", "trembling", "shaking", "bleeding", "swelling",
            "chest pain", "difficulty breathing", "can't walk", "can't stand",
            "throwing up", "threw up", "vomiting", "vomit", "nausea", "nauseous",
            "sick to my stomach", "soiled", "bathroom accident", "not feeling well",
            "don't feel ok", "dont feel ok", "doesn't feel ok", "doesnt feel ok",
            "don't feel good", "dont feel good", "doesn't feel good", "doesnt feel good",
            "not feeling ok", "not feeling good", "not feeling well",
            "feel bad", "feeling bad", "feeling terrible", "feeling awful",
            "under the weather", "running a fever", "fever", "temperature"
        ],
        "positive": [
            "active", "walked", "exercised", "feeling better physically", "strong today",
            "feeling well", "feeling good physically"
        ],
        "neutral": [
            "physical", "body", "moving", "mobility", "walking", "standing", "health"
        ]
    },
    "behavior": {
        "concerning": [
            "wandering", "wandered", "flashback", "flashbacks", "triggered", "hypervigilant",
            "seeing things", "hearing things", "paranoid", "combative", "destructive",
            "threw", "screaming", "yelling at", "repetitive", "pacing"
        ],
        "positive": [
            "cooperative", "focused", "oriented", "clear headed", "calm and cooperative"
        ],
        "neutral": [
            "behavior", "acting", "trigger", "reaction", "response"
        ]
    }
}

def mock_extract(note_text):
    text_lower = note_text.lower()

    # Emergency check — always runs first, hard stop
    emergency = False
    emergency_phrase = None
    emergency_type = None

    for phrase in THIRD_PARTY_VIOLENCE_PHRASES:
        if phrase in text_lower:
            emergency = True
            emergency_phrase = phrase
            emergency_type = "third_party"
            break

    if not emergency:
        for phrase in CAREGIVER_SAFETY_PHRASES:
            if phrase in text_lower:
                emergency = True
                emergency_phrase = phrase
                emergency_type = "caregiver_safety"
                break

    if not emergency:
        for phrase in PHYSICAL_EMERGENCY_PHRASES:
            if phrase in text_lower:
                emergency = True
                emergency_phrase = phrase
                emergency_type = "physical"
                break

    if not emergency:
        for phrase in MENTAL_EMERGENCY_PHRASES:
            if phrase in text_lower:
                emergency = True
                emergency_phrase = phrase
                emergency_type = "mental"
                break

    # Self-report detection — silent log, no overlay
    self_report = False
    self_report_phrase = None
    for phrase in SELF_REPORT_PHRASES:
        if phrase in text_lower:
            self_report = True
            self_report_phrase = phrase
            break

    # Tag extraction
    tags = {}
    flags = []

    for category, rules in EXTRACTION_RULES.items():
        sentiment = None
        matched = None

        for phrase in rules.get("concerning", []):
            if phrase in text_lower:
                sentiment = "concerning"
                matched = phrase
                flags.append(f"{category}_concern")
                break

        if not sentiment:
            for phrase in rules.get("positive", []):
                if phrase in text_lower:
                    sentiment = "positive"
                    matched = phrase
                    break

        if not sentiment:
            for phrase in rules.get("neutral", []):
                if phrase in text_lower:
                    sentiment = "noted"
                    matched = phrase
                    break

        if sentiment:
            tags[category] = {"sentiment": sentiment, "matched": matched, "confirmed": True}

    concerning = [k for k, v in tags.items() if v["sentiment"] == "concerning"]
    positive   = [k for k, v in tags.items() if v["sentiment"] == "positive"]

    if emergency:
        note = "URGENT: Language detected that may indicate a crisis. See alert below."
    elif concerning:
        note = f"{len(concerning)} concern(s) noted: {', '.join(concerning)}."
    elif positive:
        note = f"Positive signs today: {', '.join(positive)}."
    elif tags:
        note = f"{len(tags)} topic(s) logged."
    else:
        note = "Nothing specific detected — see the follow-up question below."

    return {
        "tags": tags,
        "flags": flags,
        "emergency": emergency,
        "emergency_type": emergency_type,
        "emergency_phrase": emergency_phrase,
        "self_report": self_report,
        "self_report_phrase": self_report_phrase,
        "note": note,
        "sandbox": True
    }

def claude_extract(note_text):
    """
    Production extraction using Claude Haiku.
    Flip SANDBOX_MODE = False and implement this to go live.

    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": note_text}]
    )
    return parse_claude_response(response)
    """
    raise NotImplementedError("Set SANDBOX_MODE = False and implement Claude API call here.")

def extract_note(note_text):
    if SANDBOX_MODE:
        return mock_extract(note_text)
    return claude_extract(note_text)

# ── Drug Interaction Check (NIH RxNorm — free, no key) ────────────────────────

def check_drug_interactions(new_drug, existing_drugs):
    """Check interactions using FDA drug label database — free, no key required."""
    interactions = []
    seen_keys = set()
    try:
        for existing in existing_drugs:
            for primary, secondary in [(new_drug, existing), (existing, new_drug)]:
                key = tuple(sorted([primary.lower(), secondary.lower()]))
                if key in seen_keys:
                    continue
                url = (
                    f"https://api.fda.gov/drug/label.json"
                    f"?search=openfda.generic_name:\"{urllib.parse.quote(primary.lower())}\""
                    f"+AND+drug_interactions:\"{urllib.parse.quote(secondary.lower())}\""
                    f"&limit=1"
                )
                try:
                    with urllib.request.urlopen(url, timeout=6) as resp:
                        data = json.loads(resp.read())
                    results = data.get("results") or []
                    if not results:
                        continue
                    di_text = (results[0].get("drug_interactions") or [""])[0]
                    sentences = di_text.replace("\n", " ").split(". ")
                    relevant = [s.strip() for s in sentences if secondary.lower() in s.lower()]
                    if relevant:
                        seen_keys.add(key)
                        interactions.append({
                            "drugs": [primary.title(), secondary.title()],
                            "description": ". ".join(relevant[:2])[:400],
                            "severity": ""
                        })
                        break
                except Exception:
                    continue
    except Exception:
        pass
    return interactions

# ── AI Follow-up Question ──────────────────────────────────────────────────────

def generate_follow_up(tags, patient_name=None):
    name = patient_name or "they"
    concerns = [k for k, v in tags.items() if v.get("sentiment") == "concerning"]
    positives = [k for k, v in tags.items() if v.get("sentiment") == "positive"]

    if not tags:
        return random.choice([
            f"You mentioned things today — what stood out most?",
            f"Can you say more about how {name} seemed?",
            f"What was the most important thing that happened today?",
        ])

    priority = {
        "sleep":        f"That sounds like another rough night. Has the sleep disruption been affecting {name} during the day?",
        "medication":   f"When they refused medication, did they say why? Did they end up taking it later?",
        "mood":         f"You noted some mood concerns — did anything specific seem to trigger it, or did it come on gradually?",
        "behavior":     f"The behavior you described sounds difficult to manage. How are you holding up after today?",
        "physical":     f"You mentioned some physical symptoms — how is {name} feeling right now?",
        "appointments": f"When they missed the appointment, was that a refusal or did something else come up?",
        "appetite":     f"They didn't eat well today — have they had enough to drink? Fluids matter too.",
        "social":       f"The withdrawal you described — is this new, or has it been building over the past few days?",
    }
    for cat in ["sleep", "medication", "mood", "behavior", "physical", "appointments", "appetite", "social"]:
        if cat in concerns:
            return priority[cat]

    if positives and not concerns:
        return f"Sounds like a better day than usual. What do you think made the difference today?"

    return f"Is there anything else from today you want to make sure gets captured?"

# ── Pattern Detection ──────────────────────────────────────────────────────────

def detect_patterns(days=7, threshold=3):
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT extracted_tags FROM entries WHERE created_at >= ? AND is_emergency_flagged = 0",
        (cutoff,)
    ).fetchall()
    conn.close()

    counts = {}
    for row in rows:
        try:
            tags = json.loads(row["extracted_tags"] or "{}")
        except Exception:
            continue
        for cat, data in tags.items():
            if data.get("sentiment") == "concerning":
                counts[cat] = counts.get(cat, 0) + 1

    patterns = []
    label_map = {
        "sleep": "Sleep disruption",
        "mood": "Mood concerns",
        "appetite": "Appetite issues",
        "medication": "Medication refusal",
        "appointments": "Missed appointments",
        "social": "Social withdrawal",
        "physical": "Physical symptoms",
        "behavior": "Behavioral concerns"
    }
    for cat, count in counts.items():
        if count >= threshold:
            patterns.append({
                "category": cat,
                "label": label_map.get(cat, cat.title()),
                "count": count,
                "days": days,
                "threshold": threshold,
                "message": f"{label_map.get(cat, cat.title())} flagged {count} times in the last {days} days."
            })

    return sorted(patterns, key=lambda x: x["count"], reverse=True)

# ── Check-in Greeting ──────────────────────────────────────────────────────────

def build_checkin():
    patterns = detect_patterns(days=7, threshold=2)
    conn = get_db()
    has_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    patient_row = conn.execute("SELECT name FROM patients LIMIT 1").fetchone()
    conn.close()

    name = patient_row["name"] if patient_row else None
    they = name if name else "he/she"

    if not has_entries:
        greeting = f"Welcome. When you're ready, log how today went{' for ' + name if name else ''}."
        return {"greeting": greeting, "context": None}

    if patterns:
        top = patterns[0]
        greetings = {
            "sleep": f"You've mentioned sleep problems several times this week — how did last night go for {they}?",
            "mood": f"You've noted some mood concerns this week. How is {they} doing today?",
            "medication": f"There have been some medication challenges recently. Any updates today?",
            "appointments": f"A few appointments have been missed this week. How is scheduling going?",
            "appetite": f"Appetite has been a concern lately. Did {they} eat well today?",
            "behavior": f"You've flagged some behavior concerns this week. How is {they} today?",
            "social": f"Social withdrawal has come up a few times this week. Any change today?",
            "physical": f"You've noted some physical symptoms this week. How is {they} feeling today?"
        }
        msg = greetings.get(top["category"],
              f"You've had concerns about {top['label'].lower()} this week. How are things today?")
        return {"greeting": msg, "context": top}

    return {"greeting": f"Welcome back. How are things going today{' with ' + name if name else ''}?", "context": None}

# ── Summary Generator ──────────────────────────────────────────────────────────

def mock_generate_summary(days=14):
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT raw_note, extracted_tags, custom_tags, created_at, is_emergency_flagged FROM entries WHERE created_at >= ? ORDER BY created_at ASC",
        (cutoff,)
    ).fetchall()
    meds = conn.execute(
        "SELECT name, dosage, frequency, scheduled_time FROM medications WHERE is_active=1 ORDER BY name"
    ).fetchall()
    alert_rows = conn.execute(
        "SELECT alert_type, alert_message, created_at FROM alerts WHERE created_at >= ? AND alert_type NOT IN ('pattern') ORDER BY created_at DESC",
        (cutoff,)
    ).fetchall()
    patient  = conn.execute("SELECT name, is_veteran FROM patients LIMIT 1").fetchone()
    caregiver_row = conn.execute("SELECT name, relationship, caregiver_id FROM caregivers LIMIT 1").fetchone()
    conn.close()

    if not rows:
        return {"summary": "No entries found for the selected period.", "entries_reviewed": 0}

    total          = len(rows)
    concern_counts = {}
    positive_counts = {}
    custom_counts  = {}
    emergency_count = 0

    for row in rows:
        if row["is_emergency_flagged"]:
            emergency_count += 1
        try:
            for cat, data in json.loads(row["extracted_tags"] or "{}").items():
                if data.get("sentiment") == "concerning":
                    concern_counts[cat] = concern_counts.get(cat, 0) + 1
                elif data.get("sentiment") == "positive":
                    positive_counts[cat] = positive_counts.get(cat, 0) + 1
        except Exception:
            pass
        try:
            for t in json.loads(row["custom_tags"] or "[]"):
                custom_counts[t] = custom_counts.get(t, 0) + 1
        except Exception:
            pass

    first_date   = rows[0]["created_at"][:10]
    last_date    = rows[-1]["created_at"][:10]
    patient_name = patient["name"] if patient else "the patient"
    is_veteran   = bool(patient["is_veteran"]) if patient else False

    label_map = {
        "sleep":        "Sleep",
        "mood":         "Mood / Emotional State",
        "appetite":     "Appetite / Nutrition",
        "medication":   "Medication Adherence",
        "appointments": "Appointments",
        "social":       "Social Engagement",
        "physical":     "Physical Health",
        "behavior":     "Behavior"
    }

    lines = [
        "CAREGIVER OBSERVATION SUMMARY",
        "=" * 46,
        f"Patient:          {patient_name}{' (Veteran)' if is_veteran else ''}",
        f"Period:           {first_date} through {last_date}  ({days} days)",
        f"Total entries:    {total}",
        f"Emergency flags:  {emergency_count}",
        "",
        "CURRENT MEDICATIONS",
        "─" * 46,
    ]
    if meds:
        for m in meds:
            line = f"  • {m['name']}"
            if m["dosage"]:         line += f"  —  {m['dosage']}"
            if m["frequency"]:      line += f"  ({m['frequency']})"
            if m["scheduled_time"]: line += f"  @ {m['scheduled_time']}"
            lines.append(line)
    else:
        lines.append("  No medications on file.")

    lines += ["", "AREAS OF CONCERN", "─" * 46]
    if concern_counts:
        for cat, count in sorted(concern_counts.items(), key=lambda x: x[1], reverse=True):
            pct = round(count / total * 100)
            lines.append(f"  {label_map.get(cat, cat.title()):<28}  {count}/{total} entries  ({pct}%)")
    else:
        lines.append("  No recurring concerns flagged during this period.")

    lines += ["", "POSITIVE OBSERVATIONS", "─" * 46]
    if positive_counts:
        for cat, count in sorted(positive_counts.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {label_map.get(cat, cat.title()):<28}  noted positively in {count} entries")
    else:
        lines.append("  No specific positive observations recorded.")

    emergency_flags = [
        {
            "date": a["created_at"][:10],
            "message": a["alert_message"],
            "type": a["alert_type"]
        } for a in alert_rows
    ]

    custom_list = [
        {"name": k if isinstance(k, str) else k.get("name", ""), "count": v}
        for k, v in sorted(custom_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    concerns_list = [
        {"category": cat, "label": label_map.get(cat, cat.title()),
         "count": count, "total": total,
         "pct": round(count / total * 100)}
        for cat, count in sorted(concern_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    positives_list = [
        {"category": cat, "label": label_map.get(cat, cat.title()), "count": count}
        for cat, count in sorted(positive_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    meds_list = [
        {"name": m["name"], "dosage": m["dosage"],
         "frequency": m["frequency"], "scheduled_time": m["scheduled_time"]}
        for m in meds
    ]

    # Generate follow-up talking points for the appointment
    follow_ups = []
    med_names = [m["name"] for m in meds_list]
    med_str   = ", ".join(med_names) if med_names else "current medications"

    for c in concerns_list:
        cat, count, pct = c["category"], c["count"], c["pct"]
        if cat == "sleep" and count >= 3:
            follow_ups.append(f"Sleep was disrupted in {count} of {total} entries ({pct}%) — ask about sleep medication or a sleep study.")
        elif cat == "medication" and count >= 2:
            follow_ups.append(f"Medication was refused {count} times — ask the prescriber whether {med_str} may need adjustment or if side effects are a factor.")
        elif cat == "mood" and count >= 3:
            follow_ups.append(f"Mood concerns were logged {count} times ({pct}%) — ask about mental health support options or a referral.")
        elif cat == "physical" and count >= 2:
            follow_ups.append(f"Physical health concerns came up {count} times — request a physical assessment at this visit.")
        elif cat == "appointments" and count >= 2:
            follow_ups.append(f"Appointments were missed {count} times — discuss whether telehealth or scheduling support would help.")
        elif cat == "appetite" and count >= 3:
            follow_ups.append(f"Appetite concerns appeared in {count} entries — ask about a nutrition assessment.")
        elif cat == "behavior" and count >= 2:
            follow_ups.append(f"Behavioral concerns were noted {count} times — ask about a behavioral health evaluation.")

    for flag in emergency_flags:
        if flag["type"] == "physical":
            follow_ups.append(f"A fall or physical emergency was logged on {flag['date']} — ask about a fall risk assessment and home safety evaluation.")
        elif flag["type"] == "mental":
            follow_ups.append(f"A mental health crisis was logged on {flag['date']} — confirm the mental health provider is aware and follow up on crisis plan.")
        elif flag["type"] == "third_party":
            follow_ups.append(f"A violent incident was logged on {flag['date']} — discuss safety planning with the care team.")

    caregiver_info = None
    if caregiver_row:
        caregiver_info = {
            "name":         caregiver_row["name"],
            "relationship": caregiver_row["relationship"],
            "caregiver_id": caregiver_row["caregiver_id"]
        }

    return {
        "patient":   {"name": patient_name, "is_veteran": is_veteran},
        "caregiver": caregiver_info,
        "period":    {"start": first_date, "end": last_date, "days": days},
        "total_entries":    total,
        "emergency_count":  emergency_count,
        "medications":      meds_list,
        "concerns":         concerns_list,
        "positives":        positives_list,
        "emergency_flags":  emergency_flags,
        "custom_topics":    custom_list,
        "follow_ups":       follow_ups,
        "sandbox":          SANDBOX_MODE,
        "entries_reviewed": total,
        "date_range":       f"{first_date} to {last_date}"
    }

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", sandbox=SANDBOX_MODE)

@app.route("/api/patient", methods=["GET"])
def get_patient():
    conn = get_db()
    row = conn.execute("SELECT * FROM patients ORDER BY id LIMIT 1").fetchone()
    conn.close()
    if not row:
        return jsonify({"patient": None})
    return jsonify({"patient": {
        "id": row["id"],
        "name": row["name"],
        "is_veteran": bool(row["is_veteran"]),
        "local_crisis_number": row["local_crisis_number"]
    }})

@app.route("/api/patient", methods=["POST"])
def save_patient():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required."}), 400
    is_veteran = 1 if data.get("is_veteran") else 0
    local_crisis_number = (data.get("local_crisis_number") or "").strip() or None

    conn = get_db()
    existing = conn.execute("SELECT id FROM patients LIMIT 1").fetchone()
    if existing:
        conn.execute(
            "UPDATE patients SET name=?, is_veteran=?, local_crisis_number=? WHERE id=?",
            (name, is_veteran, local_crisis_number, existing["id"])
        )
    else:
        conn.execute(
            "INSERT INTO patients (name, is_veteran, local_crisis_number) VALUES (?,?,?)",
            (name, is_veteran, local_crisis_number)
        )
    conn.commit()
    conn.close()
    return jsonify({"success": True})

def _hash_pin(pin, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', pin.encode(), salt.encode(), 200_000)
    return f"{salt}:{key.hex()}"

def _verify_pin(pin, stored):
    try:
        salt, _ = stored.split(':', 1)
        return _hash_pin(pin, salt) == stored
    except Exception:
        return False

def _hash_answer(answer, salt=None):
    normalized = answer.strip().lower()
    if salt is None:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', normalized.encode(), salt.encode(), 200_000)
    return f"{salt}:{key.hex()}"

def _verify_answer(answer, stored):
    try:
        salt, _ = stored.split(':', 1)
        return _hash_answer(answer, salt) == stored
    except Exception:
        return False

# In-memory attempt trackers (single-user local app)
_pin_attempts      = {"count": 0, "locked_until": None}
_recovery_attempts = {"count": 0, "locked_until": None}

def _check_locked(tracker):
    lu = tracker["locked_until"]
    if lu and datetime.now() < lu:
        secs = int((lu - datetime.now()).total_seconds())
        return True, secs
    if lu and datetime.now() >= lu:
        tracker["count"] = 0
        tracker["locked_until"] = None
    return False, 0

def _recovery_locked():
    return _check_locked(_recovery_attempts)

@app.route("/api/pin/status", methods=["GET"])
def pin_status():
    conn = get_db()
    row = conn.execute("SELECT pin_hash, auto_lock_minutes FROM caregivers LIMIT 1").fetchone()
    conn.close()
    if not row or not row["pin_hash"]:
        return jsonify({"pin_set": False})
    return jsonify({"pin_set": True, "auto_lock_minutes": row["auto_lock_minutes"] or 15})

@app.route("/api/pin/set", methods=["POST"])
def set_pin():
    data = request.get_json()
    pin  = (data.get("pin") or "").strip()
    if not pin.isdigit() or len(pin) < 4:
        return jsonify({"error": "PIN must be at least 4 digits."}), 400
    auto_lock = int(data.get("auto_lock_minutes") or 15)
    hashed = _hash_pin(pin)
    conn = get_db()
    existing = conn.execute("SELECT id FROM caregivers LIMIT 1").fetchone()
    if existing:
        conn.execute("UPDATE caregivers SET pin_hash=?, auto_lock_minutes=? WHERE id=?",
                     (hashed, auto_lock, existing["id"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/pin/verify", methods=["POST"])
def verify_pin():
    locked, secs = _check_locked(_pin_attempts)
    if locked:
        return jsonify({"valid": False, "locked": True, "seconds": secs}), 429

    data = request.get_json()
    pin  = (data.get("pin") or "").strip()
    conn = get_db()
    row  = conn.execute("SELECT pin_hash FROM caregivers LIMIT 1").fetchone()
    conn.close()
    if not row or not row["pin_hash"]:
        return jsonify({"valid": True})

    if _verify_pin(pin, row["pin_hash"]):
        _pin_attempts["count"] = 0
        _pin_attempts["locked_until"] = None
        return jsonify({"valid": True})

    _pin_attempts["count"] += 1
    remaining = 5 - _pin_attempts["count"]
    if _pin_attempts["count"] >= 5:
        _pin_attempts["locked_until"] = datetime.now() + timedelta(minutes=5)
        return jsonify({"valid": False, "locked": True, "seconds": 300}), 429
    return jsonify({"valid": False, "remaining": remaining})

@app.route("/api/pin/question", methods=["GET"])
def get_recovery_question():
    conn = get_db()
    row  = conn.execute("SELECT security_question FROM caregivers LIMIT 1").fetchone()
    conn.close()
    if not row or not row["security_question"]:
        return jsonify({"question": None})
    return jsonify({"question": row["security_question"]})

@app.route("/api/pin/set-recovery", methods=["POST"])
def set_recovery():
    data     = request.get_json()
    question = (data.get("question") or "").strip()
    answer   = (data.get("answer") or "").strip()
    if not question or not answer:
        return jsonify({"error": "Question and answer are required."}), 400
    hashed = _hash_answer(answer)
    conn = get_db()
    existing = conn.execute("SELECT id FROM caregivers LIMIT 1").fetchone()
    if existing:
        conn.execute(
            "UPDATE caregivers SET security_question=?, security_answer_hash=? WHERE id=?",
            (question, hashed, existing["id"])
        )
        conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/pin/reset", methods=["POST"])
def reset_pin():
    locked, secs = _recovery_locked()
    if locked:
        return jsonify({"error": f"Too many attempts. Try again in {secs} seconds.", "locked": True, "seconds": secs}), 429

    data       = request.get_json()
    answer     = (data.get("answer") or "").strip()
    new_pin    = (data.get("new_pin") or "").strip()
    check_only = data.get("check_only", False)

    conn = get_db()
    row  = conn.execute("SELECT id, security_answer_hash FROM caregivers LIMIT 1").fetchone()
    conn.close()

    if not row or not row["security_answer_hash"]:
        return jsonify({"error": "No recovery question set."}), 400

    if not _verify_answer(answer, row["security_answer_hash"]):
        _recovery_attempts["count"] += 1
        remaining = 5 - _recovery_attempts["count"]
        if _recovery_attempts["count"] >= 5:
            _recovery_attempts["locked_until"] = datetime.now() + timedelta(minutes=5)
            return jsonify({"error": "Too many incorrect answers. Locked for 5 minutes.", "locked": True, "seconds": 300}), 429
        return jsonify({"valid": False, "remaining": remaining})

    # Answer is correct — reset attempt counter
    _recovery_attempts["count"] = 0
    _recovery_attempts["locked_until"] = None

    if check_only:
        return jsonify({"answer_valid": True})

    if not new_pin or not new_pin.isdigit() or len(new_pin) < 4:
        return jsonify({"error": "New PIN must be 4 digits."}), 400

    hashed = _hash_pin(new_pin)
    conn = get_db()
    conn.execute("UPDATE caregivers SET pin_hash=? WHERE id=?", (hashed, row["id"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/caregiver", methods=["GET"])
def get_caregiver():
    conn = get_db()
    row = conn.execute("SELECT * FROM caregivers LIMIT 1").fetchone()
    conn.close()
    if not row:
        return jsonify({"caregiver": None})
    return jsonify({"caregiver": {
        "id": row["id"],
        "name": row["name"],
        "relationship": row["relationship"],
        "caregiver_id": row["caregiver_id"]
    }})

@app.route("/api/caregiver", methods=["POST"])
def save_caregiver():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Caregiver name is required."}), 400
    relationship = (data.get("relationship") or "").strip() or None
    conn = get_db()
    existing = conn.execute("SELECT id, caregiver_id FROM caregivers LIMIT 1").fetchone()
    if existing:
        conn.execute(
            "UPDATE caregivers SET name=?, relationship=? WHERE id=?",
            (name, relationship, existing["id"])
        )
        cid = existing["caregiver_id"]
    else:
        cid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO caregivers (name, relationship, caregiver_id) VALUES (?,?,?)",
            (name, relationship, cid)
        )
    conn.commit()
    conn.close()
    return jsonify({"success": True, "caregiver_id": cid})

@app.route("/api/caregiver-checkin", methods=["POST"])
def save_caregiver_checkin():
    data    = request.get_json()
    entry_id = data.get("entry_id")
    response = (data.get("response") or "").strip()
    wanted_support = 1 if data.get("wanted_support") else 0
    if not response:
        return jsonify({"error": "Response required."}), 400
    conn = get_db()
    conn.execute(
        "INSERT INTO caregiver_checkins (entry_id, response, wanted_support) VALUES (?,?,?)",
        (entry_id, response, wanted_support)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/caregiver-rating", methods=["POST"])
def save_caregiver_rating():
    data = request.get_json()
    try:
        rating = int(data.get("rating"))
        if rating < 1 or rating > 5:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Rating must be 1–5"}), 400
    notes = (data.get("notes") or "").strip() or None
    conn = get_db()
    conn.execute("INSERT INTO caregiver_wellbeing (rating, notes) VALUES (?, ?)", (rating, notes))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/checkin", methods=["GET"])
def checkin():
    return jsonify(build_checkin())

@app.route("/api/entry", methods=["POST"])
def save_entry():
    data = request.get_json()
    note = (data.get("note") or "").strip()
    if not note:
        return jsonify({"error": "Note cannot be empty."}), 400

    extraction = extract_note(note)

    conn = get_db()
    patient_row = conn.execute("SELECT name FROM patients LIMIT 1").fetchone()
    patient_name = patient_row["name"] if patient_row else None

    cur = conn.execute(
        "INSERT INTO entries (raw_note, extracted_tags, is_emergency_flagged, emergency_phrase) VALUES (?, ?, ?, ?)",
        (note, json.dumps(extraction["tags"]),
         1 if extraction["emergency"] else 0,
         extraction.get("emergency_phrase"))
    )
    entry_id = cur.lastrowid

    if extraction["emergency"]:
        etype = extraction.get("emergency_type") or "emergency"
        conn.execute(
            "INSERT INTO alerts (entry_id, alert_type, alert_message) VALUES (?, ?, ?)",
            (entry_id, etype, f"Emergency language detected: \"{extraction['emergency_phrase']}\"")
        )

    if extraction.get("self_report"):
        conn.execute(
            "INSERT INTO alerts (entry_id, alert_type, alert_message) VALUES (?, 'incident', ?)",
            (entry_id, f"Self-reported incident logged: \"{extraction['self_report_phrase']}\"")
        )

    conn.commit()

    # Pattern alerts — only add if not already open
    patterns = detect_patterns()
    for p in patterns:
        exists = conn.execute(
            "SELECT id FROM alerts WHERE alert_type='pattern' AND alert_message LIKE ? AND deletion_status='locked'",
            (f"%{p['category']}%",)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO alerts (entry_id, alert_type, alert_message) VALUES (?, 'pattern', ?)",
                (entry_id, p["message"])
            )
    conn.commit()
    conn.close()

    follow_up = generate_follow_up(extraction["tags"], patient_name)
    return jsonify({"id": entry_id, "extraction": extraction, "patterns": patterns, "follow_up": follow_up})

@app.route("/api/entries", methods=["GET"])
def get_entries():
    limit  = int(request.args.get("limit", 20))
    offset = int(request.args.get("offset", 0))
    conn   = get_db()
    rows   = conn.execute(
        "SELECT id, created_at, raw_note, extracted_tags, corrected_tags, custom_tags, is_emergency_flagged, caregiver_rating FROM entries ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    conn.close()

    return jsonify({
        "entries": [{
            "id": r["id"],
            "created_at": r["created_at"],
            "raw_note": r["raw_note"],
            "tags": json.loads(r["extracted_tags"] or "{}"),
            "corrected_tags": json.loads(r["corrected_tags"]) if r["corrected_tags"] else None,
            "custom_tags": json.loads(r["custom_tags"] or "[]"),
            "is_emergency": bool(r["is_emergency_flagged"]),
            "caregiver_rating": r["caregiver_rating"]
        } for r in rows],
        "total": total
    })

@app.route("/api/entry/<int:entry_id>/correct", methods=["PUT"])
def correct_entry(entry_id):
    data = request.get_json()
    corrections = data.get("tags", {})
    conn = get_db()
    conn.execute("UPDATE entries SET corrected_tags = ? WHERE id = ?",
                 (json.dumps(corrections), entry_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/corrections/stats", methods=["GET"])
def correction_stats():
    conn  = get_db()
    total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    corrected = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE corrected_tags IS NOT NULL AND corrected_tags != 'null'"
    ).fetchone()[0]
    conn.close()
    return jsonify({"total_entries": total, "corrected": corrected,
                    "pct": round(corrected / total * 100) if total else 0})

@app.route("/api/patterns", methods=["GET"])
def get_patterns():
    days      = int(request.args.get("days", 7))
    threshold = int(request.args.get("threshold", 3))
    patterns  = detect_patterns(days, threshold)

    # Caregiver well-being trend — separate table, no patient data
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    conn   = get_db()
    rows   = conn.execute(
        "SELECT rating, notes, created_at FROM caregiver_wellbeing WHERE created_at >= ? ORDER BY created_at ASC",
        (cutoff,)
    ).fetchall()
    conn.close()

    wellbeing = None
    if rows:
        ratings = [r["rating"] for r in rows]
        avg     = round(sum(ratings) / len(ratings), 1)
        trend   = None
        if len(ratings) >= 4:
            first_half = sum(ratings[:len(ratings)//2]) / (len(ratings)//2)
            second_half = sum(ratings[len(ratings)//2:]) / (len(ratings) - len(ratings)//2)
            if second_half - first_half >= 0.5:
                trend = "improving"
            elif first_half - second_half >= 0.5:
                trend = "declining"
            else:
                trend = "stable"
        wellbeing = {
            "avg": avg,
            "count": len(ratings),
            "trend": trend,
            "ratings": [{"date": r["created_at"][:10], "rating": r["rating"], "notes": r["notes"]} for r in rows]
        }

    return jsonify({"patterns": patterns, "caregiver_wellbeing": wellbeing})

@app.route("/api/summary", methods=["POST"])
def generate_summary():
    data = request.get_json() or {}
    days = int(data.get("days", 14))
    return jsonify(mock_generate_summary(days))

_MED_LIST = None

def get_med_list():
    global _MED_LIST
    if _MED_LIST is None:
        path = os.path.join(os.path.dirname(__file__), "static", "medications.json")
        try:
            with open(path) as f:
                _MED_LIST = json.load(f)
        except Exception:
            _MED_LIST = []
    return _MED_LIST

@app.route("/api/medications/autocomplete", methods=["GET"])
def medication_autocomplete():
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return jsonify({"suggestions": []})

    med_list = get_med_list()
    results = []
    seen_lower = set()

    # 1. Exact prefix matches from local list (fast, offline, handles any spelling)
    for med in med_list:
        if med.lower().startswith(q):
            key = med.lower()
            if key not in seen_lower:
                seen_lower.add(key)
                results.append(med)
        if len(results) >= 6:
            break

    # 2. Substring matches from local list if prefix didn't fill 6
    if len(results) < 6:
        for med in med_list:
            if q in med.lower() and med.lower() not in seen_lower:
                seen_lower.add(med.lower())
                results.append(med)
            if len(results) >= 6:
                break

    # 3. Misspelling fallback — use first 3 chars as prefix against local list
    if len(results) < 3 and len(q) >= 3:
        prefix3 = q[:3]
        for med in med_list:
            if med.lower().startswith(prefix3) and med.lower() not in seen_lower:
                seen_lower.add(med.lower())
                results.append(med)
            if len(results) >= 6:
                break

    return jsonify({"suggestions": results[:6]})

@app.route("/api/medications", methods=["GET"])
def get_medications():
    conn = get_db()
    rows = conn.execute("SELECT * FROM medications WHERE is_active=1 ORDER BY name").fetchall()
    conn.close()
    return jsonify({"medications": [dict(r) for r in rows]})

@app.route("/api/medications", methods=["POST"])
def add_medication():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Medication name required."}), 400
    dosage         = (data.get("dosage") or "").strip() or None
    frequency      = (data.get("frequency") or "").strip() or None
    scheduled_time = (data.get("scheduled_time") or "").strip() or None
    notes          = (data.get("notes") or "").strip() or None

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO medications (name, dosage, frequency, scheduled_time, notes) VALUES (?,?,?,?,?)",
        (name, dosage, frequency, scheduled_time, notes)
    )
    med_id = cur.lastrowid
    conn.commit()
    existing = conn.execute(
        "SELECT name FROM medications WHERE is_active=1 AND id != ?", (med_id,)
    ).fetchall()
    conn.close()

    interactions = check_drug_interactions(name, [r["name"] for r in existing]) if existing else []
    return jsonify({"success": True, "id": med_id, "interactions": interactions})

@app.route("/api/medications/<int:med_id>", methods=["PUT"])
def update_medication(med_id):
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Medication name required."}), 400
    conn = get_db()
    conn.execute(
        "UPDATE medications SET name=?, dosage=?, frequency=?, scheduled_time=?, notes=? WHERE id=?",
        (name, data.get("dosage"), data.get("frequency"), data.get("scheduled_time"), data.get("notes"), med_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/medications/<int:med_id>", methods=["DELETE"])
def remove_medication(med_id):
    conn = get_db()
    conn.execute("UPDATE medications SET is_active=0 WHERE id=?", (med_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/entry/<int:entry_id>/custom-topics", methods=["POST"])
def add_custom_topic(entry_id):
    data   = request.get_json()
    topic  = (data.get("topic") or "").strip()
    detail = (data.get("detail") or "").strip() or None
    if not topic:
        return jsonify({"error": "Topic required."}), 400
    conn = get_db()
    row  = conn.execute("SELECT custom_tags FROM entries WHERE id=?", (entry_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Entry not found."}), 404
    existing = json.loads(row["custom_tags"] or "[]")
    entry = {"name": topic, "detail": detail} if detail else topic
    existing.append(entry)
    conn.execute("UPDATE entries SET custom_tags=? WHERE id=?", (json.dumps(existing), entry_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "custom_tags": existing})

@app.route("/api/entry/<int:entry_id>/custom-topics", methods=["PUT"])
def replace_custom_topics(entry_id):
    data = request.get_json()
    custom_tags = data.get("custom_tags", [])
    conn = get_db()
    conn.execute("UPDATE entries SET custom_tags=? WHERE id=?", (json.dumps(custom_tags), entry_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "custom_tags": custom_tags})

@app.route("/api/custom-topics/suggestions", methods=["GET"])
def topic_suggestions():
    conn = get_db()
    rows = conn.execute(
        "SELECT custom_tags FROM entries WHERE custom_tags IS NOT NULL AND custom_tags != '[]'"
    ).fetchall()
    conn.close()
    counts = {}
    for row in rows:
        try:
            for t in json.loads(row["custom_tags"]):
                name = t["name"] if isinstance(t, dict) else t
                counts[name] = counts.get(name, 0) + 1
        except Exception:
            pass
    return jsonify({"suggestions": [t for t, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:20]]})

@app.route("/api/alerts", methods=["GET"])
def get_alerts():
    date_filter = request.args.get("date", "").strip()
    type_filter = request.args.get("type", "").strip()
    conn = get_db()

    where_clauses = []
    params = []
    if date_filter:
        where_clauses.append("a.created_at LIKE ?")
        params.append(date_filter + "%")
    if type_filter:
        where_clauses.append("a.alert_type = ?")
        params.append(type_filter)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    rows = conn.execute(
        f"""SELECT a.id, a.created_at, a.alert_type, a.alert_message,
                  a.deletion_status, a.entry_id, e.created_at as entry_date
           FROM alerts a LEFT JOIN entries e ON a.entry_id = e.id
           {where_sql}
           ORDER BY a.created_at DESC""",
        params
    ).fetchall()

    total = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    count_rows = conn.execute(
        "SELECT alert_type, COUNT(*) as n FROM alerts GROUP BY alert_type"
    ).fetchall()
    counts = {r["alert_type"]: r["n"] for r in count_rows}
    conn.close()

    return jsonify({
        "alerts": [{
            "id": r["id"], "created_at": r["created_at"],
            "alert_type": r["alert_type"], "alert_message": r["alert_message"],
            "deletion_status": r["deletion_status"],
            "entry_id": r["entry_id"], "entry_date": r["entry_date"]
        } for r in rows],
        "total": total,
        "counts": counts
    })

@app.route("/api/alerts/<int:alert_id>/delete-request", methods=["POST"])
def request_deletion(alert_id):
    data       = request.get_json() or {}
    requester  = data.get("requested_by", "caregiver")
    reason     = data.get("reason", "")
    conn = get_db()
    # Always log the attempt — this record itself cannot be deleted
    conn.execute(
        "INSERT INTO deletion_audit (alert_id, requested_by, reason, status) VALUES (?, ?, ?, 'denied')",
        (alert_id, requester, reason)
    )
    conn.commit()
    conn.close()
    return jsonify({
        "success": False,
        "locked": True,
        "message": "This record is locked. Deletion requires agreement from multiple authorized parties. Your request has been permanently logged."
    })

@app.route("/api/seed", methods=["POST"])
def seed_data():
    """Load realistic sample entries for demo/testing. Only available in sandbox mode."""
    if not SANDBOX_MODE:
        return jsonify({"error": "Seed only available in sandbox mode."}), 403

    from datetime import datetime, timedelta
    today = datetime.now()
    def dts(days_ago, hour=20, minute=0):
        d = today - timedelta(days=days_ago)
        return d.strftime(f"%Y-%m-%d {hour:02d}:{minute:02d}:00")

    sample_notes = [
        (dts(13, 20, 14), "He didn't sleep again last night, maybe two hours at most. Seemed on edge all morning. Refused his medication at breakfast and wouldn't say why. Ate a little at dinner but picked at it."),
        (dts(12, 21,  2), "Better day today. Slept through the night which hasn't happened in a while. Took his medication without any issues. Good appetite at lunch and dinner. Seemed more relaxed, even sat outside for a bit."),
        (dts(11, 20, 45), "Mood was low all day. Didn't want to talk, stayed in his room most of the morning. Skipped his PT appointment — said he didn't feel up to it. Ate a full dinner though."),
        (dts(10, 21, 30), "Rough night again, kept waking up. Seemed on edge and irritable this morning, snapped at me when I brought his medication. Eventually took it but it took about 20 minutes. Missed lunch, ate dinner."),
        (dts( 9, 20, 10), "He complained of pain in his lower back, said it has been building for a few days. Walked slowly, seemed uncomfortable. Took his meds on time. Ate well. Called the VA to schedule a follow-up."),
        (dts( 8, 21, 15), "Good day overall. Slept well, woke up on his own around 8. In a good mood, talked more than usual. Kept his PT appointment and came back saying it went well. Ate everything at dinner."),
        (dts( 7, 20, 55), "Didn't sleep much. Withdrew most of the day, wouldn't come out of his room for lunch. Refused his meds in the morning and again at night. Seemed distant, couldn't reach him when I tried to talk."),
        (dts( 6, 21, 40), "Woke up agitated. During lunch he said he doesn't want to be here anymore and that things aren't going to get better. I stayed with him and called the VA crisis line after."),
        (dts( 5, 20, 30), "Quiet day after yesterday. He was calmer but still withdrawn. Took his medication without a fight, which was good. Didn't eat much. The VA called back to check in and he talked to them briefly."),
        (dts( 4, 21,  0), "Noticeably better today. Kept his PT appointment, first time in two weeks. Seemed lighter when he got back. Good appetite. Slept well last night. Had a phone call with his brother."),
        (dts( 3, 20, 20), "Sleep was bad again, restless night. Mood was low in the morning. Took his meds but complained about them. Ate breakfast, skipped lunch. Seemed to stabilize by evening."),
        (dts( 2, 21, 10), "Refused his medication again this morning, said they make him feel foggy. Missed his VA appointment, said he forgot. Appetite okay at dinner. Mood flat but not agitated."),
        (dts( 1, 20, 50), "He took a fall getting out of the shower this morning and hit his head on the towel bar. Seemed okay, no loss of consciousness, but I watched him closely all day. Took his meds. Ate well. Called the nurse line to report it."),
        (dts( 0, 20,  0), "Slept about five hours, better than the last few nights. Mood was okay this morning. Took his medication with breakfast without any issues. Ate a full lunch. PT appointment is tomorrow and he said he plans to go."),
    ]

    conn = get_db()
    inserted = 0
    for created_at, note in sample_notes:
        already = conn.execute(
            "SELECT id FROM entries WHERE raw_note = ?", (note,)
        ).fetchone()
        if already:
            continue
        extraction = extract_note(note)
        cur = conn.execute(
            "INSERT INTO entries (created_at, raw_note, extracted_tags, is_emergency_flagged, emergency_phrase) VALUES (?, ?, ?, ?, ?)",
            (created_at, note, json.dumps(extraction["tags"]),
             1 if extraction["emergency"] else 0,
             extraction.get("emergency_phrase"))
        )
        entry_id = cur.lastrowid
        if extraction["emergency"]:
            etype = extraction.get("emergency_type") or "emergency"
            conn.execute(
                "INSERT INTO alerts (created_at, entry_id, alert_type, alert_message) VALUES (?, ?, ?, ?)",
                (created_at, entry_id, etype, f"Emergency language detected: \"{extraction['emergency_phrase']}\"")
            )
        inserted += 1

    conn.commit()  # must commit before detect_patterns opens its own connection

    # Add pattern alerts for the seed data
    patterns = detect_patterns()
    for p in patterns:
        exists = conn.execute(
            "SELECT id FROM alerts WHERE alert_type='pattern' AND alert_message LIKE ?",
            (f"%{p['category']}%",)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO alerts (alert_type, alert_message) VALUES ('pattern', ?)",
                (p["message"],)
            )

    conn.commit()
    conn.close()
    return jsonify({"inserted": inserted, "message": f"Loaded {inserted} sample entries."})

# ── Run ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    migrate_db()
    print()
    print("  CareLog — Caregiver AI Sandbox")
    print("  --------------------------------")
    print("  Running at:  http://localhost:5050")
    print("  Mode:        SANDBOX (AI calls simulated, no API key needed)")
    print("  Database:    caregiver.db (local SQLite)")
    print()
    app.run(debug=True, port=5050)
