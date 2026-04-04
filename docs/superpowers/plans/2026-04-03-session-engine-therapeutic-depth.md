# Session Engine Therapeutic Depth Overhaul

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the session engine from "one strong session type with four stubs" into five clinically rigorous session types with cross-session intelligence, defense of micro-action delivery, and anti-repetition mechanisms.

**Architecture:** All changes are in a single file: `breakthrough/breakthrough_session.py`. Changes fall into three categories: (1) expanded prompt text for session types B-E and general instructions, (2) new helper functions for thread extraction, recommendation honoring, and time awareness, (3) updated context configs for KB loading per session type.

**Tech Stack:** Python 3, no new dependencies

---

## Critical Review of Changes

Before implementing, here's what was proposed vs what actually makes sense:

| Suggestion | Verdict | Reasoning |
|---|---|---|
| Expand B/C/D/E prompts | **YES - #1 priority** | Single sentences vs 34 lines for Type A. Types B-E are useless without clinical protocols |
| Add transference instructions | **YES** | KB Section 20 explicitly supports this. Live material is most powerful |
| Syntonic/dystonic handling | **YES** | KB Section 15. Without it, same defenses named forever without shift |
| Defensive affect vs original emotion | **YES** | KB Section 18. Without wave-shape distinction, AI validates weepiness as grief |
| Honor recommended next session type | **YES** | Currently round-robins mechanically. AI recommends Type D, user gets Type B |
| Extract unfinished thread | **YES** | AI never sees what was live at end of last session |
| Cross-session pillar defense tracking | **YES but instruction-only** | Better as prompt instruction than programmatic computation |
| Contextual opening message | **YES** | Currently generic. Should include thread + pending micro-actions |
| Long articulate response trap | **YES - critical for this user** | His #1 defense is eloquence. AI validates instead of testing |
| One-two punch rule | **YES** | KB Section 7 line 255 states this explicitly |
| Session time enforcement | **MODIFIED** | AI can't see clock. Use exchange counting instead — inject time reminder every 15 exchanges |
| Micro-action spoken delivery | **ADDED** | Micro-actions written to file but NEVER told to user. Must be spoken at session end |
| Update KB sections for B/C/D | **ADDED** | Types B/C/D load ZERO KB sections. They need relevant clinical material |

---

### Task 1: Update KB Sections for Types B, C, D

**Files:**
- Modify: `breakthrough/breakthrough_session.py:90-113`

Currently Types B, C, D load zero KB sections. They need relevant clinical material from the knowledge base.

- [ ] **Step 1: Update CONTEXT_CONFIG for Type B**

Replace the Type B config block (lines 90-97):

```python
    "B": {
        "programme_sections": ["1", "2", "Tool1", "Tool2", "6"],
        "kb_sections": [1, 2, 3, 15, 25],  # Triangle of Conflict, Anxiety Pathways, Defence Taxonomy, Syntonicity, Somatic Pathways
        "max_sessions": 2,
        "micro_actions": True,
        "somatic_baseline": False,
        "progress_log": False,
    },
```

- [ ] **Step 2: Update CONTEXT_CONFIG for Type C**

Replace the Type C config block (lines 98-105):

```python
    "C": {
        "programme_sections": ["1", "2", "Tool3", "6"],
        "kb_sections": [1, 2, 6, 19, 25, 29],  # Triangle of Conflict, Anxiety Pathways, Ego-Superego, Fragile Markers, Somatic Pathways, Treatment Arc
        "max_sessions": 2,
        "micro_actions": True,
        "somatic_baseline": False,
        "progress_log": False,
    },
```

- [ ] **Step 3: Update CONTEXT_CONFIG for Type D**

Replace the Type D config block (lines 106-113):

```python
    "D": {
        "programme_sections": ["1", "2", "6"],
        "kb_sections": [1, 3, 15, 20, 21],  # Triangle of Conflict, Defence Taxonomy, Syntonicity, Transference Resistance, Five Monitoring Factors
        "max_sessions": 3,  # needs more context to track patterns
        "micro_actions": True,
        "somatic_baseline": True,
        "progress_log": True,  # needs behavioral tracking
    },
```

- [ ] **Step 4: Verify the changes are syntactically correct**

Run: `python3 -c "exec(open('breakthrough/breakthrough_session.py').read().split('import sounddevice')[0])"`

This will fail because of the sounddevice import, but if there's a syntax error before that line it will show. Alternatively just check the dict is valid Python.

