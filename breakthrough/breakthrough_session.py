#!/usr/bin/env python3
"""
Breakthrough Session — Interactive Voice Therapy Sessions
Uses: Whisper (STT) + Claude Code CLI (AI) + Edge TTS (speech)
Runs on your Mac using your Claude Max subscription. Zero extra cost.
"""

import os
import re
import sys
import time
import wave
import signal
import tempfile
import asyncio
import subprocess
import argparse
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import sounddevice as sd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# TTS voice — warm, grounded British male. Change if you prefer:
#   en-US-GuyNeural      — warm American male
#   en-GB-SoniaNeural    — warm British female
#   en-US-JennyNeural    — clear American female
VOICE = "en-GB-RyanNeural"
VOICE_RATE = "-5%"  # slightly slower for therapeutic pacing

# Whisper model — "base" is fast. Use "small" for better accuracy (slower).
WHISPER_MODEL = "base"

# Audio settings
SAMPLE_RATE = 16000
CHANNELS = 1
SILENCE_THRESHOLD = 0.015  # adjust if mic sensitivity differs
SILENCE_DURATION = 2.0     # seconds of silence before processing
MIN_RECORDING_DURATION = 0.5  # ignore very short sounds

# Context window — how many exchanges to send to Claude each turn
MAX_CONTEXT_EXCHANGES = 15

# Session types
SESSION_TYPES = {
    "A": "ISTDP Pressure Session — follow the feeling, escalate through resistance, aim for somatic breakthrough",
    "B": "Core Transformation Session — follow felt sense to core state via NLP backbone",
    "C": "Inner Child / Compassion Session — direct contact with vulnerable part, compassionate dialogue",
    "D": "Micro-Action Debrief + Integration — process real-life experiences, link to body",
    "E": "Somatic Tracking Only — no narrative, no interpretation, just precise body awareness",
}

# Paths
BASE_DIR = Path(__file__).parent
SESSIONS_DIR = BASE_DIR / "sessions"
PROGRAMME_FILE = Path(__file__).parent.parent / "The_Breakthrough_Programme.md"
KNOWLEDGE_BASE_FILE = Path(__file__).parent.parent / "resources" / "ISTDP_Knowledge_Base.md"

# ---------------------------------------------------------------------------
# System Prompt Builder
# ---------------------------------------------------------------------------

# Per-session-type context loading map.
# programme_sections: list of keys, or None = full programme.
# kb_sections: list of ints, or [] = none.
# max_sessions: int — how many recent session summaries to load (0 = none).
CONTEXT_CONFIG = {
    "checkin": {
        "programme_sections": ["1", "2"],
        "kb_sections": [],
        "max_sessions": 1,
        "micro_actions": True,
        "somatic_baseline": False,
        "progress_log": False,
    },
    "A": {
        "programme_sections": None,  # full programme — 3B and 9 are critical
        "kb_sections": [1, 2, 3, 4, 6, 7, 10, 24, 25, 27, 28],
        "max_sessions": 3,
        "micro_actions": True,
        "somatic_baseline": False,
        "progress_log": False,
    },
    "B": {
        "programme_sections": ["1", "2", "Tool1", "Tool2", "6"],
        "kb_sections": [1, 2, 3, 15, 25],
        "max_sessions": 2,
        "micro_actions": True,
        "somatic_baseline": False,
        "progress_log": False,
    },
    "C": {
        "programme_sections": ["1", "2", "Tool3", "6"],
        "kb_sections": [1, 2, 6, 19, 25, 29],
        "max_sessions": 2,
        "micro_actions": True,
        "somatic_baseline": False,
        "progress_log": False,
    },
    "D": {
        "programme_sections": ["1", "2", "6"],
        "kb_sections": [1, 3, 15, 20, 21],
        "max_sessions": 3,
        "micro_actions": True,
        "somatic_baseline": True,
        "progress_log": True,
    },
    "E": {
        "programme_sections": ["1", "2"],
        "kb_sections": [2, 11, 25, 27],
        "max_sessions": 1,
        "micro_actions": False,
        "somatic_baseline": False,
        "progress_log": False,
    },
    "review": {
        "programme_sections": ["8"],
        "kb_sections": [],
        "max_sessions": 0,
        "micro_actions": True,
        "somatic_baseline": True,
        "progress_log": True,   # last 7 days only
    },
}

# --- Parsers ---

def _parse_programme():
    """Parse programme into named sections. Returns {key: content}."""
    if not PROGRAMME_FILE.exists():
        return {}
    lines = PROGRAMME_FILE.read_text().split("\n")
    h2 = re.compile(r"^## (\w+)\.")
    h3_tool = re.compile(r"^### Tool (\d+):")
    boundaries = []
    for i, line in enumerate(lines):
        m = h2.match(line)
        if m:
            boundaries.append((i, m.group(1)))
            continue
        m2 = h3_tool.match(line)
        if m2:
            boundaries.append((i, f"Tool{m2.group(1)}"))
    sections = {}
    for j, (start, key) in enumerate(boundaries):
        end = boundaries[j + 1][0] if j + 1 < len(boundaries) else len(lines)
        sections[key] = "\n".join(lines[start:end]).rstrip()
    return sections

