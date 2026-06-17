# Section 3 — Usability and Integration

---

## Design Principle: Reduce Effort, Not Just Improve Efficiency

Most caregiving tools are designed to make documentation faster. CareLog is designed to make documentation effortless. These are not the same thing.

A caregiver who is exhausted, emotionally drained, and managing a full household at the end of the day will not use a faster form. They will not use a better-organized intake screen. They will use something that requires nothing from them beyond what they were already going to do — describe their day.

Every usability decision in CareLog flows from this principle. The tool should feel like talking to someone who is paying attention, not filling out paperwork.

---

## Error Prevention

**Natural language input eliminates structured input errors.**
The most common source of user error in caregiving documentation tools is the structured form — wrong field, wrong date, missed required entry, confusing clinical terminology. CareLog has no fields, no dropdowns, no required formats. The caregiver writes or speaks naturally. The AI handles interpretation. There is nothing to fill out incorrectly.

**Voice input with accumulation.**
The voice input feature records continuously, accumulates text across natural pauses in speech, and does not stop until the caregiver explicitly stops it. A pause to think does not erase what was said. The caregiver can speak for 30 seconds, pause, collect their thoughts, and continue — the full entry builds in the text box throughout. Voice commands ("log it," "log entry," "submit," "done") allow hands-free submission.

**Caregiver correction mechanism.**
If the AI misreads an entry — tags something as concerning that was not, or misses a topic entirely — the caregiver can correct it directly. Both the AI's original extraction and the caregiver's correction are saved. The AI's version is never silently overwritten. This maintains transparency and builds a correction record that improves future performance.

**The "I Don't Know" protocol.**
When the AI cannot confidently extract a specific observation from an entry, it returns no tag for that category rather than guessing. Ambiguous entries produce fewer tags, not wrong ones. The caregiver sees exactly what was and was not detected, and can add corrections if needed. The tool is designed to under-tag rather than over-tag — a missing tag is less harmful than a wrong one in a clinical context.

---

## Transparency

**Sandbox mode indicator.**
During testing, a visible banner identifies that AI responses are simulated. Caregivers and evaluators always know the current operating mode of the tool.

**Tag sourcing.**
Every extracted tag shows what specific language triggered it. The caregiver can see not just that "sleep" was flagged as concerning, but that the phrase "didn't sleep again" was the trigger. This makes the AI's reasoning visible and correctable.

**Emergency attribution.**
When the emergency screen fires, the exact language that triggered it is shown at the bottom of the screen. The caregiver knows why the alert appeared. This prevents confusion and supports informed decision-making.

**AI limitations stated explicitly.**
The tool states clearly throughout that it is not a clinical assessment, that only trained professionals can evaluate risk, and that the caregiver retains final say on all decisions. This language appears on the emergency screen, in the summary footer, and in the extraction result display.

---

## Usability in the Home Environment

**No installation required.**
CareLog runs entirely in a browser. There is nothing to download, no app store required, no account creation before first use. A caregiver can access it from any device — phone, tablet, laptop — by visiting a URL.

**Device flexibility.**
The interface is responsive and functions on mobile, tablet, and desktop. A caregiver who logs from their phone at midnight and reviews the summary on a laptop the next morning sees the same data on both devices.

**Low cognitive load design.**
Five tabs. One text box. One button. The interface presents only what is needed at the moment. Non-essential features do not appear until the caregiver navigates to them. The emergency screen, when triggered, removes all other interface elements entirely — the only thing on screen is the crisis information and the guidance.

**No ongoing login friction.**
Patient profiles are saved locally. The caregiver does not re-enter patient information at every visit. The system remembers who they are caring for and greets them by the patient's name with a memory-aware check-in based on recent entries.

---

## Integration into the Home

CareLog does not require integration with any external system to function. It works standalone, offline-capable for note entry, and requires only a basic internet connection for AI processing.

**Interoperability note:**
CareLog does not currently integrate with Electronic Medical Records (EMR) systems or assistive technology hardware. This is an intentional scope decision for Phase 1 — EMR integration requires institutional data access agreements and compliance infrastructure beyond the reach of a solo Phase 1 build. The clinician-ready summary generated by CareLog is designed to be printed, emailed, or read aloud by the caregiver at a clinical visit — a low-friction bridge to the clinical record without requiring system-level integration.

This approach is honest about current limitations while demonstrating a clear, practical pathway to clinical utility without overreaching.

---

## Realistic Usability Testing Plan

**Phase 1 (pre-submission):**
One non-clinical paid caregiver with direct in-home care experience reviewed the tool in person. Observations from that session:
- [INSERT DIRECT QUOTE FROM CAREGIVER SESSION]
- [INSERT OBSERVATION ABOUT WHERE THEY HESITATED OR WHAT THEY ASKED]
- [INSERT WHAT THEY SAID THEY WOULD ACTUALLY USE IT FOR]

**Phase 2 testing plan:**
- 5 to 10 caregivers recruited through veteran spouse networks and caregiver support communities
- Two-week minimum usage period per participant
- Feedback collected through direct conversation, not survey forms
- Specific attention to: phrasing the AI misses, emergency screen false positives, summary usefulness at clinical visits
- Iteration cycle: two weeks use, one week review and adjustment

**Accessibility:**
The tool uses system fonts, high-contrast color design, and large tap targets for mobile use. Voice input provides an alternative to typing for caregivers with limited dexterity or low literacy. No clinical terminology is required at any point of interaction.

---

## What "Not Applicable" Means Here

ACL's judging criteria reference EMR integration and assistive technology integration as areas of evaluation. For CareLog:

- **EMR integration:** Not applicable at Phase 1. Requires institutional data access and compliance infrastructure. Planned for consideration in Phase 3 pending partnership development.
- **Assistive technology integration:** Not applicable at Phase 1. The voice input feature built into the browser provides meaningful accessibility without requiring physical hardware integration.

These are honest scope boundaries, not oversights.

---

*[END SECTION 3]*
