# Section 1 — Understanding of Need and Solution Design

---

## The Problem

I am a retired Sergeant First Class from the United States Army. I have seen the military medical system from both sides — active duty care and the VA — and what I observed in both was the same problem: observations made at the point of care did not follow the patient. Notes did not transfer reliably between providers. When I sought care through the VA for conditions related to my service in the Middle East, what existed in my medical record was often one or two lines. Years of context reduced to a sentence. Without documentation, claims could not be made. It took a class action lawsuit — the burn pit legislation — before veterans in that situation could begin to receive recognition.

That is a documentation failure. And it is still happening today — not to the veterans themselves, but to the people caring for them.

Family and individual caregivers for veterans are often the most consistent observers of a veteran's daily condition. They see the sleep disruptions, the mood shifts, the missed appointments, the moments of crisis. But there is no structured way for them to capture those observations in real time, and no tool that turns what they see every day into something a VA provider can actually use. At every clinical visit, the caregiver is asked to remember. What they cannot remember, or cannot prove, does not become part of the record.

---

## The Gap

Existing support for veteran caregivers falls into two categories: human-staffed services — VA coaching, peer support programs, caregiver stipends — and symptom-tracking apps designed for the veteran's own use. Neither addresses the caregiver's role as an observer and communicator.

Fewer than 18% of military family caregivers use the financial stipends and support programs already available to them. The barrier is not eligibility — it is awareness and navigation. A caregiver who is exhausted, isolated, and managing a full day of care does not have time to research benefit programs or fill out detailed intake forms. They need something that works in the margins of their day.

---

## The Solution

CareLog is a browser-based AI tool built specifically for veteran and military family caregivers. The caregiver speaks or types naturally about their day — "he didn't sleep again, seemed on edge, skipped his PT appointment" — and the AI extracts structured observations automatically. Over time, the tool identifies patterns. When a concern repeats across multiple days, it is flagged. When urgent language appears, an emergency screen interrupts everything and surfaces the right resources immediately — Veterans Crisis Line, 911, VA Caregiver Support Line — based on the type of emergency and whether the patient is a veteran.

The tool distinguishes between four emergency types:
- **Mental health crisis** — suicidal language or self-harm, surfaces Veterans Crisis Line and crisis resources immediately
- **Physical emergency** — fall, injury, unresponsiveness, surfaces 911 and physical emergency guidance
- **Caregiver safety** — language indicating the caregiver is being threatened or harmed, surfaces 911 with guidance to leave the room first
- **Third-party violence** — language indicating the care recipient has harmed or threatened someone else, surfaces 911 with guidance to get others to safety first and not intervene physically

At any point, the caregiver can generate a clean, plain-language summary of recent observations formatted for a clinician, a VA provider, or a family member. They do not fill out a form. They do not try to remember two weeks of history under pressure. They hand over a document.

The tool also maintains a locked alert log. Emergency flags and repeating pattern alerts are permanently recorded and cannot be deleted by any single party. Every deletion request — approved or denied — is itself logged. This protects both the caregiver and the veteran.

---

## Current Technology Readiness Level

CareLog is at **Technology Readiness Level 3**. A working, demonstrable proof of concept has been built and tested. The tool runs in a browser, requires no installation, and operates with a Python backend and local database. AI extraction is implemented with a documented pathway to Claude AI (Anthropic Haiku model) for production use, with projected costs of approximately five to six cents per caregiver per month — a genuine affordability solution, not an estimate.

All core features are functional and demonstrable:
- Natural language note entry with real-time voice input
- Automated AI extraction of structured observations (sleep, mood, appetite, medication, appointments, social, physical, behavior)
- Pattern detection across entries over time
- Clinician-ready summary generation
- Four-branch emergency detection with appropriate resources per emergency type
- Patient profile system with veteran/civilian distinction
- Locked alert log with multi-party deletion requirement and audit trail
- Memory-aware greeting that references recent patterns by name

---

## User Input That Shaped the Design

The design reflects direct lived experience within the veteran and military community, including firsthand knowledge of how medical documentation failures affect care access, claims, and outcomes over years of active duty service and VA navigation.

Every design decision was tested against a single question: what does a caregiver actually need at the end of a hard day? The answer shaped the tool — no forms, no login friction, no clinical terminology required. The caregiver speaks or types in their own words, and the system does the rest.

Additional input was gathered from a working non-clinical caregiver with direct experience providing regular in-home care. Their feedback confirmed the core gap: observations made during visits are rarely captured in a format that follows the patient or informs the next provider interaction.

*[NOTE: Insert direct quote from caregiver feedback session here before submission.]*

---

## Supporting Research

- Fewer than 18% of military family caregivers access financial support programs for which they are eligible (RAND Corporation, Hidden Heroes report)
- The VA's own caregiver-facing technology — including the PTSD Coach app — is designed for the veteran's self-reporting, not the caregiver's observations
- No existing tool identified in market research captures caregiver observations in natural language and converts them into structured, clinician-ready documentation
- The PACT Act (2022) and related burn pit legislation demonstrated at scale what happens when service-connected conditions go undocumented — recognition came decades late for thousands of veterans

---

*[END SECTION 1]*