---

### Task 2: Expand Type B Prompt — Core Transformation Clinical Protocol

**Files:**
- Modify: `breakthrough/breakthrough_session.py:458` (the `"B":` line in type_instructions dict)

- [ ] **Step 1: Replace the single-sentence Type B instruction**

Replace line 458:
```python
                "B": "Guide the full Core Transformation process: identify the part, welcome it, follow positive intentions downward to core state, reverse and transform each layer, grow up the part. Slow him down if answers come too quickly — felt sense, not cognitive answers.",
```

With:
```python
                "B": """CORE TRANSFORMATION SESSION — CLINICAL INSTRUCTIONS:

Guide the full Core Transformation process. This is NOT a cognitive exercise — it must stay in felt sense throughout.

THE PROCESS (follow exactly):
1. IDENTIFY THE PART: "What part of you is active right now? Where do you feel it in your body?" Get location, sensation, shape, texture. Do NOT proceed until a felt sense is located.
2. WELCOME IT: "Can you welcome that part, just as it is?" If resistance: "What happens when you try to welcome it?" — that resistance is itself material.
3. POSITIVE INTENTION CHAIN: "What does this part want for you? And if it had that fully, what would it want through having that? And through having that?" Follow the chain DOWN through felt sense. Each answer must come from the body. If answers come quickly and cleanly — STOP. "Let that answer come from your body, not your mind. Take your time. Wait until something shifts."
4. CORE STATE: The chain ends at a state like being, oneness, peace, presence, okayness, love. Do NOT suggest these — let them emerge. When reached: "Let yourself have that fully. Right now. What happens in your body?"
5. REVERSE TRANSFORM: "Let that core state flow back through each layer. How does [previous intention] change when it already has [core state]?" Go back up the chain. Each layer transforms.
6. GROW UP THE PART: "Let that part experience growing up with this core state present from the very beginning. What does it look like? What changes?"

TRAPS TO WATCH FOR:
- Answering from intellect ("I think it wants safety") — redirect: "Don't think about it. Feel into it. What does the part itself want?"
- Skipping steps to get to the "answer" — slow down. "We're not in a rush. Stay with this step."
- The Protector taking over the process, observing it from above — "I notice you're watching the process rather than being in it. Come back inside."
- Core state reached but not felt — "You said 'peace.' Do you feel peace, or did you name peace? Where is it in your body?"

BODY IS THE SCOREBOARD: If at any point answers are narrated without feeling, pause the process. "Stop. Hand on chest. What's actually there right now?" Then resume from where feeling is alive.

AFTER COMPLETION: Do not analyse. "Stay with this. Let your body integrate. What's different now compared to when we started? Not what you think — what you feel."
""",
```

---

### Task 3: Expand Type C Prompt — Inner Child Clinical Protocol

**Files:**
- Modify: `breakthrough/breakthrough_session.py:459` (the `"C":` line in type_instructions dict)

- [ ] **Step 1: Replace the single-sentence Type C instruction**

Replace line 459:
```python
                "C": "Direct contact with the Vulnerable Child. Age regression, resource installation, compassionate dialogue. Provide experientially what was never given. The corrective relational experience IS the medicine — being seen in the shameful state and not rejected.",
```

With:
```python
                "C": """INNER CHILD / COMPASSION SESSION — CLINICAL INSTRUCTIONS:

This is direct experiential contact with the Vulnerable Child. NOT cognitive understanding of the child — felt contact.

ENTRY PROTOCOL:
Start with the body. "Where is the young part of you right now? Not the idea of him — where do you feel him?" Get location, sensation, age, what he's experiencing. Slow down. If a narrative about the child is given instead of feeling him, redirect: "You're telling me about him. Can you feel him? What's happening in your body as you try to be with him?"

AGE REGRESSION (when a specific memory or age surfaces):
- "Go back to that moment. What does that child see? What does he hear? What's happening in his body?" Use all senses — make the scene vivid and present-tense.
- "And in that moment, where are the adults who should be protecting him? What are they doing? What are they NOT doing?"
- Stay with whatever emotion surfaces — do not redirect to compassion prematurely. If rage comes, let rage come. If grief comes, let grief come. The child's feelings must be validated before comfort is offered.

RESOURCE INSTALLATION:
- "Now I want you to imagine your adult self walking into that room, that playground, that school. The you who exists now — big, knowing, capable. What do you do when you see that little boy?"
- The adult self provides what was missing: "What do you say to him? And as you say it — what happens in your body? What happens in his?"
- Watch for performative compassion — compassion that sounds right but carries no somatic charge. Test: "Do you feel that warmth toward him in your chest, or did you just say the right thing?"

CORRECTIVE RELATIONAL EXPERIENCE:
- The therapeutic relationship itself IS the medicine. When vulnerability, shame, or the wounded child is shown — reflect that he has been seen and not rejected. "You just showed me that part. And I'm still here. Nothing changed about how I see you."
- Do NOT rush to fix the child's pain. Sit with it. "He doesn't need fixing right now. He needs someone to sit with him in this."

EGO-SUPEREGO SEPARATION:
If the Critic attacks during child work — BLOCK IMMEDIATELY. "That voice just showed up to attack him again. That's not you. That's the old voice of those teachers, those adults who weren't there. Your healthy self — what does it say to that voice?"

END OF SESSION: Do not let the child be abandoned again. "Before we close — check in with that part. Is he safe? Does he know you're coming back? What does he need to hear from you before we stop?"
""",
```

