from flask import Flask, request, jsonify, render_template, send_file
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
import io

app = Flask(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

SANDBOX_MODE = os.environ.get("SANDBOX_MODE", "true").lower() != "false"
_db_default  = os.path.join(os.path.dirname(__file__), "caregiver.db")
DB_PATH      = os.environ.get("DB_PATH", _db_default)

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
    audit_cols = [row[1] for row in conn.execute("PRAGMA table_info(deletion_audit)").fetchall()]
    if "confirm_code" not in audit_cols:
        conn.execute("ALTER TABLE deletion_audit ADD COLUMN confirm_code TEXT DEFAULT NULL")
        conn.commit()
    if "note_type" not in entry_cols:
        conn.execute("ALTER TABLE entries ADD COLUMN note_type TEXT DEFAULT 'observation'")
        conn.commit()
    patient_cols = [row[1] for row in conn.execute("PRAGMA table_info(patients)").fetchall()]
    if "patient_language" not in patient_cols:
        conn.execute("ALTER TABLE patients ADD COLUMN patient_language TEXT DEFAULT NULL")
        conn.commit()
    if "conditions" not in patient_cols:
        conn.execute("ALTER TABLE patients ADD COLUMN conditions TEXT DEFAULT NULL")
        conn.commit()
    alert_cols2 = [row[1] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()]
    if "is_deleted" not in alert_cols2:
        conn.execute("ALTER TABLE alerts ADD COLUMN is_deleted INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE alerts ADD COLUMN deleted_at TEXT DEFAULT NULL")
        conn.commit()
    vp_tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='voice_profiles'").fetchone()
    if not vp_tables:
        conn.execute("""CREATE TABLE voice_profiles (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at        TEXT DEFAULT (datetime('now','localtime')),
            caregiver_id      TEXT NOT NULL,
            phrase_text       TEXT,
            pitch_mean        REAL DEFAULT 0,
            pitch_std         REAL DEFAULT 0,
            energy_mean       REAL DEFAULT 0,
            spectral_centroid REAL DEFAULT 0,
            freq_profile      TEXT DEFAULT NULL
        )""")
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
    # third-person — caregiver observing
    "wants to die", "want to die", "wants to end it", "end it all",
    "kill himself", "kill herself", "killing himself", "killing herself",
    "hurt himself", "hurt herself", "hurting himself", "hurting herself",
    "suicidal", "suicide", "taking his life", "taking her life",
    "no reason to live", "doesn't want to live", "doesn't want to be here",
    "not worth living", "better off dead", "better off without",
    "self-harm", "self harm",
    # first-person — patient speaking directly (translator use case)
    "kill myself", "killing myself", "want to kill myself", "going to kill myself",
    "hurt myself", "hurting myself", "want to hurt myself",
    "end my life", "take my life", "take my own life", "going to end my life",
    "i want to die", "i don't want to live", "i do not want to live",
    "i don't want to be here", "i do not want to be here",
    "i don't want to be alive", "i want to be dead",
    "no point in living", "no reason to go on", "nothing to live for",
    "going to end it", "planning to end it",
    # bridge / jumping — explicit suicidal method
    "jump off the bridge", "jump off a bridge", "jump from the bridge", "jump from a bridge",
    "jumping off the bridge", "jumping off a bridge", "jumping from the bridge",
    "jump off the roof", "jump off a roof", "jump off a building", "jump off the building",
    "jump head first", "head first off the bridge", "head first off a bridge",
    "jumper from bridge", "off the bridge head first",
    "going to jump", "going to jump off", "planning to jump",
    "throw myself off", "throw myself from",
    # coded / indirect
    "not going to be around", "won't be around much longer", "wont be around much longer",
    "goodbye forever", "last goodbye", "no one will miss me",
    "can't go on", "cant go on", "can't do this anymore", "cant do this anymore",
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
    # overdose — third-person and first-person
    "overdose", "drug overdose",
    "took too many pills", "took all his pills", "took all her pills",
    "took all my pills", "took too many of my", "i took too many",
    "swallowed too many", "swallowed a bottle", "swallowed all my",
    "took an overdose", "i took an overdose", "took in overdose",
    # self-harm with injury — physical AND mental, treat as physical emergency
    "slit his wrist", "slit her wrist", "slit his wrists", "slit her wrists",
    "slit my wrist", "slit my wrists",
    "cut his wrist", "cut her wrist", "cut his wrists", "cut her wrists",
    "cut my wrist", "cut my wrists",
    "cut himself", "cut herself", "cutting himself", "cutting herself",
    "cut myself", "cutting myself",
    "stabbed himself", "stabbed herself", "shot himself", "shot herself",
    "stabbed myself", "shot myself",
    "hung himself", "hung herself", "hanging himself", "hanging herself",
    "hung myself", "hanging myself",
    "tried to hang", "attempted suicide", "suicide attempt",
]

