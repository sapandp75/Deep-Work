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
import copy
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
    "F": "Ericksonian Guided Hypnosis / Rescripting — slower guided trance-style rescripting for shame memories and emotional installation",
}

# Paths
BASE_DIR = Path(__file__).parent
SESSIONS_DIR = BASE_DIR / "sessions"
PROGRAMME_FILE = Path(__file__).parent.parent / "The_Breakthrough_Programme.md"
KNOWLEDGE_BASE_FILE = Path(__file__).parent.parent / "resources" / "ISTDP_Knowledge_Base.md"
DEFAULT_SCOREBOARD = {
    "version": 1,
    "current_week": "",
    "sessions": [],
    "recommended_next_type": None,
    "recommended_reason": "",
    "pending_consolidation": False,
    "consolidation_items": [],
    "pending_actions": [],
    "metrics": {
        "shame_intensity": None,
        "baseline_intensity": None,
        "self_abandonment_catches": 0,
        "breakthrough_carryover": "none",
        "groundedness_after_session": None,
    },
}

def new_scoreboard():
    board = copy.deepcopy(DEFAULT_SCOREBOARD)
    board["current_week"] = datetime.now().strftime("%Y-W%W")
    return board

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
    "F": {
        "programme_sections": ["1", "2", "Tool2", "Tool6", "6"],
        "kb_sections": [1, 2, 6, 19, 25, 29],
        "max_sessions": 2,
        "micro_actions": True,
        "somatic_baseline": False,
        "progress_log": True,
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

def ensure_tracking_files(client_name):
    """Ensure all machine and human tracking files exist."""
    client_dir = SESSIONS_DIR / client_name
    client_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "micro_actions.md": (
            f"# Micro-Actions — {client_name.title()}\n\n"
            "Prescribed micro-actions for real-world evidence generation. Each action tests a threat prediction and builds the self-trust account.\n\n"
            "**Status key:** [ ] = pending, [x] = done, [~] = skipped\n\n---\n"
        ),
        "daily_actions.md": (
            f"# Daily Actions — {client_name.title()}\n\n"
            "Daily real-life change work across micro-actions, behavioural experiments, exposure / re-entry, and vitality.\n\n"
            "**Status key:** [ ] = pending, [x] = done, [~] = skipped\n\n---\n"
        ),
        "consolidation_queue.md": (
            f"# Consolidation Queue — {client_name.title()}\n\n"
            "Post-breakthrough tasks that lock a felt shift into body, behaviour, and anti-relapse awareness.\n\n---\n"
        ),
        "auto_state.md": (
            f"# Auto State — {client_name.title()}\n\n"
            "Machine-generated snapshot read at the start of every session.\n"
        ),
    }

    for filename, default_content in files.items():
        path = client_dir / filename
        if not path.exists():
            path.write_text(default_content)

    scoreboard_path = client_dir / "scoreboard.json"
    if not scoreboard_path.exists():
        scoreboard = new_scoreboard()
        scoreboard_path.write_text(json.dumps(scoreboard, indent=2))

def load_scoreboard(client_name):
    path = SESSIONS_DIR / client_name / "scoreboard.json"
    if not path.exists():
        ensure_tracking_files(client_name)
    try:
        return json.loads(path.read_text())
    except Exception:
        return new_scoreboard()

def save_scoreboard(client_name, scoreboard):
    path = SESSIONS_DIR / client_name / "scoreboard.json"
    path.write_text(json.dumps(scoreboard, indent=2))

def unique_pending_action_dicts(actions):
    seen = set()
    result = []
    for action in actions:
        text = action.get("text", "")
        norm = normalize_action_text(text)
        if norm and norm not in seen:
            seen.add(norm)
            result.append(action)
    return result

def load_auto_state(client_name):
    path = SESSIONS_DIR / client_name / "auto_state.md"
    return path.read_text() if path.exists() else ""

def load_daily_actions(client_name):
    path = SESSIONS_DIR / client_name / "daily_actions.md"
    return path.read_text() if path.exists() else ""

def load_consolidation_queue(client_name):
    path = SESSIONS_DIR / client_name / "consolidation_queue.md"
    return path.read_text() if path.exists() else ""