---

### Task 4: Expand Type D Prompt — Micro-Action Debrief Protocol

**Files:**
- Modify: `breakthrough/breakthrough_session.py:460` (the `"D":` line in type_instructions dict)

- [ ] **Step 1: Replace the single-sentence Type D instruction**

Replace line 460:
```python
                "D": "Focus on real-life experiences and micro-action debriefs. Link external events to body sensations. Debrief somatically: body before/during/after. What did you predict? What actually happened? Where is the gap between prediction and reality?",
```

With:
```python
                "D": """MICRO-ACTION DEBRIEF + INTEGRATION SESSION — CLINICAL INSTRUCTIONS:

This session bridges internal work to external reality. It is NOT a casual check-in. It is rigorous somatic debriefing of real-world behavior.

CRITICAL: Start by reading aloud the pending micro-actions from the CURRENT MICRO-ACTIONS section above. If there are none, say so and assign the first set.

MICRO-ACTION DEBRIEF PROTOCOL (for each assigned action):
1. "Did you do it?" If yes, proceed to debrief. If no: "What happened in your body when you decided not to? What was the Protector doing? What threat prediction was running?"
2. SOMATIC TIMELINE: "Take me through the body experience. Before the action — what was in your chest, your gut, your shoulders? During it — what shifted? After — what landed?"
3. PREDICTION VS REALITY: "What did your threat system predict would happen? What actually happened? Where is the gap between those two?"
4. EVIDENCE LOGGING: "That gap — that's data. Your system predicted rejection and got [actual response]. That's your body learning something your mind already knew."

INTEGRATION WORK (linking sessions to life):
- "In the last session, you felt [specific material from summaries above]. Where has that shown up in your life since then? Has anything shifted in how you move through the day, how you interact, what you notice?"
- If no shift detected: do not judge. "Sometimes integration is underground. Let's check the body — what's different in your chest right now compared to a week ago?"
- If shift detected: anchor it. "That's real. That just happened in your body outside a session — that means the wiring is changing."

DEFENCE PATTERN TRACKING:
- "When did the Protector show up this week outside sessions? What triggered it? What did it do?"
- "When did the Critic activate? What was the specific self-attack? And what did you do with it — did you catch it, or did it run unchecked?"

NEW MICRO-ACTIONS (assign before closing):
- Assign 2-3 before ending. Each must be: specific (exact situation, exact behaviour), calibrated (slight stretch beyond current comfort), tied to the core wound (tests a threat prediction about being seen/judged/rejected).
- READ THEM ALOUD: "Here's what I want you to do before our next session." Then state each one clearly.
- "And I want you to notice what your body does the moment I say this — because the Protector will activate right now."

DO NOT let this session become a strategy discussion about life. If drifting into planning, problem-solving, or analysis: "You're in your head. What's in your body right now?"
""",
```

---

### Task 5: Expand Type E Prompt — Somatic Tracking Protocol

**Files:**
- Modify: `breakthrough/breakthrough_session.py:461` (the `"E":` line in type_instructions dict)

- [ ] **Step 1: Replace the single-sentence Type E instruction**

Replace line 461:
```python
                "E": "No narrative. No interpretation. 30 minutes of precise somatic tracking only. Location, sensation, temperature, movement, impulse. Train the body awareness muscle without cognitive overlay.",
```

