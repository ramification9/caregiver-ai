# Section 4 — Alignment with Caregiver AI Principles

This section maps each of ACL's named Caregiver AI Principles explicitly to CareLog's design and functionality.

---

## Principle 1: Protect Privacy, Dignity, and Choice

**What ACL requires:** AI tools should clearly protect personal privacy, enable data portability, and respect dignity. Tools should have clear limits on what information is collected, how it is used, and who can see it. The care recipient should remain in control of their own data.

**How CareLog addresses it:**

- All data is stored locally in a private database tied to the caregiver's instance of the application. No data is shared with third parties, aggregated across users, or sold.
- The caregiver controls what is logged. Nothing is captured automatically — every entry requires the caregiver to initiate it.
- The care recipient's name and veteran status are stored as a patient profile. No medical record number, diagnosis, or insurance information is collected or required.
- The locked alert log protects dignity in both directions — it prevents a single bad actor from erasing evidence of either caregiver misconduct or false accusations. Deletion requires multi-party agreement, and every deletion request is permanently recorded regardless of outcome.
- The AI never contacts anyone, takes automated action, or makes decisions on behalf of the caregiver or care recipient. The human always decides.
- **AI processing and data transmission:** In production, note content is transmitted to the Anthropic API for AI extraction under Anthropic's published API terms (anthropic.com/legal/privacy). Anthropic does not retain, aggregate, or use API inputs for model training — this commitment is contractually binding, publicly documented, and independently verifiable. The note is processed and the structured result is returned; no content is stored by the AI provider beyond the duration of the request. Caregivers are informed of this before first use. The tool also supports sandbox mode, which performs keyword extraction with no external data transmission of any kind, giving caregivers the option to operate entirely offline if privacy requirements demand it.

---

## Principle 2: Support Human-in-the-Loop Accountability

**What ACL requires:** AI should augment, rather than replace, human judgment. Systems must include clear pathways for a caregiver to verify or override AI decisions.

**How CareLog addresses it:**

- The caregiver's final say is a hard rule built into every layer of the tool — stated explicitly in the interface, coded into the logic, and non-negotiable in the emergency response design.
- Every AI extraction is shown back to the caregiver before it is saved. The caregiver sees exactly what the AI tagged and can correct any tag they disagree with. Their correction is saved alongside the original AI output — the AI version is never silently overwritten.
- The emergency screen does not take action. It shows resources and guidance, then waits for the caregiver to decide. The tool never calls anyone, sends an alert, or escalates automatically.
- The summary is generated on demand, reviewed by the caregiver before sharing, and never transmitted anywhere without the caregiver's explicit action.
- The AI's uncertainty is visible. When the system cannot confidently extract a tag, it returns nothing rather than guessing. The caregiver can see what was and was not detected.

---

## Principle 3: Support Caregivers' Well-Being and Reduce Burden

**What ACL requires:** AI tools should assist caregivers with their responsibilities and support their physical and emotional well-being.

**How CareLog addresses it:**

- The tool eliminates the documentation burden entirely — no forms, no structured input, no clinical terminology required. The caregiver speaks or types naturally and the AI does the rest.
- Voice input allows hands-free logging. A caregiver who is physically exhausted, managing a task, or caring for someone in the same room can log an entry without sitting down at a screen.
- The memory-aware check-in greets the caregiver by the patient's name and references recent patterns — "You've mentioned sleep problems several times this week. How did last night go for Robert?" This reduces the cognitive load of remembering what matters.
- The post-crisis caregiver check-in feature recognizes that emergencies take a toll on the caregiver, not just the care recipient. After a crisis entry is logged and acknowledged, the tool checks in on the caregiver separately — not as a data collection step, but as a human acknowledgment that what they just went through was hard.
- The locked alert log removes the caregiver's burden of being the sole keeper of sensitive records. They do not have to remember, prove, or defend what happened — it is documented.

---

## Principle 4: Reflect Current Evidence and Best Practice, Protect Safety

**What ACL requires:** Tools should reflect current evidence and best practices and protect the safety of people receiving care.

**How CareLog addresses it:**