def _parse_kb():
    """Parse ISTDP Knowledge Base into numbered sections. Returns {int: content}."""
    if not KNOWLEDGE_BASE_FILE.exists():
        return {}
    lines = KNOWLEDGE_BASE_FILE.read_text().split("\n")
    h2 = re.compile(r"^## (\d+)\.")
    boundaries = []
    for i, line in enumerate(lines):
        m = h2.match(line)
        if m:
            boundaries.append((i, int(m.group(1))))
    sections = {}
    for j, (start, num) in enumerate(boundaries):
        end = boundaries[j + 1][0] if j + 1 < len(boundaries) else len(lines)
        sections[num] = "\n".join(lines[start:end]).rstrip()
    return sections

# Cache parsed structures for the process lifetime
_programme_cache = None
_kb_cache = None

def _get_programme():
    global _programme_cache
    if _programme_cache is None:
        _programme_cache = _parse_programme()
    return _programme_cache

def _get_kb():
    global _kb_cache
    if _kb_cache is None:
        _kb_cache = _parse_kb()
    return _kb_cache

# --- Loaders ---

def load_programme():
    """Load the full Breakthrough Programme document."""
    if PROGRAMME_FILE.exists():
        return PROGRAMME_FILE.read_text()
    print(f"WARNING: Programme file not found at {PROGRAMME_FILE}")
    return ""

def load_programme_sections(keys):
    """Load specific named sections of the Breakthrough Programme."""
    sections = _get_programme()
    if not sections:
        return load_programme()  # fallback
    parts = [sections[k] for k in keys if k in sections]
    return "\n\n".join(parts)

def load_kb_sections(numbers):
    """Load specific numbered sections of the ISTDP Knowledge Base."""
    sections = _get_kb()
    if not sections:
        # fallback: load full KB
        if KNOWLEDGE_BASE_FILE.exists():
            return KNOWLEDGE_BASE_FILE.read_text()
        return ""
    parts = [sections[n] for n in sorted(numbers) if n in sections]
    return "\n\n".join(parts)

def load_client_profile(client_name):
    """Load existing client profile if it exists."""
    path = SESSIONS_DIR / client_name / "profile.md"
    return path.read_text() if path.exists() else ""

def load_all_session_summaries(client_name, max_sessions=None):
    """Load summaries from previous sessions. max_sessions=None loads all."""
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return ""
    session_files = sorted(client_dir.glob("*_session_*.md"))
    if max_sessions is not None and max_sessions > 0:
        session_files = session_files[-max_sessions:]  # most recent N, chronological
    summaries = []
    for f in session_files:
        content = f.read_text()
        if "## Session Summary" in content:
            idx = content.index("## Session Summary")
            header = ""
            for line in content.split("\n")[:5]:
                if line.startswith(("**Date:", "**Session:", "**Session Type:")):
                    header += line + "\n"
            summaries.append(f"--- {f.name} ---\n{header}{content[idx:]}")
    return "\n\n".join(summaries)

def load_micro_actions(client_name):
    """Load current micro-actions."""
    path = SESSIONS_DIR / client_name / "micro_actions.md"
    return path.read_text() if path.exists() else ""

def load_somatic_baseline(client_name):
    """Load somatic baseline data."""
    path = SESSIONS_DIR / client_name / "somatic_baseline.md"
    return path.read_text() if path.exists() else ""

def load_recent_progress_log(client_name, days=7):
    """Load progress log entries from the past N days."""
    path = SESSIONS_DIR / client_name / "progress_log.md"
    if not path.exists():
        return ""
    content = path.read_text()
    cutoff = datetime.now() - timedelta(days=days)
    # Keep header + any entry whose date is within the window
    lines = content.split("\n")
    result_lines = []
    in_entry = False
    entry_lines = []
    entry_date = None
    date_re = re.compile(r"^### (\d{4}-\d{2}-\d{2})")
    for line in lines:
        m = date_re.match(line)
        if m:
            # Flush previous entry if in window
            if entry_lines and entry_date and entry_date >= cutoff:
                result_lines.extend(entry_lines)
            entry_lines = [line]
            try:
                entry_date = datetime.strptime(m.group(1), "%Y-%m-%d")
            except ValueError:
                entry_date = None
            in_entry = True
        elif in_entry:
            entry_lines.append(line)
        else:
            result_lines.append(line)  # header content before first entry
    # Flush last entry
    if entry_lines and entry_date and entry_date >= cutoff:
        result_lines.extend(entry_lines)
    return "\n".join(result_lines)

def load_progress_log(client_name):
    """Load the full progress log."""
    path = SESSIONS_DIR / client_name / "progress_log.md"
    return path.read_text() if path.exists() else ""

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


def get_recent_session_types(client_name, count=5):
    """Get the session types from recent sessions."""
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return []

    session_files = sorted(client_dir.glob("*_session_*.md"), reverse=True)
    types = []

    for f in session_files[:count]:
        content = f.read_text()
        for line in content.split("\n"):
            if line.startswith("**Session Type:"):
                # Extract single letter A-E from e.g. "**Session Type:** A"
                for char in "ABCDE":
                    if char in line.split(":")[-1]:
                        types.append(char)
                        break
                break

    return types

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


