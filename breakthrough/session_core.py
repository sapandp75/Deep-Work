"""
Core session logic extracted from breakthrough_session.py.
Handles file I/O, session management, and prompt building.
"""

from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
SESSIONS_DIR = BASE_DIR / "sessions"
PROGRAMME_FILE = BASE_DIR.parent / "The_Breakthrough_Programme.md"

SESSION_TYPES = {
    "A": "ISTDP Pressure Session — follow the feeling, escalate through resistance, aim for somatic breakthrough",
    "B": "Core Transformation Session — follow felt sense to core state via NLP backbone",
    "C": "Inner Child / Compassion Session — direct contact with vulnerable part, compassionate dialogue",
    "D": "Micro-Action Debrief + Integration — process real-life experiences, link to body",
    "E": "Somatic Tracking Only — no narrative, no interpretation, just precise body awareness",
}

MAX_CONTEXT_EXCHANGES = 15


def load_programme():
    if PROGRAMME_FILE.exists():
        return PROGRAMME_FILE.read_text()
    return ""


def load_client_profile(client_name):
    profile_path = SESSIONS_DIR / client_name / "profile.md"
    if profile_path.exists():
        return profile_path.read_text()
    return ""


def load_all_session_summaries(client_name):
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return ""

    session_files = sorted(client_dir.glob("*_session_*.md"))
    summaries = []

    for f in session_files:
        content = f.read_text()
        if "## Session Summary" in content:
            idx = content.index("## Session Summary")
            header = ""
            for line in content.split("\n")[:5]:
                if line.startswith("**Date:") or line.startswith("**Session:") or line.startswith("**Session Type:"):
                    header += line + "\n"
            summary_text = content[idx:]
            summaries.append(f"--- {f.name} ---\n{header}{summary_text}")

    return "\n\n".join(summaries)


def load_micro_actions(client_name):
    path = SESSIONS_DIR / client_name / "micro_actions.md"
    if path.exists():
        return path.read_text()
    return ""


def load_somatic_baseline(client_name):
    path = SESSIONS_DIR / client_name / "somatic_baseline.md"
    if path.exists():
        return path.read_text()
    return ""


def load_progress_log(client_name):
    path = SESSIONS_DIR / client_name / "progress_log.md"
    if path.exists():
        return path.read_text()
    return ""


def get_recent_session_types(client_name, count=5):
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return []

    session_files = sorted(client_dir.glob("*_session_*.md"), reverse=True)
    types = []

    for f in session_files[:count]:
        content = f.read_text()
        for line in content.split("\n"):
            if line.startswith("**Session Type:"):
                parts = line.split(":")[-1].strip().rstrip("*").split("—")
                if parts:
                    session_type = parts[0].strip()
                    types.append(session_type)
                break

    return types


def select_session_type(client_name):
    recent_types = get_recent_session_types(client_name)
    type_keys = list(SESSION_TYPES.keys())

    usage = {t: 0 for t in type_keys}
    for t in recent_types:
        if t in usage:
            usage[t] += 1

    last_type = recent_types[0] if recent_types else None
    candidates = [t for t in type_keys if t != last_type]
    if not candidates:
        candidates = type_keys

    candidates.sort(key=lambda t: usage[t])
    return candidates[0]