EXTRACTION_RULES = {
    "sleep": {
        "concerning": [
            "didn't sleep", "couldn't sleep", "didn't get much sleep", "barely slept",
            "up all night", "was up all night", "awake all night", "up most of the night",
            "up at 2", "up at 3", "up at 4", "up at 1", "woke up at 2", "woke up at 3",
            "woke up at 4", "woke up at 1", "woke up screaming", "woke up yelling",
            "restless night", "bad night", "nightmare", "nightmares", "thrashing",
            "insomnia", "poor sleep", "not sleeping", "slept maybe", "slept only",
            "kept waking", "couldn't get him to sleep", "couldn't get her to sleep",
            "was up most", "no sleep",
            # PTSD-specific
            "night sweats", "woke up drenched", "soaked the sheets", "soaked the bed",
            "woke up in a sweat", "drenched in sweat",
            # depression-specific (opposite direction — oversleeping)
            "sleeping all day", "slept all day", "can't get out of bed", "won't get out of bed",
            "wouldn't get up", "stayed in bed all day", "in bed all day"
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
            "wouldn't respond", "wouldn't engage", "shut himself off", "shut herself off",
            # veteran-specific
            "got triggered", "something triggered him", "something triggered her",
            "triggered today", "flat affect", "no expression", "emotionless",
            "just staring", "tearful", "weeping quietly", "staring at the wall"
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
        n = len(concerning)
        note = f"{n} concern{'s' if n > 1 else ''} noted: {', '.join(concerning)}."
    elif positive:
        note = f"Positive signs today: {', '.join(positive)}."
    elif tags:
        note = ""
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
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": note_text}]
    )
    raw = response.content[0].text if response.content else "{}"
    return parse_claude_response(raw)

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
        "SELECT DATE(created_at) AS day, extracted_tags FROM entries WHERE created_at >= ? AND is_emergency_flagged = 0",
        (cutoff,)
    ).fetchall()
    conn.close()

    counts = {}
    dates  = {}
    for row in rows:
        try:
            tags = json.loads(row["extracted_tags"] or "{}")
        except Exception:
            continue
        for cat, data in tags.items():
            if data.get("sentiment") == "concerning":
                counts[cat] = counts.get(cat, 0) + 1
                dates.setdefault(cat, set()).add(row["day"])

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
    patterns = []
    for cat, count in counts.items():
        if count >= threshold:
            patterns.append({
                "category": cat,
                "label": label_map.get(cat, cat.title()),
                "count": count,
                "days": days,
                "threshold": threshold,
                "dates": sorted(dates.get(cat, [])),
                "message": f"{label_map.get(cat, cat.title())} flagged {count} times in the last {days} days."
            })

    return sorted(patterns, key=lambda x: x["count"], reverse=True)

# ── Check-in Greeting ──────────────────────────────────────────────────────────

def build_checkin():
    patterns = detect_patterns(days=7, threshold=2)
    conn = get_db()
    has_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    patient_row = conn.execute("SELECT name FROM patients LIMIT 1").fetchone()
    recent_ratings = conn.execute(
        "SELECT rating FROM caregiver_wellbeing ORDER BY created_at DESC LIMIT 3"
    ).fetchall()
    conn.close()

    name = patient_row["name"] if patient_row else None
    they = name if name else "he/she"

    caregiver_note = None
    if recent_ratings:
        low_count = sum(1 for r in recent_ratings if r["rating"] <= 2)
        if low_count >= 2:
            caregiver_note = "You've been rating yourself low for a few days. How are you holding up today?"
        elif recent_ratings[0]["rating"] <= 2:
            caregiver_note = "You had a hard day yesterday. Checking in on you too — not just the patient."

    if not has_entries:
        greeting = f"Welcome. When you're ready, log how today went{' for ' + name if name else ''}."
        return {"greeting": greeting, "context": None, "caregiver_note": caregiver_note}

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
        return {"greeting": msg, "context": top, "caregiver_note": caregiver_note}

    return {"greeting": f"Welcome back. How are things going today{' with ' + name if name else ''}?", "context": None, "caregiver_note": caregiver_note}

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
    conn2 = get_db()
    first_entry = conn2.execute("SELECT MIN(DATE(created_at)) as d FROM entries").fetchone()["d"]
    total_entries = conn2.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    last_entry = conn2.execute("SELECT MAX(DATE(created_at)) as d FROM entries").fetchone()["d"]
    alert_counts = {r["alert_type"]: r["n"] for r in conn2.execute(
        "SELECT alert_type, COUNT(*) as n FROM alerts WHERE is_deleted=0 OR is_deleted IS NULL GROUP BY alert_type"
    ).fetchall()}
    caregiver = conn2.execute("SELECT name, relationship FROM caregivers ORDER BY id LIMIT 1").fetchone()
    active_meds = conn2.execute(
        "SELECT name, dosage, frequency, scheduled_time, notes FROM medications WHERE is_active=1 ORDER BY name"
    ).fetchall()
    conn2.close()

    from datetime import date
    days_in_care = (date.today() - date.fromisoformat(first_entry)).days + 1 if first_entry else 0

    return jsonify({"patient": {
        "id":                   row["id"],
        "name":                 row["name"],
        "is_veteran":           bool(row["is_veteran"]),
        "local_crisis_number":  row["local_crisis_number"],
        "patient_language":     row["patient_language"],
        "conditions":           row["conditions"],
        "first_entry":          first_entry,
        "last_entry":           last_entry,
        "days_in_care":         days_in_care,
        "total_entries":        total_entries,
        "alert_counts":         alert_counts,
        "caregiver_name":       caregiver["name"] if caregiver else None,
        "caregiver_relationship": caregiver["relationship"] if caregiver else None,
        "active_medications":   [dict(m) for m in active_meds],
    }})

@app.route("/api/patient", methods=["POST"])
def save_patient():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required."}), 400
    is_veteran = 1 if data.get("is_veteran") else 0
    local_crisis_number = (data.get("local_crisis_number") or "").strip() or None
    patient_language = (data.get("patient_language") or "").strip() or None
    conditions = (data.get("conditions") or "").strip() or None

    conn = get_db()
    existing = conn.execute("SELECT id FROM patients LIMIT 1").fetchone()
    if existing:
        conn.execute(
            "UPDATE patients SET name=?, is_veteran=?, local_crisis_number=?, patient_language=?, conditions=? WHERE id=?",
            (name, is_veteran, local_crisis_number, patient_language, conditions, existing["id"])
        )
    else:
        conn.execute(
            "INSERT INTO patients (name, is_veteran, local_crisis_number, patient_language, conditions) VALUES (?,?,?,?,?)",
            (name, is_veteran, local_crisis_number, patient_language, conditions)
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

    note_type = data.get("note_type", "observation")
    extraction = extract_note(note)

    conn = get_db()
    patient_row = conn.execute("SELECT name FROM patients LIMIT 1").fetchone()
    patient_name = patient_row["name"] if patient_row else None

    cur = conn.execute(
        "INSERT INTO entries (raw_note, extracted_tags, is_emergency_flagged, emergency_phrase, note_type) VALUES (?, ?, ?, ?, ?)",
        (note, json.dumps(extraction["tags"]),
         1 if extraction["emergency"] else 0,
         extraction.get("emergency_phrase"),
         note_type)
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

@app.route("/api/entries/dates", methods=["GET"])
def get_entry_dates():
    """Return all dates that have entries with summary metadata."""
    conn = get_db()
    rows = conn.execute("""
        SELECT DATE(e.created_at) AS day,
               COUNT(DISTINCT e.id) AS entry_count,
               MAX(e.is_emergency_flagged) AS has_emergency,
               SUM(CASE WHEN e.note_type='translation' THEN 1 ELSE 0 END) AS has_translation,
               COALESCE((
                 SELECT 1 FROM alerts a
                 WHERE DATE(a.created_at) = DATE(e.created_at)
                   AND a.alert_type='pattern'
                   AND a.is_deleted=0
                 LIMIT 1
               ), 0) AS has_pattern
        FROM entries e
        GROUP BY DATE(e.created_at)
        ORDER BY day
    """).fetchall()
    conn.close()
    return jsonify([{
        "date":            r["day"],
        "count":           r["entry_count"],
        "has_emergency":   bool(r["has_emergency"]),
        "has_translation": bool(r["has_translation"]),
        "has_pattern":     bool(r["has_pattern"])
    } for r in rows])

@app.route("/api/entries", methods=["GET"])
def get_entries():
    conn  = get_db()
    dates_param = request.args.get("dates")
    SEL = "SELECT id, created_at, raw_note, extracted_tags, corrected_tags, custom_tags, is_emergency_flagged, caregiver_rating, note_type FROM entries"

    if dates_param:
        dates = [d.strip() for d in dates_param.split(",") if d.strip()]
        placeholders = ",".join("?" * len(dates))
        rows  = conn.execute(f"{SEL} WHERE DATE(created_at) IN ({placeholders}) ORDER BY created_at ASC", dates).fetchall()
        total = len(rows)
    else:
        limit  = int(request.args.get("limit", 20))
        offset = int(request.args.get("offset", 0))
        rows   = conn.execute(f"{SEL} ORDER BY created_at ASC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        total  = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

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
            "caregiver_rating": r["caregiver_rating"],
            "note_type": r["note_type"] or "observation"
        } for r in rows],
        "total": total
    })

@app.route("/api/entry/<int:entry_id>/update-note", methods=["PUT"])
def update_entry_note(entry_id):
    data = request.get_json()
    note = (data.get("note") or "").strip()
    if not note:
        return jsonify({"error": "Note required"}), 400
    conn = get_db()
    conn.execute("UPDATE entries SET raw_note = ? WHERE id = ?", (note, entry_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/detect-emergency", methods=["POST"])
def detect_emergency_text():
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"emergency": False})
    result = extract_note(text)
    return jsonify({
        "emergency": bool(result.get("emergency")),
        "emergency_type": result.get("emergency_type"),
        "emergency_phrase": result.get("emergency_phrase"),
    })

@app.route("/api/entry/<int:entry_id>/flag-emergency", methods=["POST"])
def flag_emergency_entry(entry_id):
    data   = request.get_json() or {}
    etype  = (data.get("emergency_type") or "mental")
    phrase = (data.get("emergency_phrase") or "")
    conn   = get_db()
    conn.execute(
        "UPDATE entries SET is_emergency_flagged=1, emergency_phrase=? WHERE id=?",
        (phrase, entry_id)
    )
    msg = f"Emergency language detected in translation: \"{phrase}\""
    conn.execute(
        "INSERT INTO alerts (entry_id, alert_type, alert_message) VALUES (?, ?, ?)",
        (entry_id, etype, msg)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})

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

    where_clauses = ["(a.is_deleted=0 OR a.is_deleted IS NULL)"]
    params = []
    if date_filter:
        where_clauses.append("a.created_at LIKE ?")
        params.append(date_filter + "%")
    if type_filter:
        where_clauses.append("a.alert_type = ?")
        params.append(type_filter)
    where_sql = "WHERE " + " AND ".join(where_clauses)

    rows = conn.execute(
        f"""SELECT a.id, a.created_at, a.alert_type, a.alert_message,
                  a.deletion_status, a.entry_id, e.created_at as entry_date
           FROM alerts a LEFT JOIN entries e ON a.entry_id = e.id
           {where_sql}
           ORDER BY a.created_at DESC""",
        params
    ).fetchall()

    total = conn.execute("SELECT COUNT(*) FROM alerts WHERE is_deleted=0 OR is_deleted IS NULL").fetchone()[0]
    count_rows = conn.execute(
        "SELECT alert_type, COUNT(*) as n FROM alerts WHERE is_deleted=0 OR is_deleted IS NULL GROUP BY alert_type"
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
    data      = request.get_json() or {}
    requester = data.get("requested_by", "caregiver")
    reason    = (data.get("reason") or "").strip()
    if not reason:
        return jsonify({"error": "A reason is required."}), 400
    conn = get_db()
    alert = conn.execute("SELECT id FROM alerts WHERE id=? AND (is_deleted=0 OR is_deleted IS NULL)", (alert_id,)).fetchone()
    if not alert:
        conn.close()
        return jsonify({"error": "Alert not found."}), 404
    code = secrets.token_hex(3).upper()
    conn.execute(
        "INSERT INTO deletion_audit (alert_id, requested_by, reason, status, confirm_code) VALUES (?, ?, ?, 'pending', ?)",
        (alert_id, requester, reason, code)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True, "confirm_code": code})