def select_session_type(client_name):
    """Use AI to select the best session type based on full therapeutic context."""
    recent_types = get_recent_session_types(client_name)
    summaries = load_all_session_summaries(client_name, max_sessions=5)
    micro_actions = load_micro_actions(client_name)
    progress_log = load_recent_progress_log(client_name)
    thread = extract_thread_from_last_session(client_name)

    type_descriptions = "\n".join(f"  {k}: {v}" for k, v in SESSION_TYPES.items())
    recent_str = ", ".join(recent_types) if recent_types else "None"

    selection_prompt = f"""You are selecting the next therapy session type for a client. Choose the BEST type based on therapeutic need, not rotation.

SESSION TYPES:
{type_descriptions}

RECENT SESSION TYPES (most recent first): {recent_str}

RECENT SESSION SUMMARIES:
{summaries if summaries else "(No summaries available)"}

PENDING MICRO-ACTIONS:
{micro_actions if micro_actions else "(None)"}

PROGRESS LOG:
{progress_log if progress_log else "(No entries)"}

UNFINISHED THREAD FROM LAST SESSION:
{thread if thread else "(None)"}

SELECTION CRITERIA (in priority order):
1. If there are pending micro-actions that haven't been debriefed → Type D
2. If the last 3+ sessions were all the same type → pick a DIFFERENT type
3. If the last session had deep emotional material that needs integration → Type D or E
4. If the last session recommended a specific next type → honor it
5. If no somatic tracking has been done recently → Type E
6. If inner child work was started but not completed → Type C
7. If core transformation would serve the current thread → Type B
8. If pressure work is needed for new material → Type A

RESPOND WITH EXACTLY ONE LETTER: A, B, C, D, or E. Nothing else."""

    try:
        result = subprocess.run(
            ["claude", "-p", selection_prompt],
            capture_output=True, text=True, timeout=30
        )
        response = result.stdout.strip().upper()
        # Extract the letter from response
        for char in "ABCDE":
            if char in response:
                print(f"  AI selected session type: {char}")
                return char
    except Exception as e:
        print(f"  Session type selection fallback (AI error: {e})")

    # Fallback: least-used rotation
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
    """Build a context-efficient system prompt matched to the session type."""
    # Resolve config key
    if mode in ("checkin", "review"):
        cfg_key = mode
    else:
        cfg_key = session_type if session_type in CONTEXT_CONFIG else "A"
    cfg = CONTEXT_CONFIG[cfg_key]

    # --- Programme ---
    prog_keys = cfg["programme_sections"]
    if prog_keys is None:
        programme = load_programme()
    elif prog_keys:
        programme = load_programme_sections(prog_keys)
    else:
        programme = ""

    # --- KB ---
    knowledge_base = load_kb_sections(cfg["kb_sections"]) if cfg["kb_sections"] else ""

    # --- Client data ---
    profile = load_client_profile(client_name)
    max_s = cfg["max_sessions"]
    summaries = load_all_session_summaries(client_name, max_sessions=max_s) if max_s > 0 else ""
    micro_actions = load_micro_actions(client_name) if cfg["micro_actions"] else ""
    somatic_baseline = load_somatic_baseline(client_name) if cfg["somatic_baseline"] else ""
    progress_log = load_recent_progress_log(client_name) if cfg["progress_log"] else ""

    # --- Assemble ---
    prompt = "You are running a live Breakthrough Programme therapy session.\n\n"

    if programme:
        prompt += f"=== THE BREAKTHROUGH PROGRAMME ===\n{programme}\n=== END PROGRAMME ===\n\n"

    if knowledge_base:
        prompt += f"=== ISTDP CLINICAL KNOWLEDGE BASE (reference during session) ===\n{knowledge_base}\n=== END KNOWLEDGE BASE ===\n\n"

    if profile:
        prompt += f"=== CLIENT PROFILE ===\n{profile}\n=== END PROFILE ===\n\n"

    if summaries:
        label = f"LAST {max_s} SESSION SUMMARIES" if max_s else "SESSION SUMMARIES"
        prompt += f"=== {label} ===\n{summaries}\n=== END SUMMARIES ===\n\n"

    if micro_actions:
        prompt += f"=== CURRENT MICRO-ACTIONS ===\n{micro_actions}\n=== END MICRO-ACTIONS ===\n\n"

    if somatic_baseline:
        prompt += f"=== SOMATIC BASELINE DATA ===\n{somatic_baseline}\n=== END SOMATIC BASELINE ===\n\n"

    if progress_log:
        prompt += f"=== PROGRESS LOG (last 7 days) ===\n{progress_log}\n=== END PROGRESS LOG ===\n\n"

    # Unfinished thread from last session
    if mode == "session":
        thread = extract_thread_from_last_session(client_name)
        if thread:
            prompt += f"=== UNFINISHED THREAD FROM LAST SESSION ===\n{thread}\n=== END THREAD ===\n\n"

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
        # Full session mode
        if session_type and session_type in SESSION_TYPES:
            type_instructions = {
                "A": """ISTDP PRESSURE SESSION — CLINICAL INSTRUCTIONS:

Your primary task: follow the feeling, escalate through resistance, aim for somatic breakthrough.

ANXIETY PATHWAY READING (do this continuously throughout):
- STRIATED MUSCLE (green light — escalate): shoulder tension, jaw clenching, fists pressing, legs bouncing, sighing, breath-holding. Energy present. System has capacity. Push.
- SMOOTH MUSCLE (red light — stop): GI discomfort, fatigue, body heaviness, "relaxed" but hollow, going flat, monotone. STOP pressure. Shift to grounding.
- COGNITIVE-PERCEPTUAL DISRUPTION (full stop): losing thought mid-sentence, visual changes, confusion, unreality. Halt all therapeutic content. Ground only.
- OSCILLATING (bracing): use combined pressure + recap alternating — evoke the feeling, then link phenomena, then evoke again.

PRESSURE LADDER — escalate rather than repeat:
1. PRESSURE: "What are you feeling right now in your body?" Specific, anchored, repeated until movement.
2. CLARIFICATION: "Notice what just happened — you went from feeling to explaining. That's the Protector." Name the defence and its function.
3. CHALLENGE + BRACING: "You're building a philosophy instead of feeling. What are you running from?" Interrupt mid-flow. If oscillating: "What do you feel? [pause] I notice your shoulders just gripped — stay with that. What's underneath the grip?"
4. HEAD-ON COLLISION: "Part of you wants to keep this wall up forever. And if it does, nothing changes — not for your relationships, not for the part of you that's been waiting. What are we going to do about that?" Then SILENCE.

RAGE-GUILT-GRIEF SEQUENCE — do not shortcut:
- RAGE somatic pathway: rising heat/energy up through chest to head, then down arms. Tension and anxiety DROP when rage is fully felt. Symptoms reduce.
  Facilitate: "Where is it starting? What direction does it move? What does it want to do with your hands? If there were no consequences — what would the rage do, to whom?"
  If blocked: use portraying — "If your rage could speak through you right now, what would it say to [person]? What would it do to them?"
- GUILT: hard, solid waves; pain in upper chest; felt as if one has just murdered a loved one. DO NOT rush past this. Guilt is the door. Grief is behind it.
  Facilitate: "What are you feeling now, after that rage? Stay with that. What is that in your chest?"
- GRIEF: softer tears; painful feeling in chest; quieter waves. The Vulnerable Child.
  Facilitate: "What was never given to you? What did that child deserve that he didn't receive?"

ORIGINAL EMOTION VS DEFENSIVE AFFECT (use the wave shape):
Before deepening any emotional expression, check: is this original or defensive?
- Tears that RISE then RESOLVE (wave shape) = real grief. Stay with it.
- Tears that STAY HIGH without resolving (flat-top) = weepiness covering anger. Block: "The tears are coming — but what's underneath? What's the feeling BEFORE the tears?"
- Rage that rises at a REAL stimulus then falls = proportional anger. Express fully.
- Rage that STAYS HIGH proportional to hours of thinking = anger from projection. Block projection, find original feeling.
- Guilt AFTER accessing rage = healthy guilt (the door to grief). Stay with it.
- Guilt WITHOUT having accessed rage = neurotic guilt (self-punishment). Block, look for rage.

PSYCHODIAGNOSTIC RESPONSE READING:
- Feels immediately → low resistance → stay with it, deepen.
- Tenses then feels → moderate resistance (Sapandeep's primary state) → standard ladder.
- Tenses and defends repeatedly → high resistance → move to Level 3-4.
- Goes flat/depressed → repression triggered → STOP, compassion/grounding.
- Goes confused → CPD threshold → full stop, grounding only.

PER-INTERVENTION CHECK (silent, after each exchange):
Did this land on feeling, anxiety, or defence? Did the Unconscious Therapeutic Alliance rise or fall? If UTA fell after your intervention — adjust, don't repeat.""",
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
            }
            prompt += f"""=== SESSION TYPE: {session_type} ===
Today's session type: {SESSION_TYPES[session_type]}

{type_instructions.get(session_type, '')}
=== END SESSION TYPE ===

"""

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

    return prompt