def current_week_key(now=None):
    now = now or datetime.now()
    return now.strftime("%Y-W%W")

def sessions_done_today(client_name):
    today = datetime.now().strftime("%Y-%m-%d")
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return 0
    return len(list(client_dir.glob(f"{today}_session_*.md")))

def extract_summary_field(summary, field_prefix):
    for line in summary.split("\n"):
        if line.upper().startswith(field_prefix.upper()):
            return line.split(":", 1)[-1].strip()
    return ""

def extract_machine_data(summary):
    """Extract machine-readable JSON payload from summary if present."""
    marker = "## MACHINE DATA"
    idx = summary.find(marker)
    if idx == -1:
        return {}
    payload = summary[idx + len(marker):].strip()
    if payload.startswith("```json"):
        payload = payload[len("```json"):].strip()
    elif payload.startswith("```"):
        payload = payload[len("```"):].strip()
    if payload.endswith("```"):
        payload = payload[:-3].strip()
    try:
        return json.loads(payload)
    except Exception:
        return {}

def machine_data_is_valid(data):
    if not isinstance(data, dict) or not data:
        return False
    rec = data.get("recommended_next_type")
    if rec is not None and rec not in SESSION_TYPES:
        return False
    if "micro_actions" in data and not isinstance(data.get("micro_actions"), list):
        return False
    if "daily_actions" in data and not isinstance(data.get("daily_actions"), dict):
        return False
    return True

def normalize_action_text(action):
    return re.sub(r"\s+", " ", action.strip().lower())

def dedupe_actions(existing_text, new_actions):
    existing_norm = set()
    for line in existing_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("- [ ]", "- [x]", "- [~]")):
            existing_norm.add(normalize_action_text(stripped[6:].strip()))
    deduped = []
    seen = set()
    for action in new_actions:
        norm = normalize_action_text(action)
        if norm and norm not in existing_norm and norm not in seen:
            seen.add(norm)
            deduped.append(action)
    return deduped

def parse_recommended_type_from_summary(summary):
    data = extract_machine_data(summary)
    rec = data.get("recommended_next_type")
    if rec in SESSION_TYPES:
        return rec
    for line in summary.split("\n"):
        upper = line.upper()
        if "RECOMMENDED NEXT SESSION TYPE" in upper:
            match = re.search(r"RECOMMENDED NEXT SESSION TYPE\s*:\s*([A-F])\b", upper)
            if match:
                return match.group(1)
    return None

def parse_action_lines_from_summary(summary):
    data = extract_machine_data(summary)
    if data.get("micro_actions"):
        return [a for a in data.get("micro_actions", []) if a]
    actions = []
    lines = summary.split("\n")
    in_actions = False
    for line in lines:
        upper = line.upper().strip()
        if upper.startswith("11. MICRO-ACTIONS") or upper.startswith("11. MICRO ACTIONS") or upper == "MICRO-ACTIONS" or upper == "MICRO ACTIONS":
            in_actions = True
            continue
        if in_actions:
            if not line.strip():
                if actions:
                    break
                continue
            if re.match(r"^\s*(12\.|THREAD|RECOMMENDED NEXT SESSION TYPE)", upper):
                break
            if line.strip().startswith(("1.", "2.", "3.", "-", "*")):
                action = line.strip().lstrip("0123456789.-*) ").strip()
                if action:
                    actions.append(action)
    return actions

def parse_shift_detected(summary):
    data = extract_machine_data(summary)
    if "felt_shift" in data:
        return bool(data.get("felt_shift"))
    upper = summary.upper()
    return "FELT SHIFT" in upper and "YES" in upper

def parse_carryover_hint(summary):
    data = extract_machine_data(summary)
    if data.get("breakthrough_carryover"):
        return data["breakthrough_carryover"]
    upper = summary.upper()
    if "24H" in upper or "24 HOURS" in upper:
        return "24h"
    if "48H" in upper or "48 HOURS" in upper:
        return "48h"
    return "none"