- Emergency detection is based on documented crisis language categories — mental health crisis, physical emergency, and caregiver safety — informed by established crisis response frameworks including the 988 Suicide and Crisis Lifeline protocols and VA crisis intervention guidance.
- The "while you wait" guidance on the emergency screen is flagged explicitly as pending clinical review. The tool does not present unreviewed guidance as authoritative. Final language will be reviewed by a licensed crisis professional before Phase 2 deployment.
- Emergency detection is deliberately conservative — the system is designed to under-trigger rather than miss a real crisis. A false positive that shows crisis resources unnecessarily is a manageable inconvenience. A false negative that misses a real emergency is not acceptable.
- The tool does not attempt clinical risk assessment. It recognizes urgent language and surfaces resources — it does not diagnose, evaluate, or classify risk level. That distinction is stated explicitly to the caregiver every time the emergency screen appears.
- Pattern detection flags concerns that repeat across multiple days, supporting early identification of trends that a clinical visit might otherwise miss.

---

## Principle 5: Ensure Affordability and Access

**What ACL requires:** AI tools should be affordable and accessible to support all caregivers and the recipients of care.

**How CareLog addresses it:**

- Projected operational cost using Claude AI (Anthropic Haiku model) with prompt caching: approximately five to six cents per caregiver per month. This is not an estimate — it is a calculation based on real API pricing applied to realistic daily usage and weekly summary generation. At this cost, the tool is viable for free access without subscription revenue.
- The tool runs in any standard web browser. No app store, no installation, no specific device required. A caregiver with a smartphone and a basic internet connection can use it.
- No account creation is required before first use. The caregiver sets up a patient profile and starts logging immediately.
- Voice input provides an alternative to typing for caregivers with limited dexterity, low literacy, or who are managing other tasks simultaneously.
- Future affordability pathways include existing VA Caregiver Support Program stipends as a potential funding mechanism — the same programs that fewer than 18% of eligible caregivers currently access. CareLog's summary feature could directly support a caregiver's ability to document and navigate those benefit applications.

---

## Principle 6: Promote Safety, Reliability, and Transparency — Avoid Bias

**What ACL requires:** The performance of AI tools should be transparent and designed to avoid bias and adverse impacts on caregivers and care recipients.

**How CareLog addresses it:**

- The AI's reasoning is always visible. Every extracted tag shows the specific language that triggered it. The caregiver can see not just what was flagged but why.
- Sandbox mode is clearly labeled throughout testing. Caregivers and evaluators always know the current operating mode of the tool.
- Bias monitoring is built into the Phase 2 evaluation plan — extraction and emergency detection performance will be reviewed across gender, military branch and era, caregiver communication style, and crisis language variation to identify and address any demographic gaps.
- The caregiver correction mechanism creates a living bias log. Every correction the caregiver makes is a documented instance where the AI's interpretation diverged from the caregiver's intent. These corrections directly inform extraction improvements.
- The tool does not make decisions. It surfaces information. Bias in the AI output affects what the caregiver sees — not what happens to the care recipient. The human remains the decision point.

---

## Principle 7: Actively Engage Caregivers Throughout Design and Development

**What ACL requires:** Approaches should actively engage caregivers throughout all stages of design and development and demonstrate a clear understanding of caregivers' challenges, needs, preferences, and limitations.

**How CareLog addresses it:**

- The core problem the tool solves — observations lost between providers, notes that don't transfer, caregivers repeating themselves at every visit — was identified through direct lived experience inside the military medical system, not through market research or assumption.
- Every design decision was tested against the question: what does a caregiver actually need at the end of a hard day? The answer eliminated forms, eliminated login friction, eliminated clinical terminology, and produced a tool that asks only what the caregiver was already going to say.
- Pre-submission testing included a working session with a non-clinical paid caregiver with direct in-home care experience. Their feedback confirmed the core gap and informed the interface design.
  - *[INSERT CAREGIVER QUOTE HERE]*
- The Phase 2 testing plan centers caregiver behavior — not accuracy metrics — as the primary signal. If caregivers stop logging, the tool is not working, regardless of what performance numbers say.
- The caregiver correction mechanism ensures caregivers remain active participants in the tool's accuracy over time, not passive users of a system they cannot influence.

---

*[END SECTION 4]*