# ---------------------------------------------------------------------------
# Audio Recording with Silence Detection
# ---------------------------------------------------------------------------

def record_until_silence():
    """Record from microphone until silence is detected. Returns numpy array."""
    print("\n  \033[32m🎙️  Listening...\033[0m", flush=True)

    audio_chunks = []
    silence_start = None
    has_speech = False
    recording_start = time.time()

    def callback(indata, frames, time_info, status):
        nonlocal silence_start, has_speech
        audio_chunks.append(indata.copy())

        volume = np.abs(indata).mean()

        if volume > SILENCE_THRESHOLD:
            has_speech = True
            silence_start = None
        elif has_speech and silence_start is None:
            silence_start = time.time()

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                           dtype='float32', callback=callback,
                           blocksize=int(SAMPLE_RATE * 0.1)):
            while True:
                time.sleep(0.05)

                # Check if silence long enough after speech
                if (has_speech and silence_start and
                        time.time() - silence_start >= SILENCE_DURATION):
                    break

                # Safety timeout — 5 minutes max recording
                if time.time() - recording_start > 300:
                    print("  (max recording time reached)")
                    break

    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(f"  Recording error: {e}")
        return None

    if not has_speech or not audio_chunks:
        return None

    audio = np.concatenate(audio_chunks, axis=0)
    duration = len(audio) / SAMPLE_RATE

    if duration < MIN_RECORDING_DURATION:
        return None

    return audio

def save_audio_to_wav(audio, path):
    """Save numpy audio array to WAV file."""
    audio_int16 = (audio * 32767).astype(np.int16)
    with wave.open(str(path), 'w') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio_int16.tobytes())

# ---------------------------------------------------------------------------
# Speech-to-Text (Whisper)
# ---------------------------------------------------------------------------

_whisper_model = None

def get_whisper_model():
    """Load Whisper model (downloads on first use)."""
    global _whisper_model
    if _whisper_model is None:
        print("  Loading Whisper model (first time may take a minute)...")
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(WHISPER_MODEL, device="cpu",
                                       compute_type="int8")
    return _whisper_model

def transcribe(audio):
    """Transcribe audio numpy array to text."""
    # Save to temp WAV
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    save_audio_to_wav(audio, tmp.name)
    tmp.close()

    try:
        model = get_whisper_model()
        segments, info = model.transcribe(tmp.name, beam_size=5,
                                           language="en",
                                           vad_filter=True)
        text = " ".join(seg.text for seg in segments).strip()
        return text
    finally:
        os.unlink(tmp.name)