def backfill_scoreboard_from_history(client_name):
    """Seed scoreboard from historical session files if empty."""
    scoreboard = load_scoreboard(client_name)
    if scoreboard.get("sessions"):
        return scoreboard
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return scoreboard
    for session_file in sorted(client_dir.glob("*_session_*.md")):
        content = session_file.read_text()
        date_match = re.search(r"\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})", content)
        type_match = re.search(r"\*\*Session Type:\*\*\s*([A-F])", content)
        if not date_match or not type_match:
            continue
        date_str = date_match.group(1)
        sess_type = type_match.group(1)
        week = datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-W%W")
        felt_shift = "FELT SHIFT" in content.upper() and "YES" in content.upper()
        scoreboard.setdefault("sessions", []).append({
            "date": date_str,
            "type": sess_type,
            "week": week,
            "recommended_type": None,
            "override_reason": None,
            "felt_shift": felt_shift,
        })
    scoreboard["sessions"] = scoreboard.get("sessions", [])[-30:]
    save_scoreboard(client_name, scoreboard)
    return scoreboard

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
            for char in "ABCDEF":
                if f"TYPE {char}" in upper or f": {char}" in upper or f"({char})" in upper or line.strip().endswith(char):
                    return char
    return None

def recommend_session_type(client_name):
    """Use AI plus structured tracking to recommend the best next session type."""
    ensure_tracking_files(client_name)
    backfill_scoreboard_from_history(client_name)
    recent_types = get_recent_session_types(client_name)
    summaries = load_all_session_summaries(client_name, max_sessions=5)
    micro_actions = load_micro_actions(client_name)
    progress_log = load_recent_progress_log(client_name)
    thread = extract_thread_from_last_session(client_name)
    auto_state = load_auto_state(client_name)
    daily_actions = load_daily_actions(client_name)
    consolidation = load_consolidation_queue(client_name)
    scoreboard = load_scoreboard(client_name)
    today_sessions = sessions_done_today(client_name)

    week = current_week_key()
    deep_count = 0
    for sess in scoreboard.get("sessions", []):
        if sess.get("week") == week and sess.get("type") in {"A", "B", "C", "F"}:
            deep_count += 1

    type_descriptions = "\n".join(f"  {k}: {v}" for k, v in SESSION_TYPES.items())
    recent_str = ", ".join(recent_types) if recent_types else "None"

    selection_prompt = f"""You are selecting the next therapy session type for a client. Choose the BEST type based on therapeutic need, not rotation.

SESSION TYPES:
{type_descriptions}

RECENT SESSION TYPES (most recent first): {recent_str}
SESSIONS DONE TODAY: {today_sessions}
DEEP SESSIONS THIS WEEK (A/B/C/F): {deep_count}

RECENT SESSION SUMMARIES:
{summaries if summaries else "(No summaries available)"}

PENDING MICRO-ACTIONS:
{micro_actions if micro_actions else "(None)"}

PROGRESS LOG:
{progress_log if progress_log else "(No entries)"}

UNFINISHED THREAD FROM LAST SESSION:
{thread if thread else "(None)"}

AUTO STATE:
{auto_state if auto_state else "(None)"}

DAILY ACTIONS:
{daily_actions if daily_actions else "(None)"}

CONSOLIDATION QUEUE:
{consolidation if consolidation else "(None)"}

SELECTION CRITERIA (in priority order):
1. If there is pending consolidation from a breakthrough → Type D or E. Use F if a shame memory or rescripting thread is clearly active.
2. If there are pending micro-actions, behavioural experiments, exposures, or re-entry tasks that haven't been debriefed → Type D
3. If deep sessions this week are already 3 or more → strongly prefer D or E, not A/B/C/F
4. If the last 2+ sessions were all the same type → pick a DIFFERENT type unless the unfinished thread clearly requires continuation
5. If the last session recommended a specific next type → honor it unless higher-priority criteria override it
6. If no somatic tracking has been done recently or the client is flat / exhausted / foggy → Type E
7. If a specific shame memory, mother-aggression scene, or repeated wound needs slower installation → Type F
8. If inner child work was started but not completed → Type C
9. If core transformation would serve the current thread → Type B
10. If pressure work is needed for new material and capacity is present → Type A

Respond in exactly two lines:
TYPE: <one letter A-F>
REASON: <one concise sentence>"""

    try:
        response, _, err = _run_model_prompt(selection_prompt, timeout=30)
        if not response:
            raise RuntimeError(err or "No response from model.")
        match = re.search(r"TYPE:\s*([A-F])", response, re.IGNORECASE)
        reason_match = re.search(r"REASON:\s*(.+)", response, re.IGNORECASE)
        if match:
            rec_type = match.group(1).upper()
            reason = reason_match.group(1).strip() if reason_match else "Best fit based on recent sessions and pending work."
            print(f"  AI recommended session type: {rec_type}")
            return {"type": rec_type, "reason": reason}
    except Exception as e:
        print(f"  Session type selection fallback (AI error: {e})")

    # Fallback: least-used rotation with consolidation bias
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
    fallback = "D" if scoreboard.get("pending_consolidation") else candidates[0]
    return {"type": fallback, "reason": "Fallback recommendation based on recent usage and consolidation state."}