@app.route("/api/alerts/<int:alert_id>/delete-confirm", methods=["POST"])
def confirm_deletion(alert_id):
    data = request.get_json() or {}
    code = (data.get("confirm_code") or "").strip().upper()
    pin  = (data.get("pin") or "").strip()
    if not code or not pin:
        return jsonify({"error": "Code and PIN are required."}), 400
    conn = get_db()
    cg = conn.execute("SELECT pin_hash FROM caregivers LIMIT 1").fetchone()
    if not cg or not cg["pin_hash"] or not _verify_pin(pin, cg["pin_hash"]):
        conn.close()
        return jsonify({"error": "Incorrect PIN."}), 403
    audit = conn.execute(
        "SELECT id FROM deletion_audit WHERE alert_id=? AND confirm_code=? AND status='pending'",
        (alert_id, code)
    ).fetchone()
    if not audit:
        conn.close()
        return jsonify({"error": "Invalid code or no pending request found for this alert."}), 404
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE deletion_audit SET status='approved' WHERE id=?", (audit["id"],))
    conn.execute("UPDATE alerts SET is_deleted=1, deleted_at=? WHERE id=?", (now, alert_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/deletion-requests", methods=["GET"])
def get_deletion_requests():
    conn = get_db()
    rows = conn.execute("""
        SELECT da.id, da.created_at, da.alert_id, da.requested_by, da.reason, da.status,
               a.alert_type, a.alert_message
        FROM deletion_audit da
        LEFT JOIN alerts a ON da.alert_id = a.id
        ORDER BY da.created_at DESC
    """).fetchall()
    conn.close()
    return jsonify({"requests": [dict(r) for r in rows]})

@app.route("/api/seed", methods=["GET", "POST"])
def seed_data():
    """Load 120-day realistic sample data with pattern waves, crises, and violence. Sandbox only."""
    if not SANDBOX_MODE:
        return jsonify({"error": "Seed only available in sandbox mode."}), 403

    from datetime import datetime, timedelta
    today = datetime.now()

    def dts(days_ago, hour=20, minute=0):
        d = today - timedelta(days=days_ago)
        return d.strftime(f"%Y-%m-%d {hour:02d}:{minute:02d}:00")

    # ── 120-DAY ARC ─────────────────────────────────────────────────────────────
    # Robert (veteran, PTSD, chronic back pain) cared for by Jimmy.
    # Four pattern waves, two MH crises, one third-party violence incident.
    # Pattern waves: Sleep/Mood (days 105-99), Medication refusal (days 82-76),
    #   Physical/Appetite (days 61-54), Sleep/Mood wave 2 (days 49-42).
    # Crises draw on the patterns that precede them.

    sample_notes = [
        # ── PHASE 1 — Days 120–107: Onboarding & Baseline ─────────────────────
        (dts(120,19,10), "First day with Robert. Guarded at first but cooperative throughout. Took his medication at breakfast without issues. Ate a full lunch and dinner. Walked with me to the mailbox — slow but willing. Back pain is present but he says it's manageable. His room is organized, military neat. He showed me where his medications are kept and his VA paperwork. Quiet start."),
        (dts(119,20,30), "Slept okay by his account — around five or six hours. Mood was calm this morning. Took his medication without prompting. Ate well at every meal. He asked about his upcoming VA appointments. Reminisced about his service. Good first full day. No concerns."),
        (dts(117,20, 0), "Good day. He was more talkative than expected — told a long story about basic training. Took his medication at breakfast. Ate a full lunch and strong dinner. No pain complaints today. Said he slept reasonably well. Getting used to the routine."),
        (dts(116,21,15), "Decent day. Mood was calm. He took his medication on time. Good appetite at lunch and dinner. Back pain at a two — his baseline. He asked about the veteran group program at the VA. His daughter called in the evening and he seemed lifted after."),
        (dts(115,20, 0), "VA appointment today. He came back quieter than when he left. Didn't want to talk about what was discussed. Took his medication after the appointment. Light lunch, better at dinner. VA visits seem to weigh on him emotionally. Stayed close this evening."),
        (dts(113,20,45), "Better day. Slept well according to him. Mood was steady. Took his medication without prompting. Good appetite. He worked on a letter to his brother — dictated while I wrote. He seemed glad to have something purposeful to do."),
        (dts(111,20, 0), "He mentioned nightmares on and off for years but said they've been more frequent lately. Was tired but cooperative. Took his medication. Ate reasonably well. Mood was subdued. I noted the sleep mention and will watch for a pattern. Pain at three."),
        (dts(110,21,30), "Good day. He woke up rested. Mood was lighter than usual. Took his medication. Ate everything at every meal. Walked around the block on his own — said his back felt loose. First time doing that. A good sign."),
        (dts(108,20,20), "Back pain worse today — he rated it a five, said it started overnight. Pain slowed him all morning. Took his medication. Ate okay. I called the VA nurse line and they said to monitor and note any changes. He was patient about it."),
        (dts(107,20, 0), "PT appointment — first one I've attended with him. He did the exercises but said pain increased during. PT said some discomfort is expected early on. Mood was okay. Took his medication. Ate well at dinner. Pain down to a three by evening."),

        # ── PHASE 2 — Days 106–99: Wave 1 — Sleep Disruption + Mood Decline ───
        # Sleep concerning: days 105, 103, 102, 100, 99 (5 in 7-day window ending day 99)
        # Mood concerning: days 104, 103, 102, 100, 99 (5 in 7-day window ending day 99)
        # → Pattern alerts inserted at day 99
        (dts(106,20,30), "Stable day. Good mood in the morning. Took his medication without prompting. Ate well at all three meals. Back pain at two — his real baseline. No nightmares mentioned. He called his brother and had a good long conversation."),
        (dts(105,20,15), "He told me he woke up at 3 this morning and couldn't get back to sleep. Was tired and irritable through most of the morning. Took his medication after some reluctance. Ate lunch and dinner. Mood improved a little by evening but exhaustion was visible."),
        (dts(104,21, 0), "He was irritable from the moment I arrived — short responses, sharp tone. No clear trigger. Took his medication eventually. Ate at meals. Snapped at me when I reminded him about PT exercises. I gave him space. By evening he settled. Said he hadn't slept well again."),
        (dts(103,20,30), "He couldn't sleep again last night. Was withdrawn when I arrived and wouldn't engage in conversation for most of the morning. Took his medication. I'm starting to see a pattern — poor sleep leads directly to a withdrawn, low-mood day. Back pain also climbing, at a four."),
        (dts(102,19,50), "Rough night — he woke up screaming, heard it when I arrived early. Was pale and shaking. Low mood all day, didn't want to talk. Refused his medication at breakfast, took it at noon. Ate dinner only. Nightmares are getting worse and the daytime impact is clear. Documenting carefully."),
        (dts(101,20,30), "Exhausted and withdrawn from another poor night. Mood was very subdued but he was present. Took his medication on time, which was the one bright spot. Ate two meals. Back pain at a four. Didn't want to do PT exercises at home. Just wanted to rest."),
        (dts(100,20, 0), "Barely slept last night. When I arrived he was sitting in the dark — said he'd been up since 3. Mood was depressed, hardly spoke. Refused his medication at first but took it an hour later. Ate a small lunch and dinner. Called the VA today and flagged the sleep and mood pattern. They'll follow up."),
        (dts(99,20,45), "Was up most of the night again. Exhausted and irritable. Mood was low but he was more talkative than yesterday — said the nightmares are about his unit, specific moments he won't describe. Took his medication. The VA called back and is scheduling an appointment to address the sleep and nightmare pattern specifically."),

        # ── PHASE 3 — Days 97–83: MH Crisis #1 + Recovery ─────────────────────
        (dts(97,20, 0), "VA nurse confirmed a sleep review appointment in two weeks. He seemed relieved someone is listening. Slept better last night by his account. Mood calmer. Took his medication. Good appetite. Back pain at two. A bit of breathing room."),
        (dts(95,20,30), "Tired but functional. Sleep was disrupted again but less severely. Mood flat, stayed in his room most of the morning. Took his medication. Ate at every meal. He asked about the VA appointment — he wants to talk about the nightmares. That's meaningful."),
        (dts(93,21, 0), "Back pain flared today — rated it a six. Walked with difficulty. Took his medication. Ate light at lunch, better at dinner. Mood was subdued. I messaged the VA about the flare. The combination of pain and poor sleep is wearing on him. He said it himself."),
        (dts(91,20,30), "Better day. Slept more than usual — almost seven hours. Mood was steadier. Took his medication. Good appetite. His brother called from Texas and they talked for a long time. He was more himself afterward. Back pain back to a two. Good day overall."),
        (dts(90,20, 0), "VA appointment tomorrow for the sleep and nightmare review. He knows and seems prepared. Took his medication. Ate well. Mood was quiet but not concerning. He told me he wants the doctor to understand what the nightmares are actually like. I told him to say exactly that."),
        (dts(88,21, 0), "Very difficult day. He woke from nightmares multiple times and by morning he was distraught. During breakfast he said he doesn't want to be here anymore — that nothing is ever going to change and he is tired of feeling this way. I stayed calm, stayed with him, did not leave. Called the VA crisis line immediately. They spoke with him for nearly forty minutes. He calmed down but was exhausted and fragile the rest of the day. I stayed until 9 PM. VA is scheduling an urgent mental health appointment for this week."),
        (dts(87,20,30), "Day after the crisis. Subdued and cooperative. VA confirmed the mental health appointment for tomorrow. He agreed to go. Took his medication on his own. Ate okay. Checked in every hour. No crisis indicators. He thanked me for staying yesterday."),
        (dts(86,20, 0), "VA mental health appointment today. Quiet going in and quiet coming out, but not distressed. Provider is adjusting his medication — adding support for the nightmares alongside his Prazosin. He said the appointment felt important. That's significant."),
        (dts(85,20,45), "First day on adjusted medication. Groggy — provider said to expect that for a few days. Took his meds. Ate light. Slept during the afternoon. Mood flat but stable, no crisis indicators. Checked in every couple of hours."),
        (dts(83,20, 0), "Medication adjustment settling. Less groggy today. Slept through the night for the first time in weeks — he mentioned it at breakfast without prompting. Mood cautiously better. Took his medication. Good appetite. Things are moving in the right direction."),

        # ── PHASE 4 — Days 82–74: Wave 2 — Medication Refusal ─────────────────
        # Medication refusal concerning: days 82, 80, 78, 77, 76 (5 in 7-day window)
        # → Pattern alert inserted at day 76
        (dts(82,21, 0), "He refused his medication this morning — said the new addition to his regimen makes him feel foggy and he doesn't want it. I explained the provider's rationale. He took his evening medications but not the morning dose. Flagging to the VA."),
        (dts(81,20,30), "Mood was okay today. He took his medication at lunch after initially declining. Slept better than last week. Ate well. He called his daughter and they made plans for her to visit next month. Having something to look forward to is good."),
        (dts(80,20, 0), "He refused his medication again at breakfast — said it makes him feel like someone else. Stayed firm but did not force it. He took the evening dose. Ate okay. Mood was mixed. Documenting the refusal and calling the VA tomorrow."),
        (dts(78,21,15), "Refused his medication in the morning again. This is a consistent pattern now. He said the new medication makes him feel numb. Called the VA nurse — they said to document and they will review at next week's appointment. Took his other meds. Ate at meals. No crisis indicators."),
        (dts(77,20,30), "Refused his medication at breakfast and at lunch. Took it at dinner only. He is frustrated with how the medication makes him feel — I hear him, and I am also worried about the refusals compounding. VA appointment in three days. Mood was low but not at crisis level."),
        (dts(76,20, 0), "Refused his medication again this morning. Carefully documented every refusal this week. He took his evening dose. Mood was flat. Said he wants the VA to change what they gave him — he doesn't feel like it is helping the right things. I think he has a point."),
        (dts(75,21, 0), "VA appointment today. He told the provider exactly what he told me — the medication makes him feel foggy and numb. Provider adjusted the dose downward. He seemed relieved to be heard. Mood lifted leaving the appointment. Took his medication at the new dose without resistance this evening."),
        (dts(74,20,30), "Better day. Took his medication without any issue at the new dose. Said he already feels less foggy. Mood was calmer. Ate well. Slept okay. Back pain at a three — manageable. Talked about his daughter's upcoming visit. Things more settled today."),

        # ── PHASE 5 — Days 73–62: Agitation Building + Violence Incident ───────
        (dts(73,20, 0), "Mood elevated in an unusual way today — not the good kind. On edge, hypervigilant, checked the window several times. Took his medication. Ate okay. He mentioned a dream about being ambushed but wouldn't go further. Noted the agitation and heightened alertness."),
        (dts(72,20,45), "Poor sleep again. He was pacing when I arrived. Refused his medication at breakfast — said he was too distracted. Took it at lunch. Mood was unsettled. A car backfired outside and he had a visible startle response — went straight to the window, didn't calm easily. Behavioral concerns today."),
        (dts(70,21, 0), "Agitated and pacing most of the morning. Loud television bothered him — he turned it off and sat in silence. Took his medication. Ate lunch. A neighbor knocked and he tensed visibly, wouldn't open the door — I handled it. This level of hypervigilance is new. Flagging to the VA."),
        (dts(68,20,15), "On edge all day. Seemed paranoid — kept saying someone was outside. I checked twice, no one was there. Took his medication after significant coaxing. Ate dinner. He had a flashback in the evening — grabbed the table edge, stared for thirty seconds, then came back. First one I have witnessed directly. Calling VA in the morning."),
        (dts(66,20,30), "Called the VA this morning and described what I have been seeing — pacing, paranoia, flashback, hypervigilance. They said bring him in if anything escalates. He was calmer today. Took his medication. Ate at meals. Mood was low but not actively agitated. Staying alert."),
        (dts(65,21, 0), "Serious incident today. A neighbor came to the door to complain about noise. Robert was already agitated from a flashback earlier in the afternoon. He got violent with a neighbor at the front door — grabbed him and shoved him hard into the doorframe before I could intervene. I separated them immediately. Robert came back inside visibly shaken. The neighbor was shaken but not seriously hurt and left. I called the VA crisis team right away. They arrived within the hour. Robert was calm by the time they got here. VA is contacting the neighbor and doing a formal safety review. I am documenting everything precisely."),
        (dts(64,20, 0), "The day after the incident. Robert was subdued and remorseful — kept saying he didn't know why he did it. Ate okay. Took his medication. The VA safety team called to check in. Home visit scheduled for tomorrow. Documenting everything. He is not a danger right now but this changes the risk picture."),
        (dts(62,20,30), "VA safety home visit completed. They spoke with Robert for about an hour. He was cooperative and honest. Safety plan updated — VA will increase check-in frequency and is expediting the trauma specialist referral. Robert seemed relieved that people are taking it seriously. Took his medication. Ate okay."),

        # ── PHASE 6 — Days 61–51: Wave 3 — Physical Decline + Appetite ─────────
        # Physical (via 'pain'): days 61, 59, 57, 55, 54 (5 in 7-day window ending day 54)
        # Appetite concerning: days 59, 57, 55, 54 (4 in 7-day window)
        # → Pattern alerts inserted at day 54
        (dts(61,20, 0), "Quiet day after the safety review. Cooperative and subdued. Took his medication. Ate at every meal. No agitation or hypervigilance observed. I think the VA visit helped him feel contained. Still watching carefully. He thanked me for how I handled the door situation."),
        (dts(60,20,30), "Back pain significantly worse — rated it a six. Said it woke him up around 4 AM. Pain affected his posture and movement all morning. Took his medication. Ate okay. Messaged the VA about the back pain flare. The stress from last week may be contributing."),
        (dts(59,21, 0), "Pain continued at a five — said it now radiates down his left leg. Barely ate at breakfast, said he had no appetite. Small dinner. Took his medication. Didn't want to move much. Helped him with ice and a heating pad. VA nurse said to monitor whether the radiating pain continues."),
        (dts(57,20,45), "Back pain still significant — rated it a six again. Uncomfortable changing positions. Skipped dinner, said the pain kills his appetite. Took his medication. Ate a small lunch. Concerned the radiating pattern suggests nerve involvement. VA PT in two days."),
        (dts(55,20, 0), "Pain at a seven this morning. Barely got out of bed. Wouldn't eat, said he felt nauseous from the pain. Helped him sit up slowly. Took his medication. Called the VA urgently — they moved the PT appointment to tomorrow. He was frustrated but complied."),
        (dts(54,20,30), "Emergency PT today. Therapist found significant muscle spasm and possible nerve irritation. Rest order for three days — no exercises, minimal movement. Back pain at a six leaving PT. Barely ate at lunch and dinner, said the pain suppresses everything. Mood low. Still taking his medication. A hard day."),
        (dts(53,21, 0), "First rest day. Stayed in bed most of the morning. Pain easing to a five. Mood was low — being immobile is hard for him. Sat with him and we talked more than usual. Took his medication. Ate a small lunch. He talked about how being stuck in bed triggers memories of being helpless. Hard to hear."),
        (dts(51,20,30), "Cleared for light movement. Pain down to a three. He was visibly relieved to be able to move again. Mood better. Took his medication. Good appetite. Asked about resuming PT next week. Trauma specialist appointment confirmed — three weeks out. He said he is ready."),

        # ── PHASE 7 — Days 50–41: Wave 4 — Sleep + Mood 2nd Wave ──────────────
        # Sleep concerning: days 50, 49, 48, 47, 45, 44 (6 in 7-day window ending day 44)
        # Mood concerning: days 50, 49, 48, 47, 45, 44 (6 in 7-day window)
        # → Pattern alerts inserted at day 42
        (dts(50,20, 0), "Nightmares are back. He woke up screaming last night — heard it when I arrived early. Pale and shaking in the morning. Mood was very low, wouldn't make eye contact. Took his medication. Ate a small lunch. I am worried this is a new wave. Documenting carefully."),
        (dts(49,21, 0), "He couldn't sleep last night — said every time he drifted off the nightmares pulled him back. Exhausted by morning. Mood was depressed, barely spoke. Took his medication. Ate at dinner. Called the VA to flag the nightmare recurrence. They said to monitor and come in if crisis signs emerge."),
        (dts(48,20,30), "Barely slept two hours. Withdrawn when I arrived — sat in the living room staring at nothing. Mood was very low. Took his medication after prompting. Ate lunch. He said the nightmares feel more real than before, like being there again. Documenting every detail."),
        (dts(47,20, 0), "Didn't sleep at all by his account. Sitting up in the chair when I arrived at 7. Mood low, depressed, flat affect. Took his medication. Ate a small dinner. Didn't want to talk and I didn't push. Just stayed present. Back pain creeping back — rated it a four."),
        (dts(45,21,15), "Woke up at 3 AM by his account — called me at 6 saying he'd been up for hours. When I arrived he was agitated and tearful, which is unusual. Low mood all day. Took his medication. Ate lunch. Called the VA again. They moved the trauma specialist appointment up by a week. Still eight days away."),
        (dts(44,20,30), "Was up most of the night. Exhausted, couldn't hold a conversation. Low mood persisted all day. Took his medication. Barely ate at lunch. By evening he was calmer from pure fatigue. Stayed until 8 PM. He fell asleep in the chair. Made sure he got to bed safely before I left."),
        (dts(43,21, 0), "He woke up screaming again last night. Called me. I came early. Distressed and shaking. Mood was dark and frightened. Took his medication once calm. Ate a small dinner. He told me the nightmare involved his unit and something he has never described before — I let him talk as long as he wanted. He cried. I stayed."),
        (dts(42,20, 0), "Barely slept. Depressed and exhausted when I arrived. Mood was the lowest I've seen since the first crisis weeks ago. Took his medication. Ate a small lunch. VA crisis line number is posted on his refrigerator. Gave him mine again and asked him to call any time. He said he would. He is holding on but barely."),

        # ── PHASE 8 — Days 41–22: MH Crisis #2 + Recovery ─────────────────────
        (dts(41,20,30), "He made it through the night without calling. Still very tired and low mood but slightly more present today. Took his medication. Ate at two meals. He talked about the trauma specialist appointment this week — said he doesn't know if he can hold on that long. I took that seriously and called the VA to ask about an earlier slot. They're looking."),
        (dts(40,21, 0), "VA found an earlier slot for next week. He seemed relieved when I told him. Mood still low. Took his medication. Ate okay. Sleep was poor again but he stayed in bed. Checking in morning and evening by text. He is responding."),
        (dts(38,20,30), "Mood collapsed today. Almost non-verbal by the time I arrived. No appetite — barely touched breakfast or lunch. Took his medication after significant coaxing. Sat by the window for hours, looking outside. Stayed all day. Called the VA and described his state. They told me to watch overnight and call the crisis line if anything escalates."),
        (dts(36,21, 0), "Hard day. Mood extremely low. Refused to eat much at all. Took his medication. Barely spoke. We sat together in quiet for hours. He finally said he is tired of fighting this every day. I acknowledged how exhausting that must be and stayed close. No explicit crisis language but the despair is palpable."),
        (dts(34,20, 0), "He is visibly struggling. Mood low throughout. Ate a small dinner only. Took his medication. The trauma specialist appointment is in four days — he knows and seems to be counting down. Told me it is the only thing he is looking forward to. Glad it exists."),
        (dts(33,20,30), "Trauma specialist pre-appointment screening call today. She called and spoke with him for twenty minutes. He opened up more than I expected. After the call his mood was lighter for a few hours. Took his medication. Ate dinner. Sleep still poor but he got through the night."),
        (dts(31,21, 0), "Quiet day. Subdued but compliant. Took his medication. Ate at every meal. Didn't speak much but wasn't distressed. I think he is conserving energy for the appointment in two days. He told me he has been thinking about what he wants to say. That takes strength."),
        (dts(30,20, 0), "One day before the trauma specialist. Anxious in a functional way — anticipatory, not crisis. Mood was tense but present. Took his medication. Ate well. We talked through what he wants the specialist to know. He has a list in his head. I felt the gravity of tomorrow."),
        (dts(28,21, 0), "Worst day since I started. He texted me at 5 AM and when I called he was crying and incoherent. I came immediately. He was on the floor by his bed. He said there was no reason to live. I stayed on the phone with the VA crisis line while physically present with him. The VA dispatched a mobile crisis team — they arrived within 45 minutes. He was evaluated and agreed to a voluntary same-day psychiatric evaluation at the VA medical center. I accompanied him. They adjusted his medication and put a safety plan in place. He came home late that night, exhausted but stable. The trauma specialist appointment is tomorrow — VA psychiatrist confirmed it is still on."),
        (dts(27,20,30), "Trauma specialist appointment today — the day after the crisis. He went. I went with him. He spoke for nearly an hour. The specialist is a veteran herself, which mattered to him. She will see him weekly. His medication has been adjusted again. He came home quiet but not distressed. He told me in the car that he felt heard for the first time in a long time. That stayed with me."),
        (dts(26,20, 0), "Day two post-crisis. Slept heavily — the medication adjustment helped. Mood flat but stable. Took his medication on time. Ate at breakfast and dinner. Safety plan is posted on his refrigerator. Crisis team checking in by phone daily this week. He answered the first call and was cooperative."),
        (dts(25,20,30), "Third day after the crisis. Stabilizing. Mood still low but there is a floor to it now that wasn't there before. Took his medication. Ate all three meals. Slept about five hours. The trauma specialist called to check in. He spoke with her for twenty minutes. Calmer after. Progress."),
        (dts(22,21, 0), "End of the first full week post-crisis. More stable. Taking his medication consistently. Sleep is better — nightmares still present but less severe. Mood has lifted from the floor, though still not good. He wanted to call his brother. We called together. Long conversation. Good for him."),

        # ── PHASE 9 — Days 21–0: Stabilization & Progress ─────────────────────
        (dts(21,20,30), "Calmer day. Mood was steady for most of the morning. Took his medication without prompting. Ate well. Sleep still disrupted but less severely. Back pain at a three — manageable. Told me the trauma specialist appointment yesterday was the best yet. They are starting EMDR work."),
        (dts(19,20, 0), "Better sleep last night — only one nightmare instead of multiple, he said. Mood noticeably calmer. Took his medication. Good appetite at every meal. He went for a short walk without prompting. First time in weeks. His posture was different — more upright. Something is shifting."),
        (dts(17,20,45), "His daughter called. He was animated and engaged — laughed twice during the call. That is significant. Mood was the best in over a month. Took his medication. Strong appetite. Sleep was okay. He told me his daughter is planning to visit next month. He has something to look forward to."),
        (dts(15,21, 0), "Trauma specialist appointment — he went alone this time. Said he wanted to try. Came back quiet but purposeful. Said they are making progress. Medication seems to be working at the new dose — no foggy feeling, he said. Took his medication. Ate well. Sleep was decent. Cautiously optimistic."),
        (dts(13,20,30), "Good day. Mood was steady and even pleasant at moments. He initiated conversation at breakfast without prompting. Took his medication. Strong appetite. Back pain at a two — his real baseline. He asked about the veteran group meeting schedule. Looking ahead is new."),
        (dts(11,20, 0), "He walked to the corner store on his own and came back with something for dinner. That is independence I have not seen before. Mood was good. Took his medication. Ate well. Slept about six hours. No major complaints. The EMDR work seems to be doing something. He looks different — less haunted."),
        (dts( 9,21,15), "Slept well — six and a half hours he said, the most in months. Mood was calm and warm. He made a joke at breakfast. Took his medication. Good appetite. No pain complaints. He mentioned noticing the medication feels different now — like it is working instead of fighting him. Important to document."),
        (dts( 7,20,30), "His daughter is coming to visit this weekend. He has been looking forward to it for two weeks. Mood was animated today anticipating the visit. Took his medication. Ate well. Sleep was okay. He cleaned his room on his own — organized, military neat again. Care he is taking for himself."),
        (dts( 5,20, 0), "His daughter arrived today. The change in him was immediate — bright, engaged, holding court. He showed her around, talked about his therapy progress. Took his medication without being reminded. Ate everything. Laughed several times. This is who he is when things are going right."),
        (dts( 4,21, 0), "Second day of the visit. Still elevated — participating, smiling, storytelling. Took his medication. Strong appetite. He and his daughter went through old photographs. He talked about his service without shutting down. That is growth. I watched from across the room and felt the weight of the progress."),
        (dts( 3,20,30), "Last day of the daughter's visit. Quieter by evening but held himself together during the goodbye. Took his medication. Ate well. The transition back to routine is always a watch period. Noted the emotional shift and will check in more frequently this week."),
        (dts( 2,21, 0), "Post-visit adjustment. Mood was lower than yesterday but not at concerning levels — he knows his own pattern now and named it. Said he always feels a dip after she leaves and it passes. Took his medication. Ate okay. Slept through the night, which surprised me. His self-awareness is different from when we started."),
        (dts( 1,20,30), "Good recovery from the post-visit dip. Mood was steady. He mentioned the trauma specialist appointment unprompted. Took his medication. Ate well. Back pain at a two. Asked me to look up the veteran peer group schedule — we found one nearby. He said he is thinking about going. That is forward motion."),
        (dts( 0,20, 0), "Strong day. He woke at a reasonable hour, made his own coffee. Mood was calm and grounded — the most grounded I have seen him in four months. Took his medication on time without any prompting. Ate a full breakfast and dinner. Trauma specialist appointment is Thursday, veteran group meeting the Thursday after. He has structure and he is showing up to it. Progress is real and I am documenting it."),
    ]

    # ── TRANSLATION SESSIONS ────────────────────────────────────────────────────
    translation_sessions = [
        (dts(108,14,30), "[Translation Session — Robert, Spanish ↔ English]\n\nRobert: Good morning how did you sleep (Buenos días cómo dormiste)\nJimmy: I slept well thank you and you (Dormí bien gracias y tú)\nRobert: Not well I had pain in my back all night (No bien tuve dolor en la espalda toda la noche)\nJimmy: I am sorry I will let the nurse know about your pain (Lo siento le avisaré a la enfermera sobre tu dolor)\nRobert: Thank you I appreciate that (Gracias lo aprecio)\nJimmy: What else can I do for you today (¿Qué más puedo hacer por ti hoy?)\nRobert: Just stay close please (Solo quédate cerca por favor)"),
        (dts(86,15, 0), "[Translation Session — Robert, Spanish ↔ English]\n\nRobert: I feel ashamed about what I said (Me da vergüenza lo que dije)\nJimmy: You do not need to feel ashamed you were in pain (No tienes que sentir vergüenza estabas sufriendo)\nRobert: I have felt this way before and I never said it out loud (He sentido esto antes y nunca lo dije en voz alta)\nJimmy: Saying it out loud was brave not weak (Decirlo fue valiente no débil)\nRobert: My family cannot know how bad it gets (Mi familia no puede saber qué tan mal se pone)\nJimmy: Your family knows you are strong they just need to know you also need help (Tu familia sabe que eres fuerte solo necesitan saber que tú también necesitas ayuda)\nRobert: Maybe you are right (Quizás tienes razón)"),
        (dts(62,16,30), "[Translation Session — Robert, Spanish ↔ English]\n\nRobert: I did not mean to hurt him (No quise hacerle daño)\nJimmy: I know you did not the VA team knows that too (Lo sé tú no quisiste el equipo de la VA también lo sabe)\nRobert: Something took over I was not myself (Algo me tomó el control no era yo mismo)\nJimmy: That is exactly what you need to tell the trauma specialist (Eso es exactamente lo que necesitas decirle al especialista en trauma)\nRobert: Will they understand (¿Lo entenderán?)\nJimmy: Yes that is what they are trained for (Sí para eso están entrenados)\nRobert: Okay I will try (Bien lo intentaré)"),
        (dts(33,15,45), "[Translation Session — Robert, Spanish ↔ English]\n\nRobert: I want to tell the specialist things I have never said in English (Quiero decirle al especialista cosas que nunca he dicho en inglés)\nJimmy: We can practice together if you want (Podemos practicar juntos si quieres)\nRobert: There are things that only make sense in Spanish (Hay cosas que solo tienen sentido en español)\nJimmy: Then say them in Spanish and I will help translate (Entonces dilo en español y yo ayudaré a traducir)\nRobert: I was nineteen and I made a decision I cannot change (Tenía diecinueve años y tomé una decisión que no puedo cambiar)\nJimmy: You were a kid trying to do what you were trained to do (Eras un niño tratando de hacer lo que te entrenaron para hacer)\nRobert: I know but it does not feel that way (Lo sé pero no se siente así)"),
        (dts(11,14, 0), "[Translation Session — Robert, Spanish ↔ English]\n\nRobert: I slept well last night I want you to know that (Dormí bien anoche quiero que lo sepas)\nJimmy: That is great to hear what do you think is helping (Eso es genial qué crees que está ayudando)\nRobert: The therapy and the medication and you staying with me (La terapia y el medicamento y tú quedándote conmigo)\nJimmy: That means a lot to me (Eso significa mucho para mí)\nRobert: My daughter says you are the reason I am still here (Mi hija dice que tú eres la razón por la que todavía estoy aquí)\nJimmy: Your daughter is kind but you did the work (Tu hija es amable pero tú hiciste el trabajo)\nRobert: We both did (Los dos lo hicimos)"),
    ]

    # ── CAREGIVER WELLBEING CHECK-INS ──────────────────────────────────────────
    wellbeing_entries = [
        (dts(119,20,35), 3, "Still figuring out the routine. Robert is cooperative. Feeling cautiously okay."),
        (dts(116,20,10), 3, None),
        (dts(115,21, 5), 2, "VA appointment days are uncertain. He came back quiet. I stayed alert."),
        (dts(113,20,25), 4, "Letter-writing was meaningful for both of us. Days like this remind me why I do this."),
        (dts(111,20, 0), 3, None),
        (dts(108,20,30), 2, "Back pain days are hard. I feel like I should be able to do more for it."),
        (dts(107,20, 5), 3, "PT went okay. Good to see him doing something physical."),
        (dts(105,20,10), 2, "The sleep disruption is visible now. Documenting everything carefully."),
        (dts(104,21, 5), 2, "His irritability on these days is hard to absorb without taking it personally. I know it's not about me."),
        (dts(103,20,30), 1, "Worst sleep nights produce worst days. I'm exhausted from the vigilance too."),
        (dts(102,21, 0), 1, "He woke up screaming. I came early. Still shaking on the drive over. Hardest morning so far."),
        (dts(100,20,10), 2, "These low days are heavy. Called the VA. Glad I documented. The pattern is real."),
        (dts(99,21, 5), 3, "VA is following up on the sleep pattern. Having a plan helps me too."),
        (dts(97,20,10), 3, "VA nurse confirmed the appointment. That helps."),
        (dts(93,20,30), 2, "Back pain on top of everything else. Long day."),
        (dts(91,21, 5), 4, "His brother's call lifted him. I felt it too."),
        (dts(88,21,30), 1, "Hardest day since I started. He said he doesn't want to be here. My hands were shaking the whole time I stayed. Called the VA crisis line from his kitchen. Did not leave until 9 PM. Could not eat dinner when I got home."),
        (dts(87,20,15), 2, "Still processing yesterday. He is stable. I am not fully okay but I am here."),
        (dts(86,20,30), 3, "VA appointment helped. The medication change is a step. More grounded today."),
        (dts(83,21, 0), 4, "He slept through the night. Found out in the morning. I actually cried in the car. Relief."),
        (dts(82,20,10), 2, "Medication refusals are draining. I don't want to be the enforcer. That's not the relationship I want with him."),
        (dts(80,20,30), 2, "Another refusal. Documented. Called VA. Felt powerless again."),
        (dts(75,20, 5), 4, "VA heard him today. The dose adjustment felt like a turning point. He left looking lighter."),
        (dts(73,20,30), 2, "Something is off with him this week. Can't name it but I'm watching carefully."),
        (dts(70,21, 0), 2, "The hypervigilance is hard to be around. I feel it in my own body."),
        (dts(68,20,15), 1, "The flashback I witnessed today was frightening. Held it together for him. Fell apart a bit on the drive home."),
        (dts(65,21,30), 1, "The incident. I have never intervened physically in a caregiving situation before. I replayed it all evening. He is safe. The neighbor is okay. I am shaken."),
        (dts(64,20,20), 2, "Still processing the incident. He was remorseful. I was professional. Feels important to keep showing up."),
        (dts(62,20,30), 3, "VA safety visit helped clarify things. I feel like there's a team around him now. And me."),
        (dts(60,20,10), 2, "Back pain crisis on top of everything. Never rains. Documenting everything."),
        (dts(57,20,30), 2, "The combination of pain and low appetite is concerning. I feel like I should have a medical degree."),
        (dts(54,20,10), 1, "Emergency PT. Rest order. He is suffering physically and I feel helpless. Today was a lot."),
        (dts(51,21, 0), 3, "He can move again. Relief. He seems relieved too."),
        (dts(49,20,30), 2, "Nightmares back. I had hoped we were past this. Documenting for the VA."),
        (dts(45,21,15), 1, "Called the VA again. Calling every other day now. The appointment being moved up is the only good news."),
        (dts(43,21,30), 1, "He cried. I have never seen him cry before. I stayed. Did not know what else to do. Stayed."),
        (dts(42,20,15), 2, "He is holding on. So am I. Documenting everything."),
        (dts(38,20,30), 1, "His mood collapsed. I stayed all day. Did not eat lunch. Didn't think about it until the drive home."),
        (dts(36,21, 0), 2, "He said he is tired of fighting. I did not know what to say. I just stayed. Sometimes that is the whole job."),
        (dts(28,21,45), 1, "Second crisis. Four months in and this is the second time I have been here for this. I am proud of how I handled it and also exhausted to my bones. He is safe. That is what matters."),
        (dts(27,20,30), 3, "The trauma specialist. She is the right person. I could see it on his face. Something shifted today."),
        (dts(25,20,10), 3, "Third day post-crisis. He is stabilizing. So am I. I called the caregiver support line for myself today. That was important."),
        (dts(22,21, 0), 4, "One week post-crisis. More stable than I have felt in a long time. The team is good. He is trying."),
        (dts(17,20,45), 4, "His daughter called. He laughed. I cried in the car again. Happy tears this time."),
        (dts(11,21, 0), 5, "He went to the store alone. I watched from here. He came back. That was everything."),
        (dts( 5,20,30), 5, "Daughter's visit. Best day since I started. Maybe best day ever in this work."),
        (dts( 3,20,10), 3, "Last day of the visit. Watching the transition. He named it himself. That is growth."),
        (dts( 1,20,35), 4, "He mentioned the trauma appointment unprompted. Progress is real."),
        (dts( 0,20,10), 5, "Strong end to the week. He has a schedule. He is showing up. So am I."),
    ]

    conn = get_db()

    # Wipe existing seeded data for a clean 120-day slate
    conn.execute("DELETE FROM deletion_audit")
    conn.execute("DELETE FROM alerts")
    conn.execute("DELETE FROM entries")
    conn.execute("DELETE FROM caregiver_wellbeing")
    conn.execute("DELETE FROM medications")
    conn.execute("DELETE FROM patients")
    conn.execute("DELETE FROM caregivers")
    conn.commit()

    # Seed patient and caregiver
    conn.execute(
        "INSERT INTO patients (name, is_veteran, patient_language) VALUES (?, ?, ?)",
        ("Robert", 1, "es")
    )
    conn.execute(
        "INSERT INTO caregivers (name, caregiver_id) VALUES (?, ?)",
        ("Jimmy", str(uuid.uuid4()))
    )
    conn.commit()

    inserted_entries  = 0
    inserted_wellbeing = 0

    # Insert observation entries — emergency alerts auto-created from extraction
    entry_ids_by_date = {}  # date string → list of entry IDs (for pattern alert linking)
    for created_at, note in sample_notes:
        extraction = extract_note(note)
        cur = conn.execute(
            "INSERT INTO entries (created_at, raw_note, extracted_tags, is_emergency_flagged, emergency_phrase, note_type) VALUES (?, ?, ?, ?, ?, 'observation')",
            (created_at, note, json.dumps(extraction["tags"]),
             1 if extraction["emergency"] else 0,
             extraction.get("emergency_phrase"))
        )
        entry_id = cur.lastrowid
        day_key  = created_at[:10]
        entry_ids_by_date.setdefault(day_key, []).append(entry_id)
        if extraction["emergency"]:
            etype = extraction.get("emergency_type") or "emergency"
            conn.execute(
                "INSERT INTO alerts (created_at, entry_id, alert_type, alert_message) VALUES (?, ?, ?, ?)",
                (created_at, entry_id, etype,
                 f"Emergency language detected: \"{extraction['emergency_phrase']}\"")
            )
        inserted_entries += 1

    # Insert translation sessions
    for created_at, note in translation_sessions:
        extraction = extract_note(note)
        conn.execute(
            "INSERT INTO entries (created_at, raw_note, extracted_tags, is_emergency_flagged, emergency_phrase, note_type) VALUES (?, ?, ?, 0, NULL, 'translation')",
            (created_at, note, json.dumps(extraction["tags"]))
        )
        inserted_entries += 1

    # Insert caregiver wellbeing check-ins
    for created_at, rating, notes in wellbeing_entries:
        conn.execute(
            "INSERT INTO caregiver_wellbeing (created_at, rating, notes) VALUES (?, ?, ?)",
            (created_at, rating, notes)
        )
        inserted_wellbeing += 1

    # Seed medications
    meds = [
        ("Sertraline",  "100mg", "Once daily", "Morning", "Prescribed for depression and PTSD symptoms"),
        ("Prazosin",    "2mg",   "Once daily", "Bedtime",  "For nightmare reduction — VA prescribed"),
        ("Ibuprofen",   "400mg", "As needed",  None,       "For back pain — use sparingly"),
        ("Lisinopril",  "10mg",  "Once daily", "Morning",  "Blood pressure management"),
    ]
    for name, dosage, frequency, scheduled_time, note_text in meds:
        conn.execute(
            "INSERT INTO medications (name, dosage, frequency, scheduled_time, notes) VALUES (?,?,?,?,?)",
            (name, dosage, frequency, scheduled_time, note_text)
        )

    conn.commit()

    # ── Insert historical pattern alerts at the correct dates ──────────────────
    # Each alert is linked to an entry from that date so the calendar's has_pattern
    # flag fires correctly: DATE(a.created_at) = DATE(e.created_at).
    label_map = {
        "sleep":      "Sleep disruption",
        "mood":       "Mood concerns",
        "medication": "Medication refusal",
        "physical":   "Physical symptoms",
        "appetite":   "Appetite issues",
    }

    def add_pattern_alert(days_ago, category, count, window=7):
        created = dts(days_ago, 21, 0)
        day_key = created[:10]
        ids     = entry_ids_by_date.get(day_key, [])
        eid     = ids[-1] if ids else None
        label   = label_map.get(category, category.title())
        msg     = f"{label} flagged {count} times in the last {window} days."
        conn.execute(
            "INSERT INTO alerts (created_at, entry_id, alert_type, alert_message) VALUES (?, ?, 'pattern', ?)",
            (created, eid, msg)
        )

    # Wave 1 (days 105–99): sleep disruption 5x, mood concerns 5x
    add_pattern_alert(99, "sleep", 5)
    add_pattern_alert(99, "mood",  5)
    # Wave 2 (days 82–76): medication refusal 5x
    add_pattern_alert(76, "medication", 5)
    # Wave 3 (days 61–54): physical symptoms 5x, appetite issues 4x
    add_pattern_alert(54, "physical",  5)
    add_pattern_alert(54, "appetite",  4)
    # Wave 4 (days 50–42): sleep disruption 6x, mood concerns 6x
    add_pattern_alert(42, "sleep", 6)
    add_pattern_alert(42, "mood",  6)

    conn.commit()
    conn.close()

    return jsonify({
        "inserted":  inserted_entries,
        "wellbeing": inserted_wellbeing,
        "message":   f"Loaded {inserted_entries} entries and {inserted_wellbeing} caregiver check-ins across 120 days."
    })

# ── Voice ID ───────────────────────────────────────────────────────────────────

@app.route("/api/voice/status", methods=["GET"])
def voice_status():
    conn = get_db()
    row = conn.execute("SELECT id FROM voice_profiles ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return jsonify({"enrolled": row is not None})

@app.route("/api/voice/enroll", methods=["POST"])
def voice_enroll():
    data = request.get_json()
    conn = get_db()
    cg = conn.execute("SELECT caregiver_id FROM caregivers ORDER BY id DESC LIMIT 1").fetchone()
    caregiver_id = cg["caregiver_id"] if cg else "unknown"
    conn.execute("DELETE FROM voice_profiles WHERE caregiver_id = ?", (caregiver_id,))
    conn.execute("""
        INSERT INTO voice_profiles (caregiver_id, phrase_text, pitch_mean, pitch_std,
                                    energy_mean, spectral_centroid, freq_profile)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        caregiver_id,
        data.get("phrase", ""),
        data.get("pitch_mean", 0),
        data.get("pitch_std", 0),
        data.get("energy_mean", 0),
        data.get("spectral_centroid", 0),
        json.dumps(data.get("freq_profile", []))
    ))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/voice/verify", methods=["POST"])
def voice_verify():
    data = request.get_json()
    conn = get_db()
    row = conn.execute("SELECT * FROM voice_profiles ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return jsonify({"verified": False, "confidence": 0, "reason": "not_enrolled"})

    stored = json.loads(row["freq_profile"] or "[]")
    incoming = data.get("freq_profile", [])

    if not stored or not incoming or len(stored) != len(incoming):
        return jsonify({"verified": False, "confidence": 0, "reason": "profile_mismatch"})

    # Cosine similarity on frequency profile
    dot = sum(a * b for a, b in zip(stored, incoming))
    norm_a = sum(a * a for a in stored) ** 0.5
    norm_b = sum(b * b for b in incoming) ** 0.5
    similarity = dot / (norm_a * norm_b) if norm_a and norm_b else 0

    # Pitch range check
    pitch_ok = True
    if row["pitch_mean"] and row["pitch_std"]:
        incoming_pitch = data.get("pitch_mean", 0)
        pitch_ok = abs(incoming_pitch - row["pitch_mean"]) <= (row["pitch_std"] * 2.5 + 30)

    verified = similarity > 0.72 and pitch_ok
    return jsonify({
        "verified": verified,
        "confidence": round(similarity, 3),
        "pitch_match": pitch_ok
    })

@app.route("/api/voice/profile", methods=["GET"])
def voice_profile():
    conn = get_db()
    row = conn.execute("SELECT pitch_mean, pitch_std, spectral_centroid FROM voice_profiles ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        return jsonify({"enrolled": False})
    return jsonify({
        "enrolled": True,
        "pitch_mean": row["pitch_mean"],
        "pitch_std": row["pitch_std"],
        "spectral_centroid": row["spectral_centroid"]
    })

# ── Translation ────────────────────────────────────────────────────────────────

@app.route('/api/translate', methods=['POST'])
def translate_text():
    data = request.get_json(silent=True) or {}
    text     = (data.get('text') or '').strip()[:1000]
    from_lang = (data.get('from') or 'auto').strip()[:10]
    to_lang   = (data.get('to')   or 'en').strip()[:10]
    if not text:
        return jsonify({'error': 'no text'}), 400
    try:
        from deep_translator import GoogleTranslator
        result = GoogleTranslator(source=from_lang, target=to_lang).translate(text)
        return jsonify({'translated': result or ''})
    except Exception:
        return jsonify({'error': 'translation_failed'}), 500

# ── Text-to-Speech ─────────────────────────────────────────────────────────────

@app.route('/api/tts', methods=['POST'])
def text_to_speech():
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()[:500]
    lang = (data.get('lang') or 'es').strip()[:10]
    if not text:
        return jsonify({'error': 'no text'}), 400
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang=lang, slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return send_file(buf, mimetype='audio/mpeg', download_name='tts.mp3')
    except Exception:
        return jsonify({'error': 'tts_failed'}), 500

# ── Startup (runs under gunicorn and direct) ───────────────────────────────────

init_db()
migrate_db()

# ── Run ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    mode = "SANDBOX (keyword rules)" if SANDBOX_MODE else "LIVE (Claude Haiku)"
    print()
    print("  CareLog — Caregiver AI")
    print("  --------------------------------")
    print(f"  Running at:  http://localhost:{port}")
    print(f"  Mode:        {mode}")
    print(f"  Database:    {DB_PATH}")
    print()
    app.run(debug=False, host="0.0.0.0", port=port)