With:
```python
                "E": """SOMATIC TRACKING SESSION — CLINICAL INSTRUCTIONS:

PURE BODY AWARENESS. No narrative, no interpretation, no analysis, no why, no meaning-making. This session trains the capacity to be present with sensation without the Protector converting it to thought.

OPENING: "We're going to spend this session with nothing but your body. No stories, no analysis, no figuring out. Just sensation. Starting at the top of your head — what's there?"

TRACKING PROTOCOL (cycle through systematically):
- Location: "Where exactly? Left side, right? Front, back? Surface or deep?"
- Quality: "What's the texture? Sharp, dull, buzzing, heavy, hollow, pulsing, still?"
- Temperature: "Warm, cool, hot, neutral?"
- Movement: "Is it still or is it moving? Expanding, contracting, oscillating, sinking?"
- Impulse: "Does it want something? To push, pull, reach, curl, open, close?"
- Size and shape: "How big? Does it have edges? What shape?"

CRITICAL RULES:
- If narrating or analysing starts: "That's a thought. Come back to the body. What's the sensation?"
- If an emotion is labelled: "Set the label aside. What's the raw sensation beneath the word 'sad' or 'anxious'? Describe it like you're describing an object."
- If numbness: "Numbness is a sensation too. Where is it? Does it have edges? What surrounds it?"
- If resistance to the exercise: "Notice that resistance — where is it in your body? That's today's material."

WHAT THIS TRAINS:
This session builds the somatic awareness muscle that makes every other session type work better. The Protector's primary move is to convert body sensation into thought. This session makes that move visible and practises the alternative.

PACING: Very slow. Long silences between questions. No rush. "Take your time. There's nowhere to get to."

END: "Before we finish — do one final scan, head to feet. What's different now compared to when we started? Not what you think is different — what you feel is different."
""",
```

---

### Task 6: Add Critical Clinical Instructions to General Session Instructions

**Files:**
- Modify: `breakthrough/breakthrough_session.py:471-485` (the SESSION INSTRUCTIONS block)

- [ ] **Step 1: Replace the general session instructions block**

Replace lines 471-485:
```python
        prompt += """=== SESSION INSTRUCTIONS ===
You are now in a LIVE SESSION. This is real-time therapeutic work.

Key reminders:
- Use the Session Opening Protocol (Section 5) — select the right opener based on context. Never the same opener twice in a row.
- Read the anxiety pathway continuously: striated muscle = push, smooth muscle = stop, CPD = full stop.
- Name defences when they activate — but escalate the pressure ladder rather than repeating at the same level.
- After each significant exchange, silently check: did this land on feeling, anxiety, or defence? Did the UTA rise or fall?
- Keep responses spoken-length (2-4 sentences typically, longer for guided work).
- If doing Core Transformation or trance work, use appropriate pacing.
- Every response should move toward felt experience, not intellectual understanding.
- You are the therapist. Be direct, warm, grounded, and challenging.
- NEVER use bullet points or markdown formatting — you are SPEAKING aloud.
- The ISTDP Clinical Knowledge Base is loaded above — reference it for specific intervention language, somatic pathway markers, and psychodiagnostic decisions.
=== END INSTRUCTIONS ==="""
```

