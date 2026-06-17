from flask import Flask, request, jsonify, render_template
import sqlite3
import json
from datetime import datetime, timedelta
import os

app = Flask(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

SANDBOX_MODE = True   # set False and implement claude_extract() to go live
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

        CREATE TABLE IF NOT EXISTS deletion_audit (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            alert_id        INTEGER REFERENCES alerts(id),
            requested_by    TEXT NOT NULL,
            reason          TEXT,
            status          TEXT DEFAULT 'denied'
        );
    """)
    conn.commit()
    conn.close()

# ── Mock AI Extraction (swap this block for Claude API in production) ──────────

EMERGENCY_PHRASES = [
    "wants to die", "want to die", "wants to end it", "end it all",
    "kill himself", "kill herself", "killing himself", "killing herself",
    "hurt himself", "hurt herself", "hurting himself", "hurting herself",
    "suicidal", "suicide", "taking his life", "taking her life",
    "no reason to live", "doesn't want to live", "doesn't want to be here",
    "not worth living", "better off dead", "better off without me",
    "crisis", "overdose", "self-harm", "self harm"
]

EXTRACTION_RULES = {
    "sleep": {
        "concerning": [
            "didn't sleep", "couldn't sleep", "no sleep", "up all night", "awake all night",
            "insomnia", "restless night", "nightmare", "nightmares", "bad night",
            "poor sleep", "barely slept", "not sleeping", "can't sleep", "woke up screaming",
            "woke up yelling", "thrashing"
        ],
        "positive": [
            "slept well", "good sleep", "slept through", "good night", "rested", "full night"
        ],
        "neutral": [
            "sleep", "slept", "nap", "napping", "tired", "exhausted", "fatigue", "drowsy", "awake"
        ]
    },
    "mood": {
        "concerning": [
            "on edge", "anxious", "anxiety", "agitated", "angry", "irritable", "upset",
            "frustrated", "withdrawn", "paranoid", "depressed", "depression", "low mood",
            "not himself", "not herself", "distant", "aggressive", "combative",
            "crying", "breaking down", "overwhelmed", "hypervigilant", "jumpy", "startled"
        ],
        "positive": [
            "calm", "happy", "good mood", "positive", "content", "relaxed", "cheerful",
            "laughed", "smiling", "upbeat", "in good spirits"
        ],
        "neutral": [
            "mood", "emotional", "feelings", "seemed", "appeared"
        ]
    },
    "appetite": {
        "concerning": [
            "skipped meal", "didn't eat", "refused food", "not eating", "no appetite",
            "barely ate", "wouldn't eat", "refusing to eat", "lost appetite", "skipped dinner",
            "skipped breakfast", "skipped lunch"
        ],
        "positive": [
            "ate well", "good appetite", "ate everything", "hungry", "enjoyed meal",
            "finished plate", "good meal", "ate a full"
        ],
        "neutral": [
            "ate", "meal", "food", "eating", "breakfast", "lunch", "dinner", "snack"
        ]
    },
    "medication": {
        "concerning": [
            "refused medication", "skipped medication", "forgot medication", "missed dose",
            "wouldn't take", "spit out", "refused meds", "skipped meds", "not taking his meds",
            "not taking her meds", "refused his meds", "refused her meds"
        ],
        "positive": [
            "took medication", "took his meds", "took her meds", "medication on time",
            "no issues with meds", "meds taken", "took all his", "took all her"
        ],
        "neutral": [
            "medication", "meds", "pill", "pills", "prescription", "dose", "refill"
        ]
    },
    "appointments": {
        "concerning": [
            "skipped", "missed", "refused to go", "cancelled", "no show",
            "didn't make it", "wouldn't go", "refused appointment", "skipped his", "skipped her"
        ],
        "positive": [
            "attended", "went to", "made it to", "completed appointment", "kept appointment",
            "showed up", "went to therapy", "went to the va"
        ],
        "neutral": [
            "appointment", "physical therapy", "pt appointment", "therapy", "doctor", "va ",
            "clinic", "session", "counseling", "mental health appointment", "check-up"
        ]
    },
    "social": {
        "concerning": [
            "isolated", "refused to talk", "wouldn't come out", "stayed in room",
            "avoiding", "pushed away", "no contact", "shut himself", "shut herself",
            "won't talk", "ignoring everyone", "closed himself", "closed herself off"
        ],
        "positive": [
            "talked with", "visited with", "called family", "spent time with", "had visitors",
            "engaged", "connected", "brightened up", "opened up"
        ],
        "neutral": [
            "family", "friends", "neighbor", "group", "community", "phone call"
        ]
    },
    "physical": {
        "concerning": [
            "pain", "fell", "fall", "injury", "hurt himself", "limping", "weak", "dizzy",
            "confused", "disoriented", "trembling", "shaking", "bleeding", "swelling",
            "chest pain", "difficulty breathing", "can't walk", "can't stand"
        ],
        "positive": [
            "active", "walked", "exercised", "feeling better physically", "strong today"
        ],
        "neutral": [
            "physical", "body", "moving", "mobility", "walking", "standing"
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
    for phrase in EMERGENCY_PHRASES:
        if phrase in text_lower:
            emergency = True
            emergency_phrase = phrase
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
        note = "Entry logged. No specific topics detected — consider adding more detail."

    return {
        "tags": tags,
        "flags": flags,
        "emergency": emergency,
        "emergency_phrase": emergency_phrase,
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
    conn.close()

    if not has_entries:
        return {"greeting": "Welcome. When you're ready, log how today went.", "context": None}

    if patterns:
        top = patterns[0]
        greetings = {
            "sleep": "You've mentioned sleep problems several times this week — how did last night go?",
            "mood": "You've noted some mood concerns this week. How is he/she doing today?",
            "medication": "There have been some medication challenges recently. Any updates today?",
            "appointments": "A few appointments have been missed this week. How's scheduling going?",
            "appetite": "Appetite has been a concern lately. Did he/she eat well today?",
            "behavior": "You've flagged some behavior concerns this week. How is today going?",
            "social": "Social withdrawal has come up a few times this week. Any change today?",
            "physical": "You've noted some physical symptoms this week. How is he/she feeling today?"
        }
        msg = greetings.get(top["category"],
              f"You've had concerns about {top['label'].lower()} this week. How are things today?")
        return {"greeting": msg, "context": top}

    return {"greeting": "Welcome back. How are things going today?", "context": None}

# ── Summary Generator ──────────────────────────────────────────────────────────

def mock_generate_summary(days=14):
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT raw_note, extracted_tags, created_at FROM entries WHERE created_at >= ? ORDER BY created_at DESC",
        (cutoff,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"summary": "No entries found for the selected period.", "entries_reviewed": 0}

    total = len(rows)
    concern_counts = {}
    positive_counts = {}

    for row in rows:
        try:
            tags = json.loads(row["extracted_tags"] or "{}")
        except Exception:
            continue
        for cat, data in tags.items():
            if data.get("sentiment") == "concerning":
                concern_counts[cat] = concern_counts.get(cat, 0) + 1
            elif data.get("sentiment") == "positive":
                positive_counts[cat] = positive_counts.get(cat, 0) + 1

    first_date = rows[-1]["created_at"][:10]
    last_date  = rows[0]["created_at"][:10]

    label_map = {
        "sleep": "Sleep", "mood": "Mood", "appetite": "Appetite",
        "medication": "Medication", "appointments": "Appointments",
        "social": "Social engagement", "physical": "Physical health", "behavior": "Behavior"
    }

    lines = [
        "CAREGIVER OBSERVATION SUMMARY",
        f"Period covered:  {first_date} through {last_date}",
        f"Total entries:   {total}",
        "",
        "AREAS OF CONCERN",
        "─" * 40
    ]
    if concern_counts:
        for cat, count in sorted(concern_counts.items(), key=lambda x: x[1], reverse=True):
            pct = round(count / total * 100)
            lines.append(f"  {label_map.get(cat, cat.title()):<22} {count}/{total} entries ({pct}%)")
    else:
        lines.append("  No recurring concerns flagged during this period.")

    lines += ["", "POSITIVE OBSERVATIONS", "─" * 40]
    if positive_counts:
        for cat, count in sorted(positive_counts.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {label_map.get(cat, cat.title()):<22} noted positively in {count} entries")
    else:
        lines.append("  No specific positive observations recorded.")

    lines += [
        "",
        "FOR THE CLINICIAN",
        "─" * 40,
        "This summary reflects observations reported by the caregiver through a",
        "structured daily logging tool. All information is the caregiver's own",
        "experience and should be reviewed alongside clinical assessment.",
        "",
        "The caregiver retains final say on all care decisions. This tool flags",
        "patterns and generates summaries to support — not replace — clinical judgment.",
        "",
        "[SANDBOX] In production, this narrative is drafted by Claude AI using the",
        "full text of each entry, not just keyword tags."
    ]

    return {
        "summary": "\n".join(lines),
        "entries_reviewed": total,
        "period_days": days,
        "concerns": concern_counts,
        "positives": positive_counts,
        "date_range": f"{first_date} to {last_date}"
    }

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", sandbox=SANDBOX_MODE)

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
    cur = conn.execute(
        "INSERT INTO entries (raw_note, extracted_tags, is_emergency_flagged, emergency_phrase) VALUES (?, ?, ?, ?)",
        (note, json.dumps(extraction["tags"]),
         1 if extraction["emergency"] else 0,
         extraction.get("emergency_phrase"))
    )
    entry_id = cur.lastrowid

    if extraction["emergency"]:
        conn.execute(
            "INSERT INTO alerts (entry_id, alert_type, alert_message) VALUES (?, 'emergency', ?)",
            (entry_id, f"Emergency language detected: \"{extraction['emergency_phrase']}\"")
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

    return jsonify({"id": entry_id, "extraction": extraction, "patterns": patterns})

@app.route("/api/entries", methods=["GET"])
def get_entries():
    limit  = int(request.args.get("limit", 20))
    offset = int(request.args.get("offset", 0))
    conn   = get_db()
    rows   = conn.execute(
        "SELECT id, created_at, raw_note, extracted_tags, corrected_tags, is_emergency_flagged FROM entries ORDER BY created_at DESC LIMIT ? OFFSET ?",
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
            "is_emergency": bool(r["is_emergency_flagged"])
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

@app.route("/api/patterns", methods=["GET"])
def get_patterns():
    days      = int(request.args.get("days", 7))
    threshold = int(request.args.get("threshold", 3))
    return jsonify({"patterns": detect_patterns(days, threshold)})

@app.route("/api/summary", methods=["POST"])
def generate_summary():
    data = request.get_json() or {}
    days = int(data.get("days", 14))
    return jsonify(mock_generate_summary(days))

@app.route("/api/alerts", methods=["GET"])
def get_alerts():
    conn = get_db()
    rows = conn.execute(
        """SELECT a.id, a.created_at, a.alert_type, a.alert_message,
                  a.deletion_status, a.entry_id, e.created_at as entry_date
           FROM alerts a LEFT JOIN entries e ON a.entry_id = e.id
           ORDER BY a.created_at DESC"""
    ).fetchall()
    count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    conn.close()
    return jsonify({
        "alerts": [{
            "id": r["id"], "created_at": r["created_at"],
            "alert_type": r["alert_type"], "alert_message": r["alert_message"],
            "deletion_status": r["deletion_status"],
            "entry_id": r["entry_id"], "entry_date": r["entry_date"]
        } for r in rows],
        "total": count
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

    sample_notes = [
        ("2026-06-03 20:14:00", "He didn't sleep again last night, maybe 2 or 3 hours total. Seemed really on edge this morning, didn't want to talk. Skipped his PT appointment. I'm getting worn out."),
        ("2026-06-04 21:02:00", "Better day today. He ate breakfast and lunch which is unusual lately. We watched TV together for a while. Still going to bed late but actually slept through. Small win."),
        ("2026-06-05 20:45:00", "Couldn't sleep until 4am, then up at 7. Very irritable all morning. Refused his morning meds, took them after lunch. I called the VA caregiver line just to talk to someone."),
        ("2026-06-06 21:30:00", "Bad night again, nightmares. Woke up sweating and was confused for a few minutes, didn't know where he was. Calmed down eventually. Didn't want to eat breakfast. Ate a little at dinner."),
        ("2026-06-07 20:10:00", "Therapy session today and he actually went, which is real progress. Mood was noticeably better afterward. He even laughed at something on TV. Ate a full dinner. Still not sleeping great but good day overall."),
        ("2026-06-08 21:15:00", "Slept okay, maybe 5 hours. Quiet day, mostly stayed inside and watched TV. A little withdrawn but not combative. Took his meds fine. I'm exhausted but holding up."),
        ("2026-06-09 20:55:00", "Terrible night. Heard him yelling in his sleep around 2am, flashback I think. Spent most of the day in his room and wouldn't come out. Refused lunch. By dinner he ate a little. He seems paranoid about something, not sure what."),
        ("2026-06-10 21:40:00", "He was really paranoid today, kept checking the windows. Wouldn't go outside. Didn't sleep well again, maybe 3 hours. Skipped dinner. I am worried about this pattern. His mood has been so low."),
        ("2026-06-11 20:30:00", "His brother came to visit and he really brightened up. Ate well, slept about 6 hours. Still hasn't been to PT. The social connection clearly helps him."),
        ("2026-06-12 21:00:00", "Up at 3am again. Restless all morning. Wouldn't take his medication, said he didn't need it. Seemed agitated. Missed his VA appointment. Behavior was erratic, pacing a lot. Hard day."),
        ("2026-06-13 20:20:00", "Slept a little better, 5 hours or so. He was calmer today. Took his meds without a fight. Ate breakfast. We sat outside for a bit in the afternoon which was nice. Mood still not great but manageable."),
        ("2026-06-14 21:10:00", "Nightmares again. He was on edge all day, couldn't settle. Skipped his PT appointment again. Barely ate. I'm worried about the sleep — this has been going on for weeks now."),
        ("2026-06-15 20:50:00", "Decent day. He ate three meals which hasn't happened in a while. Still nervous and jumpy but no major incidents. Took all his meds. Slept about 4 hours. His therapist called to check in which helped."),
        ("2026-06-16 20:00:00", "Rough night, up at 1am and 4am. He was withdrawn all day, stayed in his room mostly. Refused breakfast. Took meds after I reminded him twice. Mood is really low. I'm trying to stay patient but I'm running low too.")
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
            conn.execute(
                "INSERT INTO alerts (created_at, entry_id, alert_type, alert_message) VALUES (?, ?, 'emergency', ?)",
                (created_at, entry_id, f"Emergency language: \"{extraction['emergency_phrase']}\"")
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
    print()
    print("  CareLog — Caregiver AI Sandbox")
    print("  --------------------------------")
    print("  Running at:  http://localhost:5050")
    print("  Mode:        SANDBOX (AI calls simulated, no API key needed)")
    print("  Database:    caregiver.db (local SQLite)")
    print()
    app.run(debug=True, port=5050)