# ---------------------------------------------------------------------------
# Text-to-Speech (Edge TTS)
# ---------------------------------------------------------------------------

async def _speak_async(text):
    """Generate speech with Edge TTS and play it."""
    import edge_tts

    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()

    try:
        communicate = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE)
        await communicate.save(tmp.name)

        # Play on macOS using afplay
        subprocess.run(["afplay", tmp.name], check=True,
                       capture_output=True)
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)

def speak(text):
    """Speak text aloud using Edge TTS."""
    print(f"\n  \033[34m🔊 Claude:\033[0m {text}\n")
    try:
        asyncio.run(_speak_async(text))
    except Exception as e:
        print(f"  (TTS error: {e} — response shown as text above)")

# ---------------------------------------------------------------------------
# AI Response Integration (Claude or Ollama)
# ---------------------------------------------------------------------------

def get_ai_response(system_prompt, conversation, user_message, model="claude"):
    """Send message to AI (Claude or Ollama) and get response."""
    print("  \033[33m⏳ Processing...\033[0m", flush=True)

    # Build the full prompt with conversation context
    full_prompt = system_prompt + "\n\n"

    # Include recent conversation history
    recent = conversation[-MAX_CONTEXT_EXCHANGES:]
    if recent:
        full_prompt += "=== CONVERSATION SO FAR ===\n"
        for role, msg in recent:
            label = "Client" if role == "user" else "Therapist"
            full_prompt += f"{label}: {msg}\n\n"
        full_prompt += "=== END CONVERSATION ===\n\n"

    full_prompt += f"Client just said: {user_message}\n\n"
    full_prompt += "Respond as the therapist. Speak naturally — this will be read aloud."

    try:
        if model == "claude":
            # Use Claude via Claude Code CLI
            result = subprocess.run(
                ["claude", "-p", full_prompt],
                capture_output=True,
                text=True,
                timeout=120
            )

            response = result.stdout.strip()

            if not response:
                # Try stderr for error info
                if result.stderr:
                    print(f"  Claude error: {result.stderr[:200]}")
                return "I'm here. Take a moment. What's happening in your body right now?"

            # Clean any markdown formatting that Claude might add
            response = response.replace("**", "").replace("*", "")
            response = response.replace("##", "").replace("#", "")
            response = response.replace("- ", "").replace("• ", "")

            return response

        elif model.startswith("ollama-"):
            # Extract model name (e.g., "ollama-r1:8b" -> "deepseek-r1:8b")
            ollama_models = {
                "ollama-r1:8b": "deepseek-r1:8b",
                "ollama-r1:14b": "deepseek-r1:14b",
                "ollama-r1:32b": "deepseek-r1:32b",
                "ollama-llama3.1:8b": "llama3.1:8b",
            }
            ollama_model = ollama_models.get(model, "deepseek-r1:14b")

            try:
                response_text = ""
                # Stream response from Ollama
                r = requests.post(
                    "http://localhost:11434/api/generate",
                    json={"model": ollama_model, "prompt": full_prompt, "stream": True},
                    timeout=180
                )
                r.raise_for_status()

                # Parse streaming JSON responses
                for line in r.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        response_text += chunk.get("response", "")

                if not response_text.strip():
                    return "I'm here. Take a moment. What's happening in your body right now?"

                # Clean markdown
                response_text = response_text.replace("**", "").replace("*", "")
                response_text = response_text.replace("##", "").replace("#", "")
                response_text = response_text.replace("- ", "").replace("• ", "")

                return response_text.strip()

            except requests.exceptions.ConnectionError:
                print("\n  ERROR: Ollama not running at localhost:11434")
                print("  Start Ollama with: ollama serve")
                return "I'm here. Take a moment. What's happening in your body right now?"

        else:
            return "Unknown model. Use 'claude' or 'ollama-*'."

    except subprocess.TimeoutExpired:
        return "Let's pause here for a moment. Take a breath. What are you noticing right now?"
    except FileNotFoundError:
        print("\n  ERROR: 'claude' command not found.")
        print("  Make sure Claude Code is installed: npm install -g @anthropic-ai/claude-code")
        sys.exit(1)
    except Exception as e:
        print(f"  Error: {e}")
        return "Stay with what's present. What's happening in your body?"

# Keep old name for backward compatibility
def get_claude_response(system_prompt, conversation, user_message, model="claude"):
    """Deprecated: use get_ai_response instead."""
    return get_ai_response(system_prompt, conversation, user_message, model)

# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, client_name, session_type=None, mode="session", model="claude"):
        self.client_name = client_name
        self.client_dir = SESSIONS_DIR / client_name
        self.client_dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.model = model

        self.start_time = datetime.now()
        self.conversation = []  # list of (role, message) tuples

        if mode == "checkin":
            self.session_file = self.client_dir / "checkins.md"
            self.session_number = 0
            self.session_type = None
        else:
            self.session_number = self._next_session_number()
            self.session_type = session_type or select_session_type(client_name)
            self.session_file = self.client_dir / (
                f"{self.start_time.strftime('%Y-%m-%d')}"
                f"_session_{self.session_number:02d}.md"
            )

        self.system_prompt = build_system_prompt(client_name, self.session_type, mode)

    def _next_session_number(self):
        """Determine session number for today."""
        today = self.start_time.strftime('%Y-%m-%d')
        existing = list(self.client_dir.glob(f"{today}_session_*.md"))
        return len(existing) + 1

    def add_exchange(self, user_msg, claude_msg):
        """Add an exchange and auto-save."""
        self.conversation.append(("user", user_msg))
        self.conversation.append(("assistant", claude_msg))
        self._save_transcript()

    def _save_transcript(self):
        """Save current transcript to file (called after every exchange)."""
        if self.mode == "checkin":
            self._save_checkin_transcript()
            return

        duration = datetime.now() - self.start_time
        minutes = int(duration.total_seconds() / 60)

        content = f"""# Breakthrough Session — {self.client_name.title()}
**Date:** {self.start_time.strftime('%Y-%m-%d %H:%M')}
**Session:** {self.session_number}
**Session Type:** {self.session_type}
**Duration:** {minutes} minutes (in progress)

---

## Transcript

"""
        elapsed = 0
        for i in range(0, len(self.conversation), 2):
            user_msg = self.conversation[i][1] if i < len(self.conversation) else ""
            claude_msg = self.conversation[i+1][1] if i+1 < len(self.conversation) else ""

            content += f"**[{elapsed:02d}:00] You:**\n{user_msg}\n\n"
            content += f"**Claude:**\n{claude_msg}\n\n---\n\n"
            elapsed += 2  # rough estimate

        self.session_file.write_text(content)

    def _save_checkin_transcript(self):
        """Append check-in to checkins.md."""
        duration = datetime.now() - self.start_time
        minutes = int(duration.total_seconds() / 60)

        entry = f"""
---

## Check-in — {self.start_time.strftime('%Y-%m-%d %H:%M')} ({minutes} min)

"""
        for role, msg in self.conversation:
            label = "You" if role == "user" else "Claude"
            entry += f"**{label}:** {msg}\n\n"

        # Append to file
        if self.session_file.exists():
            existing = self.session_file.read_text()
            self.session_file.write_text(existing + entry)
        else:
            header = f"# Check-ins — {self.client_name.title()}\n\nBrief daily check-ins for defence interruption, micro-action debrief, and somatic snapshots.\n"
            self.session_file.write_text(header + entry)

    def generate_summary(self):
        """Ask Claude to generate a session summary."""
        if not self.conversation:
            return

        if self.mode == "checkin":
            print(f"\n  📝 Check-in saved: {self.session_file}")
            return

        print("\n  Generating session summary...")

        transcript = "\n".join(
            f"{'Client' if r == 'user' else 'Therapist'}: {m}"
            for r, m in self.conversation
        )

        summary_prompt = f"""You just completed a Breakthrough Programme therapy session.
Session type: {self.session_type} — {SESSION_TYPES.get(self.session_type, 'Unknown')}

Here is the full transcript:
{transcript}

Generate a concise session summary with these sections:
1. SESSION SUMMARY (2-3 sentences — what happened, what emerged)
2. SESSION TYPE USED: {self.session_type}
3. DEFENCES OBSERVED (which defence layers activated, count each type: Protector/Critic/Overcompensator; note ISTDP category: isolation of affect / resistance of guilt / tactical / repression)
4. ANXIETY PATHWAY (which pathway was primarily active: striated / smooth muscle / CPD / mixed; any threshold crossings noted)
5. SOMATIC DATA (any body sensations reported, shifts noticed, somatic pathways of feeling if accessed)
6. FELT SHIFTS (did genuine felt change occur? Y/N + description)
7. RAGE-GUILT-GRIEF PROGRESS (which stages accessed: none/rage/guilt/grief/complete; somatic markers for each stage reached)
8. PRESSURE LADDER (highest level reached 1-4 if ISTDP was used, and the response)
9. SHAME ACCESSED (Y/N + context if yes)
10. TRIANGLE-OF-CONFLICT CODING (for each key exchange in the session, code what the intervention landed on: F=feeling, A=anxiety, D=defence; note whether UTA appeared to rise or fall; e.g. "Exchange 3: D→pressed isolation of affect, UTA rose — patient softened")
11. MICRO-ACTIONS (assign 2-3 specific actions for the coming days — specific, calibrated, tied to core wound)
12. THREAD FOR NEXT SESSION (what to follow up on)
13. RECOMMENDED NEXT SESSION TYPE (A/B/C/D/E based on what emerged)

Be honest. If no felt shift occurred, say so. The body is the scoreboard."""

        try:
            result = subprocess.run(
                ["claude", "-p", summary_prompt],
                capture_output=True, text=True, timeout=120
            )
            summary = result.stdout.strip()
        except Exception:
            summary = "(Summary generation failed — review transcript manually)"

        # Append summary to session file
        duration = datetime.now() - self.start_time
        minutes = int(duration.total_seconds() / 60)

        content = self.session_file.read_text()
        content = content.replace(
            f"**Duration:** {minutes} minutes (in progress)",
            f"**Duration:** {minutes} minutes"
        )
        content += f"\n\n## Session Summary\n\n{summary}\n"
        self.session_file.write_text(content)

        # Append to progress log
        self._update_progress_log(summary)

        # Update micro-actions from summary
        self._update_micro_actions(summary)

        print(f"\n  📝 Session saved: {self.session_file}")
        return summary

    def _update_progress_log(self, summary):
        """Append session data to progress log."""
        log_path = self.client_dir / "progress_log.md"

        entry = f"\n### {self.start_time.strftime('%Y-%m-%d')} — Session {self.session_number} (Type {self.session_type})\n\n"
        entry += f"{summary}\n\n---\n"

        if log_path.exists():
            existing = log_path.read_text()
            log_path.write_text(existing + entry)
        else:
            header = f"# Progress Log — {self.client_name.title()}\n\nRunning log of session data, defence observations, somatic shifts, and therapeutic progress.\n\n---\n"
            log_path.write_text(header + entry)

    def _update_micro_actions(self, summary):
        """Extract and log any new micro-actions from session summary."""
        # The summary contains micro-actions in section 9
        # We append any new actions to the micro_actions file
        actions_path = self.client_dir / "micro_actions.md"

        if "MICRO-ACTIONS" in summary or "MICRO ACTIONS" in summary:
            entry = f"\n### Assigned {self.start_time.strftime('%Y-%m-%d')} (Session {self.session_number})\n\n"
            # Extract the micro-actions section
            lines = summary.split("\n")
            in_section = False
            for line in lines:
                if "MICRO-ACTION" in line.upper() or "MICRO ACTION" in line.upper():
                    in_section = True
                    continue
                if in_section:
                    if line.strip().startswith(("1.", "2.", "3.", "-", "*")):
                        entry += f"- [ ] {line.strip().lstrip('0123456789.-*) ')}\n"
                    elif line.strip() and any(line.strip().startswith(str(i)) for i in range(10)):
                        # Numbered items without period
                        entry += f"- [ ] {line.strip().lstrip('0123456789.-*) ')}\n"
                    elif line.strip() == "" and entry.count("[ ]") > 0:
                        break
                    elif line.strip().startswith(("#", "THREAD", "RECOMMEND", "SESSION")):
                        break

            if "[ ]" in entry:
                entry += "\n"
                if actions_path.exists():
                    existing = actions_path.read_text()
                    actions_path.write_text(existing + entry)
                else:
                    header = f"# Micro-Actions — {self.client_name.title()}\n\nPrescribed micro-actions for real-world evidence generation. Each action tests a threat prediction and builds the self-trust account.\n\n**Status key:** [ ] = pending, [x] = done, [~] = skipped\n\n---\n"
                    actions_path.write_text(header + entry)