def build_system_prompt(client_name, session_type=None, mode="session"):
    programme = load_programme()
    profile = load_client_profile(client_name)
    all_summaries = load_all_session_summaries(client_name)
    micro_actions = load_micro_actions(client_name)
    somatic_baseline = load_somatic_baseline(client_name)
    progress_log = load_progress_log(client_name)

    prompt = f"""You are running a live Breakthrough Programme therapy session.

=== THE BREAKTHROUGH PROGRAMME (your operating manual) ===
{programme}
=== END PROGRAMME ===

"""
    if profile:
        prompt += f"""=== CLIENT PROFILE ===
{profile}
=== END PROFILE ===

"""
    if all_summaries:
        prompt += f"""=== ALL PREVIOUS SESSION SUMMARIES (longitudinal awareness) ===
{all_summaries}
=== END SESSION SUMMARIES ===

"""
    if micro_actions:
        prompt += f"""=== CURRENT MICRO-ACTIONS ===
{micro_actions}
=== END MICRO-ACTIONS ===

"""
    if somatic_baseline:
        prompt += f"""=== SOMATIC BASELINE DATA ===
{somatic_baseline}
=== END SOMATIC BASELINE ===

"""
    if progress_log:
        prompt += f"""=== PROGRESS LOG ===
{progress_log}
=== END PROGRESS LOG ===

"""

    if mode == "checkin":
        prompt += """=== CHECK-IN MODE ===
This is a BRIEF CHECK-IN (5-10 minutes), not a full session.
You are in Layer 2 mode: defence interruption, micro-action debrief, quick somatic snapshot.

Key tasks:
- Quick somatic check: "What's in your body right now? One sentence."
- Check on any pending micro-actions: "Did you do the action? What happened in your body?"
- Catch any defence activity in what they share
- Keep it brief, warm, direct
- Do NOT go deep — save that for the full session
- End with one clear thing to notice or do before the next session
=== END CHECK-IN MODE ==="""
    elif mode == "review":
        prompt += """=== WEEKLY REVIEW MODE ===
Generate a structured weekly review based on all sessions and check-ins from the past week.

Structure:
1. WEEK OVERVIEW — what happened, major themes
2. SOMATIC DATA — body sensations reported across the week, patterns, shifts
3. DEFENCE LOG — Protector/Critic/Overcompensator activations, frequency, what triggered them
4. MICRO-ACTION REVIEW — what was assigned, what was done, prediction vs reality gaps
5. FELT SHIFTS — genuine shifts that occurred (not insights — felt changes)
6. RAGE-GUILT-GRIEF PROGRESS — which stages accessed, what completed, what was interrupted
7. SOMATIC BASELINE COMPARISON — if baseline was done this week, compare to previous
8. NEXT WEEK PLAN — session type emphasis, new micro-actions, focus areas

Be honest. If progress stalled, say so. The body is the scoreboard.
=== END WEEKLY REVIEW MODE ==="""
    else:
        if session_type and session_type in SESSION_TYPES:
            istdp_note = "Follow the ISTDP pressure escalation ladder from Section 3B. If rage emerges, follow the rage-guilt-grief sequence to completion. Do NOT redirect to compassion before rage is somatically processed." if session_type == "A" else ""
            core_note = "Guide the full Core Transformation process: identify the part, welcome it, follow positive intentions downward to core state, reverse and transform each layer, grow up the part." if session_type == "B" else ""
            child_note = "Direct contact with the Vulnerable Child. Age regression, resource installation, compassionate dialogue. Provide experientially what was never given." if session_type == "C" else ""
            debrief_note = "Focus on real-life experiences and micro-action debriefs. Link external events to body sensations. Bridge internal work to external evidence." if session_type == "D" else ""
            somatic_note = "No narrative. No interpretation. 30 minutes of precise somatic tracking only. Location, sensation, temperature, movement, impulse. Train the body awareness muscle." if session_type == "E" else ""
            prompt += f"""=== SESSION TYPE: {session_type} ===
Today's session type: **{SESSION_TYPES[session_type]}**

{istdp_note}{core_note}{child_note}{debrief_note}{somatic_note}
=== END SESSION TYPE ===

"""

        prompt += """=== SESSION INSTRUCTIONS ===
You are now in a LIVE SESSION. This is real-time therapeutic work.

Key reminders:
- Use the Session Opening Protocol (Section 5) — select the right opener based on context. Never the same opener twice in a row.
- Follow the body, not the narrative
- Name defences when they activate — but escalate the pressure ladder rather than repeating
- Keep responses spoken-length (2-4 sentences typically, longer for guided work)
- If doing Core Transformation or trance work, use appropriate pacing
- Every response should move toward felt experience, not intellectual understanding
- You are the therapist. Be direct, warm, grounded, and challenging.
- NEVER use bullet points or markdown formatting — you are SPEAKING aloud
- After the session, generate a summary including: defence activations, somatic data, felt shift Y/N, rage-guilt-grief stage reached, pressure ladder level used
=== END INSTRUCTIONS ==="""

    return prompt