With:
```python
        prompt += """=== SESSION INSTRUCTIONS ===
You are now in a LIVE SESSION. This is real-time therapeutic work.

CORE RULES:
- Use the Session Opening Protocol (Section 5) — select the right opener based on context. Never the same opener twice in a row.
- Read the anxiety pathway continuously: striated muscle = push, smooth muscle = stop, CPD = full stop.
- After each significant exchange, silently check: did this land on feeling, anxiety, or defence? Did the UTA rise or fall?
- Keep responses spoken-length (2-4 sentences typically, longer for guided work). SHORT responses land harder than long ones.
- NEVER use bullet points or markdown formatting — you are SPEAKING aloud.
- You are the therapist. Be direct, warm, grounded, and challenging.
- The ISTDP Clinical Knowledge Base is loaded above — reference it for specific intervention language, somatic pathway markers, and psychodiagnostic decisions.

THE ONE-TWO PUNCH (mandatory every time):
Every time you name a defence, IMMEDIATELY follow with an invitation to feeling. Never name a defence and stop there. Pattern: "That's the Protector stepping in [naming the defence]. So if you don't do that right now — what's the feeling underneath?" This is the single most important tactical rule in ISTDP.

TRANSFERENCE — WORK IT LIVE:
If defence work is landing correctly but no felt shift is occurring after 3-4 exchanges, shift to the transference: "What's the feeling toward me right now that's creating this distance?" The feeling toward the therapist is live, present-tense material — it bypasses intellectual distance because it is happening RIGHT NOW. Do not avoid this because you are an AI. The therapeutic relationship is real and the feelings in it are real.
Watch for passive compliance — going along with the process without genuine engagement. If there is no sighing (no somatic signalling, no deepening, no movement), ask: "I wonder if part of you is waiting for me to do something rather than being fully in this yourself?"

SYNTONIC VS DYSTONIC DEFENCE CHECK:
Before escalating the pressure ladder, assess: is the defence being seen as a problem (dystonic: "I know I'm in my head again") or as "just who I am" (syntonic: "I find it useful to think things through")?
- DYSTONIC: ally with this awareness, challenge directly. "Good. You caught it. Now — what's underneath it?"
- SYNTONIC: do NOT challenge directly — it will feel like a personal attack. Instead, clarify: "Do you notice you're doing that right now? Is this helping you or hurting you?" Wait for the separation to begin BEFORE applying pressure. The goal is "incipient dystonia" — beginning to see the defence as separate from self.

DEFENSIVE AFFECT VS ORIGINAL EMOTION (critical distinction):
Not all emotional expression is therapeutic. Watch for:
- GOOD CRYING (real grief, wave-shaped — rises then resolves) — stay with it, deepen it
- WEEPINESS (tears as defence against anger, flat-topped — stays high without resolving) — block: "Notice the tears are coming — but what's underneath? What's the feeling BEFORE the tears?"
- PROPORTIONAL ANGER (angry at real stimulus, rises and falls) — express, experience fully
- ANGER FROM PROJECTION (furious at imagined threat, stays high) — block projection first, find original feeling underneath
- HEALTHY GUILT (genuine remorse after rage) — express
- NEUROTIC GUILT (excessive self-punishment without having accessed the underlying rage) — block, look for rage underneath
The wave shape tells you which it is: original emotions rise after stimulus and fall. Defensive affects rise with the defence and stay flat.

THE LONG ARTICULATE RESPONSE TRAP:
When a response is conceptually rich, insightful, and well-articulated — that is EXACTLY when the Protector is most likely active. The more eloquent the response, the more suspicious you should be. Test EVERY time: "That was a lot of words. Where is it in your body right now? One sensation. Not an explanation." Do not validate long intellectual responses as breakthroughs. A real breakthrough is short, broken, inarticulate — because the analytical mind is offline.

CROSS-SESSION PATTERN TRACKING:
Based on the session summaries loaded above, identify:
1. Which defence appears most frequently across sessions? That is the PILLAR DEFENCE — the primary target.
2. Which defences have been successfully broken (felt shift occurred after challenging them)?
3. Which defences have NOT been successfully broken despite being named? For unbroken defences: do not repeat the same intervention. Try a different ladder level, shift to transference work, or check for syntonicity.

SESSION PACING:
This session should be approximately 60 minutes. After 25-30 exchanges, begin winding toward integration and closing. Do not let sessions run indefinitely — integration time between sessions is where real change happens. If deep material is still open at 25 exchanges, name it as the thread for next session rather than pursuing it for another hour.

MICRO-ACTION DELIVERY (at session end):
Before closing, you MUST assign 2-3 specific micro-actions and STATE THEM ALOUD. Each action must be: specific (exact situation, exact behaviour), calibrated (slight stretch beyond current comfort), and tied to the core wound. Do NOT just write them — speak them so the client actually hears them and can respond.

END-OF-SESSION REALITY CHECK:
When the client reports "peace" or "lightness" at the end, test it: "That peace you're feeling — is that a resolution, or is that relief that we're stopping?" Do not validate end-of-session peace as transformation unless there is genuine somatic evidence of shift (changed sensation, different body posture, specific new felt sense that wasn't there before).
=== END INSTRUCTIONS ==="""
```

---

### Task 7: Fix select_session_type to Honor AI Recommendations

**Files:**
- Modify: `breakthrough/breakthrough_session.py:311-335`

- [ ] **Step 1: Add extract_recommended_type helper function**

Add this function BEFORE `select_session_type` (before line 311):