def select_session_type(client_name):
    """Backward-compatible selector returning only the recommended type."""
    return recommend_session_type(client_name)["type"]

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
    auto_state = load_auto_state(client_name) if mode == "session" else ""
    daily_actions = load_daily_actions(client_name) if mode in ("session", "review", "checkin") else ""
    consolidation_queue = load_consolidation_queue(client_name) if mode in ("session", "review") else ""
    scoreboard = json.dumps(load_scoreboard(client_name), indent=2) if mode in ("session", "review") else ""

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

    if auto_state:
        prompt += f"=== AUTO STATE ===\n{auto_state}\n=== END AUTO STATE ===\n\n"

    if daily_actions:
        prompt += f"=== DAILY ACTIONS ===\n{daily_actions}\n=== END DAILY ACTIONS ===\n\n"

    if consolidation_queue:
        prompt += f"=== CONSOLIDATION QUEUE ===\n{consolidation_queue}\n=== END CONSOLIDATION QUEUE ===\n\n"

    if scoreboard:
        prompt += f"=== STRUCTURED SCOREBOARD ===\n{scoreboard}\n=== END STRUCTURED SCOREBOARD ===\n\n"

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
                "F": """ERICKSONIAN GUIDED HYPNOSIS / RESCRIPTING SESSION — CLINICAL INSTRUCTIONS:

This is a slower, guided, trance-style session for emotional installation and shame-memory updating. Minimum target arc: 20 minutes. Keep the pacing slower, more sensory, and more immersive than normal sessions.

WHEN TO USE:
- A known wound keeps repeating without lasting installation
- A shame memory, humiliation memory, or maternal aggression scene is clearly active
- The client says "I understand it but I can't feel it"
- Pressure has reached the layer, but not changed the learning

OPENING:
Slow everything down. Use breath, sensory tracking, and permissive language. Help attention settle into body and scene at the same time.

METHOD:
1. Access a specific scene, not a theory.
2. Make it sensory and present-tense: what is seen, heard, felt in the body?
3. Track the emotional meaning of the scene.
4. Bring in the adult self, therapist, or protective intervention only after the emotional truth is live.
5. Rescript what was missing: protection, boundary, validation, truth, interruption of abuse, permission to feel.
6. Install the new learning in the body: "What changes in your chest now? What does the younger part know now that he didn't know then?"

STYLE GUIDELINES:
- Use indirect, permissive language: "you may notice", "something in you might begin to", "and as that scene becomes clearer"
- Use metaphor only if it deepens contact
- Long pauses are useful
- Keep attention moving between scene and present-body so the client stays anchored

SAFETY:
- If fogginess, flattening, or dissociation rises, stop the rescripting and ground immediately
- If the scene stays conceptual, do not force it. Return to body and choose a simpler target

ENDING:
Do not end with theory. End with:
- the body marker of the shift
- the new sentence that is true now
- one concrete real-life act within 24 hours that expresses the new learning
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
- If a real felt shift lands, stop digging and move to consolidation rather than more excavation.
- Every deep session (A/B/C/F) must end with: one body marker, one real-life proof action, and one anti-relapse warning.
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

def _clean_model_text(text):
    """Strip common markdown formatting from model output."""
    text = text.replace("**", "").replace("*", "")
    text = text.replace("##", "").replace("#", "")
    text = text.replace("- ", "").replace("• ", "")
    return text.strip()


def _is_claude_rate_limited(stdout, stderr):
    """Detect Claude usage/rate limit signals from CLI output."""
    combined = f"{stdout or ''}\n{stderr or ''}".lower()
    markers = (
        "rate limit",
        "usage limit",
        "too many requests",
        "ratelimit",
        "quota exceeded",
        "you've hit your limit",
        "you have hit your limit",
        "resets 3am",
    )
    return any(marker in combined for marker in markers)


def _run_model_prompt(prompt, timeout=120):
    """
    Run prompt via Claude CLI, with Codex fallback on Claude rate limits.
    Returns (response_text, provider, error_message).
    """
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if _is_claude_rate_limited(result.stdout, result.stderr):
        print("  Claude rate limit hit. Falling back to Codex...")
        codex_result = subprocess.run(
            ["codex", "exec", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        codex_text = (codex_result.stdout or "").strip()
        if codex_text:
            return _clean_model_text(codex_text), "codex", None
        codex_err = (codex_result.stderr or "").strip()
        return None, "codex", codex_err or "Codex returned empty response."

    claude_text = (result.stdout or "").strip()
    if claude_text:
        return _clean_model_text(claude_text), "claude", None

    err = (result.stderr or "").strip()
    return None, "claude", err or "Claude returned empty response."

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
            response, provider, err = _run_model_prompt(full_prompt, timeout=120)
            if not response:
                if err:
                    print(f"  {provider.capitalize()} error: {err[:200]}")
                return "I'm here. Take a moment. What's happening in your body right now?"
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

                return _clean_model_text(response_text)

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
    def __init__(self, client_name, session_type=None, mode="session", model="claude", recommendation=None, override_reason=None):
        self.client_name = client_name
        self.client_dir = SESSIONS_DIR / client_name
        self.client_dir.mkdir(parents=True, exist_ok=True)
        ensure_tracking_files(client_name)
        self.mode = mode
        self.model = model
        self.recommendation = recommendation or recommend_session_type(client_name)
        self.override_reason = override_reason

        self.start_time = datetime.now()
        self.conversation = []  # list of (role, message) tuples

        if mode == "checkin":
            self.session_file = self.client_dir / "checkins.md"
            self.session_number = 0
            self.session_type = None
        else:
            self.session_number = self._next_session_number()
            self.recommended_type = self.recommendation.get("type")
            self.recommended_reason = self.recommendation.get("reason", "")
            # Priority: 1) user-confirmed type, 2) current recommendation, 3) last session's recommendation
            self.session_type = session_type or self.recommended_type or extract_recommended_type(client_name) or select_session_type(client_name)
            self.session_file = self.client_dir / (
                f"{self.start_time.strftime('%Y-%m-%d')}"
                f"_session_{self.session_number:02d}.md"
            )

        self.system_prompt = build_system_prompt(client_name, self.session_type, mode)
        if mode == "session":
            self._rebuild_auto_state()

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
Recommended type at session start: {getattr(self, 'recommended_type', None)}
Recommendation rationale: {getattr(self, 'recommended_reason', '')}
Override reason (if any): {self.override_reason or "None"}

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
12. DAILY ACTIONS (include: behavioural experiment, exposure or re-entry step, vitality action if relevant)
13. BODY MARKER (the specific felt marker of the shift, or "none")
14. ANTI-RELAPSE WARNING (what the Protector / state-chasing pattern will likely do next)
15. THREAD FOR NEXT SESSION (what to follow up on)
16. RECOMMENDED NEXT SESSION TYPE (A/B/C/D/E/F based on what emerged)

Then add a final section exactly like this:
## MACHINE DATA
```json
{
  "recommended_next_type": "D",
  "felt_shift": false,
  "body_marker": "none",
  "anti_relapse_warning": "short sentence",
  "micro_actions": ["action 1", "action 2"],
  "daily_actions": {
    "behavioural_experiments": ["..."],
    "exposure_reentry": ["..."],
    "vitality": ["..."]
  },
  "thread_for_next_session": "short sentence",
  "summary_status": "ok"
}
```

Be honest. If no felt shift occurred, say so. The body is the scoreboard."""

        try:
            summary, _, err = _run_model_prompt(summary_prompt, timeout=120)
            summary = summary or ""
            data = extract_machine_data(summary)
            if not machine_data_is_valid(data):
                retry_prompt = summary_prompt + "\n\nYour previous response was missing or malformed in the MACHINE DATA JSON block. Regenerate the full summary and ensure the MACHINE DATA block is valid JSON."
                retry_summary, _, _ = _run_model_prompt(retry_prompt, timeout=120)
                retry_summary = retry_summary or ""
                if machine_data_is_valid(extract_machine_data(retry_summary)):
                    summary = retry_summary
            if not summary and err:
                raise RuntimeError(err)
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
        self._update_daily_actions(summary)
        self._update_consolidation(summary)
        self._update_scoreboard(summary)
        self._rebuild_auto_state(summary)

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
        actions_path = self.client_dir / "micro_actions.md"
        actions = parse_action_lines_from_summary(summary)
        if not actions:
            return
        existing = actions_path.read_text() if actions_path.exists() else (
            f"# Micro-Actions — {self.client_name.title()}\n\nPrescribed micro-actions for real-world evidence generation. Each action tests a threat prediction and builds the self-trust account.\n\n**Status key:** [ ] = pending, [x] = done, [~] = skipped\n\n---\n"
        )
        actions = dedupe_actions(existing, actions)
        if not actions:
            return
        entry = f"\n### Assigned {self.start_time.strftime('%Y-%m-%d')} (Session {self.session_number})\n\n"
        for action in actions:
            entry += f"- [ ] {action}\n"
        entry += "\n"
        actions_path.write_text(existing + entry)

    def _update_daily_actions(self, summary):
        """Append broader daily-action tracking items from the summary."""
        data = extract_machine_data(summary)
        actions = parse_action_lines_from_summary(summary)
        daily_path = self.client_dir / "daily_actions.md"
        existing = daily_path.read_text() if daily_path.exists() else (
            f"# Daily Actions — {self.client_name.title()}\n\n"
            "Daily real-life change work across micro-actions, behavioural experiments, exposure / re-entry, and vitality.\n\n"
            "**Status key:** [ ] = pending, [x] = done, [~] = skipped\n\n---\n"
        )
        entry = f"\n### Assigned {self.start_time.strftime('%Y-%m-%d')} (Session {self.session_number}, Type {self.session_type})\n\n"
        wrote = False

        micro_actions = dedupe_actions(existing, actions)
        if micro_actions:
            wrote = True
            entry += "#### Micro-Actions\n"
            for action in micro_actions:
                entry += f"- [ ] {action}\n"

        daily_actions = data.get("daily_actions", {})
        sections = [
            ("#### Behavioural Experiments", dedupe_actions(existing, daily_actions.get("behavioural_experiments", []))),
            ("#### Exposure / Re-entry", dedupe_actions(existing, daily_actions.get("exposure_reentry", []))),
            ("#### Vitality", dedupe_actions(existing, daily_actions.get("vitality", []))),
        ]
        for header, items in sections:
            if items:
                wrote = True
                entry += f"\n{header}\n"
                for item in items:
                    entry += f"- [ ] {item}\n"
        if wrote:
            daily_path.write_text(existing + entry + "\n")

    def _update_consolidation(self, summary):
        """Queue consolidation after real felt shifts."""
        if not parse_shift_detected(summary):
            return
        path = self.client_dir / "consolidation_queue.md"
        body_marker = extract_summary_field(summary, "13. BODY MARKER") or extract_summary_field(summary, "BODY MARKER")
        anti_relapse = extract_summary_field(summary, "14. ANTI-RELAPSE WARNING") or extract_summary_field(summary, "ANTI-RELAPSE WARNING")
        actions = parse_action_lines_from_summary(summary)
        body_action = actions[0] if actions else "Debrief one real-life proof action within 24 hours."
        entry = (
            f"\n### {self.start_time.strftime('%Y-%m-%d')} — Session {self.session_number} (Type {self.session_type})\n\n"
            f"- [ ] **Body anchor:** {body_marker or 'Identify the felt marker of the shift.'}\n"
            f"- [ ] **Behavioural proof:** {body_action}\n"
            f"- [ ] **Anti-relapse warning:** {anti_relapse or 'Watch for meaning-making, state-chasing, or project absorption.'}\n\n"
        )
        existing = path.read_text() if path.exists() else f"# Consolidation Queue — {self.client_name.title()}\n\nPost-breakthrough tasks that lock a felt shift into body, behaviour, and anti-relapse awareness.\n\n---\n"
        path.write_text(existing + entry)

    def _update_scoreboard(self, summary):
        scoreboard = load_scoreboard(self.client_name)
        data = extract_machine_data(summary)
        week = current_week_key(self.start_time)
        scoreboard["current_week"] = week
        recommended_next = data.get("recommended_next_type") or parse_recommended_type_from_summary(summary)
        scoreboard["recommended_next_type"] = recommended_next
        scoreboard["recommended_reason"] = data.get("thread_for_next_session") or extract_summary_field(summary, "15. THREAD FOR NEXT SESSION") or extract_summary_field(summary, "THREAD FOR NEXT SESSION")
        scoreboard["pending_consolidation"] = parse_shift_detected(summary)
        scoreboard["metrics"]["breakthrough_carryover"] = parse_carryover_hint(summary)
        scoreboard["summary_status"] = data.get("summary_status", "fallback")
        session_record = {
            "date": self.start_time.strftime("%Y-%m-%d"),
            "type": self.session_type,
            "week": week,
            "recommended_type": getattr(self, "recommended_type", None),
            "override_reason": self.override_reason,
            "felt_shift": parse_shift_detected(summary),
        }
        scoreboard.setdefault("sessions", []).append(session_record)
        scoreboard["sessions"] = scoreboard["sessions"][-30:]
        pending_actions = [{"text": action, "status": "pending", "assigned": self.start_time.strftime("%Y-%m-%d")} for action in parse_action_lines_from_summary(summary)]
        existing_pending = scoreboard.get("pending_actions", [])
        if pending_actions:
            scoreboard["pending_actions"] = unique_pending_action_dicts(existing_pending + pending_actions)
        else:
            scoreboard["pending_actions"] = unique_pending_action_dicts(existing_pending)
        consolidation_items = []
        if scoreboard["pending_consolidation"]:
            body_marker = extract_summary_field(summary, "13. BODY MARKER") or extract_summary_field(summary, "BODY MARKER")
            anti_relapse = extract_summary_field(summary, "14. ANTI-RELAPSE WARNING") or extract_summary_field(summary, "ANTI-RELAPSE WARNING")
            consolidation_items = [
                {"kind": "body_anchor", "text": body_marker or "Identify the felt marker of the shift.", "status": "pending"},
                {"kind": "anti_relapse", "text": anti_relapse or "Watch for meaning-making, state-chasing, or project absorption.", "status": "pending"},
            ]
        scoreboard["consolidation_items"] = consolidation_items
        save_scoreboard(self.client_name, scoreboard)

    def _rebuild_auto_state(self, summary=None):
        scoreboard = load_scoreboard(self.client_name)
        auto_path = self.client_dir / "auto_state.md"
        queue = load_consolidation_queue(self.client_name)
        daily = load_daily_actions(self.client_name)
        recent_summary = summary or ""
        lines = [
            f"# Auto State — {self.client_name.title()}",
            "",
            f"## Today",
            f"- Sessions done today: {sessions_done_today(self.client_name)}",
            f"- Current week: {scoreboard.get('current_week', current_week_key())}",
            "",
            "## Last Session",
            f"- Date: {self.start_time.strftime('%Y-%m-%d') if summary else 'See latest session file'}",
            f"- Type: {self.session_type if summary else 'Unknown'}",
            f"- Felt shift landed: {'Yes' if scoreboard.get('pending_consolidation') else 'No / not yet consolidated'}",
            "",
            "## Recommendation",
            f"- Recommended next type: {scoreboard.get('recommended_next_type') or 'TBD'}",
            f"- Why: {scoreboard.get('recommended_reason') or 'Review latest thread, pending actions, and consolidation state.'}",
            "",
            "## Consolidation",
            f"- Pending consolidation: {'Yes' if scoreboard.get('pending_consolidation') else 'No'}",
            "",
            "## Pending Actions",
        ]
        for item in scoreboard.get("pending_actions", [])[:5]:
            lines.append(f"- [ ] {item.get('text')}")
        if not scoreboard.get("pending_actions"):
            lines.append("- None")
        lines.extend([
            "",
            "## Active Relapse Risk",
            f"- {extract_summary_field(recent_summary, '14. ANTI-RELAPSE WARNING') or 'Meaning-making, state-chasing, or project absorption may reappear.'}",
            "",
            "## State Quality",
            f"- Summary status: {scoreboard.get('summary_status', 'unknown')}",
            "",
            "## Thread For Next Session",
            f"- {extract_summary_field(recent_summary, '15. THREAD FOR NEXT SESSION') or 'See latest session summary and transcript tail.'}",
            "",
            "## References",
            f"- Consolidation queue file present: {'Yes' if queue.strip() else 'No'}",
            f"- Daily actions file present: {'Yes' if daily.strip() else 'No'}",
        ])
        auto_path.write_text("\n".join(lines) + "\n")

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

    daily_path = client_dir / "daily_actions.md"
    if daily_path.exists():
        week_content.append(f"=== Daily Actions ===\n{daily_path.read_text()}")

    consolidation_path = client_dir / "consolidation_queue.md"
    if consolidation_path.exists():
        week_content.append(f"=== Consolidation Queue ===\n{consolidation_path.read_text()}")

    if not week_content:
        print("  No sessions found for the past week.")
        return

    all_content = "\n\n".join(week_content)

    review_prompt = build_system_prompt(client_name, mode="review")
    review_prompt += f"\n\n=== THIS WEEK'S DATA ===\n{all_content}\n=== END DATA ===\n\n"
    review_prompt += "Generate the weekly review now. Be thorough, honest, and specific."

    print("  Generating weekly review...")

    try:
        review, _, err = _run_model_prompt(review_prompt, timeout=180)
        if not review and err:
            raise RuntimeError(err)
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