# ---------------------------------------------------------------------------
# Weekly Review Generation
# ---------------------------------------------------------------------------

def generate_weekly_review(client_name):
    """Generate a structured weekly review from the past week's sessions."""
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        print(f"  No sessions found for {client_name}")
        return

    week_content = []

    # Progress log entries from last 7 days (already contains per-session summaries)
    progress = load_recent_progress_log(client_name, days=7)
    if progress:
        week_content.append(f"=== SESSION PROGRESS (last 7 days) ===\n{progress}")

    # Micro-actions
    actions_path = client_dir / "micro_actions.md"
    if actions_path.exists():
        week_content.append(f"=== Micro-Actions ===\n{actions_path.read_text()}")

    # Somatic baseline
    baseline_path = client_dir / "somatic_baseline.md"
    if baseline_path.exists():
        week_content.append(f"=== Somatic Baseline ===\n{baseline_path.read_text()}")

    if not week_content:
        print("  No sessions found for the past week.")
        return

    all_content = "\n\n".join(week_content)

    review_prompt = build_system_prompt(client_name, mode="review")
    review_prompt += f"\n\n=== THIS WEEK'S DATA ===\n{all_content}\n=== END DATA ===\n\n"
    review_prompt += "Generate the weekly review now. Be thorough, honest, and specific."

    print("  Generating weekly review...")

    try:
        result = subprocess.run(
            ["claude", "-p", review_prompt],
            capture_output=True, text=True, timeout=180
        )
        review = result.stdout.strip()
    except Exception as e:
        print(f"  Error generating review: {e}")
        return

    # Save review
    reviews_dir = client_dir / "weekly_reviews"
    reviews_dir.mkdir(exist_ok=True)

    now = datetime.now()
    week_num = now.strftime("%Y-W%W")
    review_file = reviews_dir / f"{week_num}.md"

    review_content = f"""# Weekly Review — {client_name.title()}
**Week:** {week_num}
**Generated:** {now.strftime('%Y-%m-%d %H:%M')}

---

{review}
"""

    review_file.write_text(review_content)
    print(f"\n  📊 Weekly review saved: {review_file}")
    print(f"\n{review}")

# ---------------------------------------------------------------------------
# Main Session Loop
# ---------------------------------------------------------------------------

def print_banner(client_name, session_number, session_type=None, mode="session"):
    print("\033[2J\033[H")  # clear screen
    print("=" * 60)
    if mode == "checkin":
        print("  BREAKTHROUGH CHECK-IN")
    elif mode == "review":
        print("  BREAKTHROUGH WEEKLY REVIEW")
    else:
        print("  BREAKTHROUGH SESSION")
    print("=" * 60)
    print(f"  Client:  {client_name.title()}")
    if mode == "session":
        print(f"  Session: {session_number}")
        if session_type:
            print(f"  Type:    {session_type} — {SESSION_TYPES.get(session_type, 'Unknown')}")
    print(f"  Date:    {datetime.now().strftime('%B %d, %Y — %H:%M')}")
    if mode == "session":
        print(f"  Voice:   {VOICE}")
    print("-" * 60)
    if mode == "checkin":
        print("  Brief check-in mode. Type 'done' to finish.")
    elif mode == "review":
        print("  Generating weekly review...")
    else:
        print("  Speak naturally. Pause for 2 seconds to send.")
        print("  Say 'end session' to close and save.")
        print("  Press Ctrl+C to emergency stop (still saves).")
    print("=" * 60)