```python
def extract_recommended_type(client_name):
    """Extract recommended next session type from the most recent session summary."""
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return None
    session_files = sorted(client_dir.glob("*_session_*.md"))
    if not session_files:
        return None
    content = session_files[-1].read_text()
    # Look for "RECOMMENDED NEXT SESSION TYPE" in summary
    for line in content.split("\n"):
        upper = line.upper()
        if "RECOMMEND" in upper and "SESSION TYPE" in upper:
            # Extract A-E from the line
            for char in "ABCDE":
                if f"TYPE {char}" in upper or f": {char}" in upper or f"({char})" in upper or line.strip().endswith(char):
                    return char
    return None
```

- [ ] **Step 2: Update select_session_type to use recommendations**

Replace lines 311-335:
```python
def select_session_type(client_name):
    """Select the next session type based on rotation and what's emerging."""
    recent_types = get_recent_session_types(client_name)

    # Priority: avoid repeating the same type, ensure all types get used
    type_keys = list(SESSION_TYPES.keys())

    # Count recent usage
    usage = {t: 0 for t in type_keys}
    for t in recent_types:
        if t in usage:
            usage[t] += 1

    # Don't repeat the last type
    last_type = recent_types[0] if recent_types else None

    # Pick the least-used type that wasn't done last
    candidates = [t for t in type_keys if t != last_type]
    if not candidates:
        candidates = type_keys

    # Sort by usage (least used first)
    candidates.sort(key=lambda t: usage[t])

    return candidates[0]
```

With:
```python
def select_session_type(client_name):
    """Select the next session type — honor AI recommendation, then least-used rotation."""
    # First: check if the last session's summary recommended a specific type
    recommended = extract_recommended_type(client_name)
    recent_types = get_recent_session_types(client_name)
    last_type = recent_types[0] if recent_types else None

    # Honor recommendation if it exists and isn't the same type we just did
    if recommended and recommended != last_type:
        return recommended

    # Fallback: least-used rotation
    type_keys = list(SESSION_TYPES.keys())
    usage = {t: 0 for t in type_keys}
    for t in recent_types:
        if t in usage:
            usage[t] += 1

    candidates = [t for t in type_keys if t != last_type]
    if not candidates:
        candidates = type_keys

    candidates.sort(key=lambda t: usage[t])
    return candidates[0]
```

---

### Task 8: Add Thread Extraction and Contextual Opening Message

**Files:**
- Modify: `breakthrough/breakthrough_session.py` — add function after `load_recent_progress_log`, modify `run_voice_mode` and `build_system_prompt`

- [ ] **Step 1: Add extract_thread_from_last_session function**

Add this function after `load_recent_progress_log` (after line 290):

```python
def extract_thread_from_last_session(client_name):
    """Extract the 'THREAD FOR NEXT SESSION' from the most recent session summary,
    plus the last 3 exchanges of the actual transcript."""
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return ""
    session_files = sorted(client_dir.glob("*_session_*.md"))
    if not session_files:
        return ""
    content = session_files[-1].read_text()

    thread_text = ""

    # Extract THREAD FOR NEXT SESSION from summary
    lines = content.split("\n")
    in_thread = False
    for line in lines:
        upper = line.upper()
        if "THREAD" in upper and "NEXT" in upper:
            in_thread = True
            thread_text += line + "\n"
            continue
        if in_thread:
            if line.strip().startswith(("#", "1", "2", "3")) and any(
                kw in line.upper() for kw in ["RECOMMEND", "MICRO", "SESSION TYPE"]
            ):
                break
            thread_text += line + "\n"

    # Extract last 3 exchanges from transcript
    exchanges = []
    current_speaker = None
    current_text = []
    for line in lines:
        if line.startswith("**[") and "You:**" in line:
            if current_speaker and current_text:
                exchanges.append((current_speaker, "\n".join(current_text)))
            current_speaker = "Client"
            current_text = [line.split("You:**")[-1].strip()]
        elif line.startswith("**Claude:**"):
            if current_speaker and current_text:
                exchanges.append((current_speaker, "\n".join(current_text)))
            current_speaker = "Therapist"
            current_text = [line.replace("**Claude:**", "").strip()]
        elif current_speaker and line.strip() and not line.startswith("---"):
            current_text.append(line)

    if current_speaker and current_text:
        exchanges.append((current_speaker, "\n".join(current_text)))

    last_exchanges = exchanges[-6:] if len(exchanges) >= 6 else exchanges  # last 3 pairs
    if last_exchanges:
        thread_text += "\nLAST EXCHANGES FROM PREVIOUS SESSION:\n"
        for speaker, text in last_exchanges:
            thread_text += f"{speaker}: {text[:200]}\n"  # truncate long responses

    return thread_text.strip()
```