def confirm_session_type(client_name, recommendation):
    """Recommend a session type, push back once on override, then let the client decide."""
    rec_type = recommendation["type"]
    reason = recommendation.get("reason", "")
    print(f"\n  Recommended next session type: {rec_type} — {SESSION_TYPES.get(rec_type, 'Unknown')}")
    if reason:
        print(f"  Why: {reason}")
    print("  Press Enter to accept, or type A-F to override.")
    choice = input("  Session type> ").strip().upper()
    if not choice:
        return rec_type, None
    if choice not in SESSION_TYPES:
        print("  Invalid choice. Using recommended type.")
        return rec_type, None
    if choice == rec_type:
        return rec_type, None

    print(f"\n  Pushback: the engine recommends {rec_type} because {reason}")
    print("  If you still want to override, type the same letter again. Otherwise press Enter to accept recommendation.")
    confirm = input("  Confirm override> ").strip().upper()
    if confirm == choice:
        return choice, f"Client overrode engine recommendation {rec_type} in favor of {choice}."
    return rec_type, None

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
                        help="Force a specific session type (A-F)")
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
    recommendation = recommend_session_type(args.client)
    selected_type = args.session_type
    override_reason = None
    if not selected_type:
        try:
            selected_type, override_reason = confirm_session_type(args.client, recommendation)
        except EOFError:
            selected_type = recommendation["type"]
    session = Session(
        args.client,
        session_type=selected_type,
        model=args.model,
        recommendation=recommendation,
        override_reason=override_reason,
    )
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