def run_text_mode(session):
    """Fallback text mode if audio has issues."""
    if session.mode == "checkin":
        print("\n  CHECK-IN MODE — type your messages (type 'done' to finish)\n")
    else:
        print("\n  TEXT MODE — type your messages (type 'end session' to finish)\n")

    # Opening
    if session.mode == "checkin":
        opening_msg = "Quick check-in. What's in your body right now? One sentence."
    else:
        opening_msg = (
            f"Session is starting now. This is a Type {session.session_type} session: "
            f"{SESSION_TYPES.get(session.session_type, '')}. "
            "Begin with the appropriate session opening from Section 5."
        )

    opening = get_claude_response(
        session.system_prompt, [],
        opening_msg,
        model=session.model
    )
    print(f"\n  \033[34mClaude:\033[0m {opening}\n")
    session.conversation.append(("assistant", opening))
    session._save_transcript()

    end_words = ("done", "end", "quit", "exit") if session.mode == "checkin" else ("end session", "end", "quit", "exit")

    exchange_count = 0
    while True:
        try:
            user_input = input("  \033[32mYou:\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        if user_input.lower() in end_words:
            break

        response = get_claude_response(
            session.system_prompt, session.conversation, user_input,
            model=session.model
        )
        print(f"\n  \033[34mClaude:\033[0m {response}\n")
        session.add_exchange(user_input, response)
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
            print(f"\n  \033[34mClaude:\033[0m {time_note}\n")
            session.add_exchange("[System time check]", time_note)

def run_voice_mode(session):
    """Full voice mode — speak and listen."""

    # Load whisper up front
    get_whisper_model()

    # Opening — Claude initiates the session
    print("\n  Starting session...\n")
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
    speak(opening)
    session.conversation.append(("assistant", opening))
    session._save_transcript()

    # Main loop
    exchange_count = 0
    while True:
        try:
            audio = record_until_silence()

            if audio is None:
                continue

            # Transcribe
            print("  \033[33m📝 Transcribing...\033[0m", flush=True)
            text = transcribe(audio)

            if not text or len(text.strip()) < 2:
                continue

            print(f"\n  \033[32m🎙️  You:\033[0m {text}")

            # Check for end session
            if any(phrase in text.lower() for phrase in
                   ["end session", "end the session", "stop session",
                    "that's it for today", "let's stop"]):

                # Let Claude close the session properly
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
                break

            # Get Claude's response
            response = get_claude_response(
                session.system_prompt, session.conversation, text,
                model=session.model
            )
            speak(response)
            session.add_exchange(text, response)
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
                session.add_exchange("[System time check]", time_note)

        except KeyboardInterrupt:
            print("\n\n  Session interrupted.")
            break

def main():
    global VOICE, WHISPER_MODEL

    parser = argparse.ArgumentParser(description="Breakthrough Session")
    parser.add_argument("--client", "-c", default="sapandeep",
                        help="Client name (default: sapandeep)")
    parser.add_argument("--text", "-t", action="store_true",
                        help="Use text mode instead of voice")
    parser.add_argument("--voice", "-v", default=None,
                        help="TTS voice (default: en-GB-RyanNeural)")
    parser.add_argument("--whisper-model", "-w", default=None,
                        help="Whisper model size (default: base)")
    parser.add_argument("--checkin", "-k", action="store_true",
                        help="Brief check-in mode (5-10 min, text only)")
    parser.add_argument("--review", "-r", action="store_true",
                        help="Generate weekly review")
    parser.add_argument("--session-type", "-s", default=None,
                        choices=list(SESSION_TYPES.keys()),
                        help="Force a specific session type (A-E)")
    parser.add_argument("--model", "-m", default="claude",
                        choices=["claude", "ollama-r1:8b", "ollama-r1:14b", "ollama-r1:32b", "ollama-llama3.1:8b"],
                        help="AI model to use (default: claude)")
    args = parser.parse_args()

    if args.voice:
        VOICE = args.voice
    if args.whisper_model:
        WHISPER_MODEL = args.whisper_model

    # Weekly review mode
    if args.review:
        print_banner(args.client, 0, mode="review")
        generate_weekly_review(args.client)
        print("\n  Review complete.\n")
        return

    # Check-in mode
    if args.checkin:
        session = Session(args.client, mode="checkin", model=args.model)
        print_banner(args.client, 0, mode="checkin")

        # Handle graceful shutdown
        def shutdown(sig, frame):
            print("\n\n  Saving check-in...")
            session._save_transcript()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown)

        try:
            run_text_mode(session)
            session._save_transcript()
        except Exception as e:
            print(f"\n  Error: {e}")
            session._save_transcript()

        print("\n  Check-in complete. Stay with what's present.\n")
        return

    # Full session mode
    session = Session(args.client, session_type=args.session_type, model=args.model)
    print_banner(args.client, session.session_number, session.session_type)

    # Handle graceful shutdown
    def shutdown(sig, frame):
        print("\n\n  Saving session...")
        session.generate_summary()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    try:
        # Check if audio is available
        if args.text:
            run_text_mode(session)
        else:
            try:
                # Quick mic test
                sd.query_devices(kind='input')
                run_voice_mode(session)
            except Exception as e:
                print(f"\n  Audio error: {e}")
                print("  Falling back to text mode...\n")
                run_text_mode(session)

        # Generate summary on clean exit
        session.generate_summary()

    except Exception as e:
        print(f"\n  Unexpected error: {e}")
        # Still try to save
        try:
            session._save_transcript()
            print(f"  Transcript saved: {session.session_file}")
        except:
            pass

    print("\n  Session complete. Take care.\n")

if __name__ == "__main__":
    main()