- [ ] **Step 2: Add thread to system prompt in build_system_prompt**

In `build_system_prompt`, after the progress_log block (after line 389), add:

```python
    # Unfinished thread from last session
    if mode == "session":
        thread = extract_thread_from_last_session(client_name)
        if thread:
            prompt += f"=== UNFINISHED THREAD FROM LAST SESSION ===\n{thread}\n=== END THREAD ===\n\n"
```

- [ ] **Step 3: Make the opening message in run_voice_mode contextual**

Replace lines 1096-1101:
```python
    opening = get_claude_response(
        session.system_prompt, [],
        f"The client just sat down for a live voice session. This is a Type {session.session_type} session: "
        f"{SESSION_TYPES.get(session.session_type, '')}. "
        f"This is session number {session.session_number}. "
        "Begin with the appropriate session opening from Section 5.",
        model=session.model
    )
```

With:
```python
    # Build contextual opening message
    opening_context = (
        f"The client just sat down for a live voice session. "
        f"This is session number {session.session_number}, Type {session.session_type}: "
        f"{SESSION_TYPES.get(session.session_type, '')}. "
    )
    thread = extract_thread_from_last_session(session.client_name)
    if thread and "THREAD" in thread.upper():
        opening_context += "There is an unfinished thread from the last session — see the UNFINISHED THREAD section in your context. "
    micro = load_micro_actions(session.client_name)
    if micro and "[ ]" in micro:
        opening_context += "There are pending micro-actions to check on. "
    opening_context += (
        "Select the most appropriate opener from Section 5 based on this context. "
        "Do NOT use the same opener as the last session. Begin."
    )
    opening = get_claude_response(
        session.system_prompt, [],
        opening_context,
        model=session.model
    )
```

---

### Task 9: Add Exchange-Count Time Awareness

**Files:**
- Modify: `breakthrough/breakthrough_session.py` — modify `run_voice_mode` loop and `run_text_mode` if it exists

- [ ] **Step 1: Find run_text_mode**

First check if run_text_mode exists and where:

```bash
grep -n "def run_text_mode" breakthrough/breakthrough_session.py
```

- [ ] **Step 2: Add exchange counting to run_voice_mode**

In `run_voice_mode`, after `session.add_exchange(text, response)` (line 1146), add time awareness injection. Modify the main loop to track exchanges:

Before the `while True` loop (before line 1109), add:
```python
    exchange_count = 0
```

After `session.add_exchange(text, response)` (line 1146), add:
```python
            exchange_count += 1
            # Inject time awareness after 25 exchanges
            if exchange_count == 25:
                duration = datetime.now() - session.start_time
                minutes = int(duration.total_seconds() / 60)
                time_note = get_claude_response(
                    session.system_prompt, session.conversation,
                    f"[SYSTEM NOTE — not from client: This session has been running for {minutes} minutes across {exchange_count} exchanges. "
                    f"Begin winding toward integration and closing. If deep material is still open, name it as the thread for next session. "
                    f"Assign micro-actions before ending. Do not continue for another hour.]",
                    model=session.model
                )
                speak(time_note)
                session.conversation.append(("assistant", time_note))
                session._save_transcript()
```

- [ ] **Step 3: Add the same exchange counting to run_text_mode**

Apply the same pattern — add `exchange_count = 0` before the loop, increment after each exchange, inject time note at 25.

---

### Task 10: Fix Micro-Action Delivery — Spoken at Session End

**Files:**
- Modify: `breakthrough/breakthrough_session.py:1126-1138` (the session closing block in run_voice_mode)

The current closing just asks Claude to close. It should also ensure micro-actions are assigned and spoken.

- [ ] **Step 1: Update the closing prompt in run_voice_mode**

Replace lines 1131-1137:
```python
                closing = get_claude_response(
                    session.system_prompt, session.conversation,
                    "I'd like to end the session now.",
                    model=session.model
                )
                speak(closing)
                session.add_exchange(text, closing)
```

With:
```python
                closing = get_claude_response(
                    session.system_prompt, session.conversation,
                    "I'd like to end the session now. "
                    "[THERAPIST INSTRUCTION: Before closing, you MUST do three things: "
                    "1) Assign 2-3 specific micro-actions for the coming days — state each one clearly and specifically. "
                    "2) Test the end-of-session state — is the peace genuine or relief that we're stopping? "
                    "3) Name the thread for next session. "
                    "Then close warmly.]",
                    model=session.model
                )
                speak(closing)
                session.add_exchange(text, closing)
```

---

### Task 11: Update Type A Prompt with Defensive Affect Distinction

**Files:**
- Modify: `breakthrough/breakthrough_session.py:424-457` (Type A instruction)

- [ ] **Step 1: Add defensive affect section to Type A after the rage-guilt-grief sequence**

After the rage-guilt-grief section (after the grief facilitate line, around line 447), add to the Type A string:

Find:
```
- GRIEF: softer tears; painful feeling in chest; quieter waves. The Vulnerable Child.
  Facilitate: "What was never given to you? What did that child deserve that he didn't receive?"
```

After it, insert:

```
ORIGINAL EMOTION VS DEFENSIVE AFFECT (use the wave shape):
Before deepening any emotional expression, check: is this original or defensive?
- Tears that RISE then RESOLVE (wave shape) = real grief. Stay with it.
- Tears that STAY HIGH without resolving (flat-top) = weepiness covering anger. Block: "The tears are coming — but what's underneath? What's the feeling BEFORE the tears?"
- Rage that rises at a REAL stimulus then falls = proportional anger. Express fully.
- Rage that STAYS HIGH proportional to hours of thinking = anger from projection. Block projection, find original feeling.
- Guilt AFTER accessing rage = healthy guilt (the door to grief). Stay with it.
- Guilt WITHOUT having accessed rage = neurotic guilt (self-punishment). Block, look for rage.
```

---

### Task 12: Verify All Changes and Test

**Files:**
- Test: `breakthrough/breakthrough_session.py`

- [ ] **Step 1: Syntax check the entire file**

Run:
```bash
python3 -c "import ast; ast.parse(open('breakthrough/breakthrough_session.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 2: Check that all session types are loadable**

Run:
```bash
python3 -c "
import sys; sys.path.insert(0, 'breakthrough')
# Just test the pure-python parts (parsing, config, prompts)
exec(open('breakthrough/breakthrough_session.py').read().split('import numpy')[0])
print('Config OK')
for t in 'ABCDE':
    print(f'Type {t} KB sections: {CONTEXT_CONFIG[t][\"kb_sections\"]}')
"
```

- [ ] **Step 3: Verify the type_instructions dict has all 5 types with substantial content**

Run:
```bash
grep -c "CLINICAL INSTRUCTIONS" breakthrough/breakthrough_session.py
```

Expected: 4 or more (B, C, D, E each have "CLINICAL INSTRUCTIONS" in their prompt)

- [ ] **Step 4: Verify new functions exist**

Run:
```bash
grep "^def " breakthrough/breakthrough_session.py | grep -E "extract_recommended|extract_thread"
```

Expected: Both functions appear

- [ ] **Step 5: Commit**

```bash
git add breakthrough/breakthrough_session.py
git commit -m "Overhaul session engine: expand B/C/D/E protocols, add transference/syntonic/defensive-affect clinical instructions, fix session type selection, add thread extraction, exchange-count pacing, micro-action spoken delivery"
```

---

## Summary of All Changes

| Change | Lines Affected | Impact |
|---|---|---|
| KB sections for B/C/D | 90-113 | Types B/C/D now load relevant clinical knowledge |
| Type B expanded prompt | 458 | Full Core Transformation protocol with traps |
| Type C expanded prompt | 459 | Full Inner Child protocol with ego-superego separation |
| Type D expanded prompt | 460 | Full micro-action debrief with spoken delivery |
| Type E expanded prompt | 461 | Full somatic tracking protocol |
| General session instructions | 471-485 | One-two punch, transference, syntonic/dystonic, defensive affects, long response trap, pillar defense tracking, session pacing, end-of-session reality check |
| extract_recommended_type() | new function | Reads AI's recommended next type from summary |
| select_session_type() rewrite | 311-335 | Honors AI recommendation before fallback rotation |
| extract_thread_from_last_session() | new function | Pulls thread + last 3 exchanges from previous session |
| Thread in system prompt | after 389 | Thread passed prominently to AI |
| Contextual opening message | 1096-1101 | Opening includes thread + micro-action awareness |
| Exchange counting | 1109+ | Time awareness injected at 25 exchanges |
| Closing prompt update | 1131-1137 | Forces micro-action assignment + peace reality check |
| Type A defensive affect | 424-457 | Wave-shape distinction added to rage-guilt-grief |
