#!/usr/bin/env python3
"""
Action Session — Interactive Behavioural Change Coaching Sessions
Uses: Whisper (STT) + Claude Code CLI (AI) + Edge TTS (speech)
Runs on your Mac using your Claude Max subscription. Zero extra cost.

Parallel programme to Breakthrough (ISTDP). This is the behavioural engine:
progressive exposure, body regulation, attention training, shame recovery.
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

VOICE = "en-GB-RyanNeural"
VOICE_RATE = "-5%"

WHISPER_MODEL = "base"

SAMPLE_RATE = 16000
CHANNELS = 1
SILENCE_THRESHOLD = 0.015
SILENCE_DURATION = 2.0
MIN_RECORDING_DURATION = 0.5

MAX_CONTEXT_EXCHANGES = 15

# Session types for the Action Programme
SESSION_TYPES = {
    "D": "Daily Action Check-in — review exposures, log evidence, assign tomorrow's target",
    "W": "Weekly Review — full 9-question review, set next week's 3 commitments",
    "E": "Exposure Coaching — real-time pre/during/post exposure regulation and debrief",
}

# Paths — action script lives in action/, sessions shared with breakthrough
BASE_DIR = Path(__file__).parent
PROJECT_DIR = BASE_DIR.parent
SESSIONS_DIR = PROJECT_DIR / "breakthrough" / "sessions"  # shared with breakthrough
PROGRAMME_FILE = PROJECT_DIR / "The_Action_Programme.md"

DEFAULT_SCOREBOARD = {
    "version": 1,
    "current_week": "",
    "sessions": [],
    "recommended_next_type": None,
    "recommended_reason": "",
    "current_exposure_level": 1,
    "gym_streak": 0,
    "cyclic_sighing_streak": 0,
    "att_practice_days": 0,
    "metrics": {
        "avg_prediction_gap": None,
        "exposures_this_week": 0,
        "avoidances_this_week": 0,
        "shame_spirals_this_week": 0,
    },
}


def new_scoreboard():
    board = copy.deepcopy(DEFAULT_SCOREBOARD)
    board["current_week"] = datetime.now().strftime("%Y-W%W")
    return board


# ---------------------------------------------------------------------------
# Programme Parser
# ---------------------------------------------------------------------------

def _parse_programme():
    """Parse The Action Programme into named sections by ## headers."""
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


_programme_cache = None


def _get_programme():
    global _programme_cache
    if _programme_cache is None:
        _programme_cache = _parse_programme()
    return _programme_cache


def load_programme():
    """Load the full Action Programme document."""
    if PROGRAMME_FILE.exists():
        return PROGRAMME_FILE.read_text()
    print(f"WARNING: Programme file not found at {PROGRAMME_FILE}")
    return ""


def load_programme_sections(keys):
    """Load specific named sections of the Action Programme."""
    sections = _get_programme()
    if not sections:
        return load_programme()
    parts = [sections[k] for k in keys if k in sections]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Context Configuration per Session Type
# ---------------------------------------------------------------------------

# programme_sections: list of keys (section numbers / Tool numbers), or None = full.
# max_sessions: how many recent action session summaries to load.
CONTEXT_CONFIG = {
    "D": {
        "programme_sections": ["1", "3", "4"],
        "max_sessions": 2,
        "evidence_log": True,
        "exposure_tracker": True,
        "for_action_flags": True,
    },
    "W": {
        "programme_sections": ["1", "4", "5", "9"],
        "max_sessions": 0,  # weekly review reads all week's data separately
        "evidence_log": True,
        "exposure_tracker": True,
        "for_action_flags": True,
    },
    "E": {
        "programme_sections": ["1", "2", "3"],
        "max_sessions": 1,
        "evidence_log": False,
        "exposure_tracker": True,
        "for_action_flags": False,
    },
}

# Tools relevant to each session type (always loaded)
SESSION_TOOL_MAP = {
    "D": ["Tool1", "Tool2", "Tool5", "Tool6", "Tool7", "Tool9", "Tool10"],
    "W": ["Tool2", "Tool7", "Tool8", "Tool9", "Tool10"],
    "E": ["Tool1", "Tool2", "Tool3", "Tool4", "Tool5", "Tool8", "Tool9"],
}


# ---------------------------------------------------------------------------
# Client Data Loaders
# ---------------------------------------------------------------------------

def load_client_profile(client_name):
    path = SESSIONS_DIR / client_name / "profile.md"
    return path.read_text() if path.exists() else ""


def load_all_action_summaries(client_name, max_sessions=None):
    """Load summaries from previous action sessions."""
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return ""
    session_files = sorted(client_dir.glob("*_action_*.md"))
    if max_sessions is not None and max_sessions > 0:
        session_files = session_files[-max_sessions:]
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


def load_evidence_log(client_name):
    path = SESSIONS_DIR / client_name / "evidence_log.md"
    return path.read_text() if path.exists() else ""


def load_recent_evidence_log(client_name, days=7):
    """Load evidence log entries from the past N days."""
    path = SESSIONS_DIR / client_name / "evidence_log.md"
    if not path.exists():
        return ""
    content = path.read_text()
    cutoff = datetime.now() - timedelta(days=days)
    lines = content.split("\n")
    result_lines = []
    entry_lines = []
    entry_date = None
    date_re = re.compile(r"^### (\d{4}-\d{2}-\d{2})")
    for line in lines:
        m = date_re.match(line)
        if m:
            if entry_lines and entry_date and entry_date >= cutoff:
                result_lines.extend(entry_lines)
            entry_lines = [line]
            try:
                entry_date = datetime.strptime(m.group(1), "%Y-%m-%d")
            except ValueError:
                entry_date = None
        elif entry_lines:
            entry_lines.append(line)
        else:
            result_lines.append(line)
    if entry_lines and entry_date and entry_date >= cutoff:
        result_lines.extend(entry_lines)
    return "\n".join(result_lines)


def load_exposure_tracker(client_name):
    path = SESSIONS_DIR / client_name / "exposure_tracker.md"
    return path.read_text() if path.exists() else ""


def extract_thread_from_last_session(client_name):
    """Extract the tomorrow's target and last exchanges from the most recent action session."""
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return ""
    session_files = sorted(client_dir.glob("*_action_*.md"))
    if not session_files:
        return ""
    content = session_files[-1].read_text()

    thread_text = ""

    # Extract TOMORROW'S TARGET or THREAD from summary
    lines = content.split("\n")
    in_thread = False
    for line in lines:
        upper = line.upper()
        if "TOMORROW" in upper and "TARGET" in upper:
            in_thread = True
            thread_text += line + "\n"
            continue
        if in_thread:
            if line.strip().startswith(("#", "14.")) or (line.strip() and line.strip()[0].isdigit() and "." in line[:4]):
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
        elif line.startswith("**Coach:**"):
            if current_speaker and current_text:
                exchanges.append((current_speaker, "\n".join(current_text)))
            current_speaker = "Coach"
            current_text = [line.replace("**Coach:**", "").strip()]
        elif current_speaker and line.strip() and not line.startswith("---"):
            current_text.append(line)

    if current_speaker and current_text:
        exchanges.append((current_speaker, "\n".join(current_text)))

    last_exchanges = exchanges[-6:] if len(exchanges) >= 6 else exchanges
    if last_exchanges:
        thread_text += "\nLAST EXCHANGES FROM PREVIOUS SESSION:\n"
        for speaker, text in last_exchanges:
            thread_text += f"{speaker}: {text[:200]}\n"

    return thread_text.strip()


def load_for_action_flags(client_name):
    """Load flags from ISTDP programme for this programme."""
    path = SESSIONS_DIR / client_name / "for_action.md"
    return path.read_text() if path.exists() else ""


def load_for_breakthrough_flags(client_name):
    """Load flags this programme has sent to ISTDP (for reference)."""
    path = SESSIONS_DIR / client_name / "for_breakthrough.md"
    return path.read_text() if path.exists() else ""


def load_somatic_baseline(client_name):
    """Shared metric with ISTDP programme."""
    path = SESSIONS_DIR / client_name / "somatic_baseline.md"
    return path.read_text() if path.exists() else ""


# ---------------------------------------------------------------------------
# Tracking File Management
# ---------------------------------------------------------------------------

def ensure_tracking_files(client_name):
    """Ensure all action programme tracking files exist."""
    client_dir = SESSIONS_DIR / client_name
    client_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "evidence_log.md": (
            f"# Evidence Log — {client_name.title()}\n\n"
            "Daily exposure evidence: predictions vs reality. Each entry proves the threat system wrong.\n\n"
            "**Fields:** Date, Gym, Sighing, Exposure (level + description), Prediction, Reality, "
            "Anxiety before/after (0-10), Safety behaviours dropped, Attention focus, Shame spiral, One-sentence summary.\n\n---\n"
        ),
        "exposure_tracker.md": (
            f"# Exposure Tracker — {client_name.title()}\n\n"
            "Current exposure level and progression history.\n\n"
            "**Current Level:** 1 — Baseline Safe\n\n"
            "## Exposure Hierarchy\n"
            "| Level | Label | Status |\n"
            "|-------|-------|--------|\n"
            "| 1 | Baseline Safe | ACTIVE |\n"
            "| 2 | Mild Visibility | Locked |\n"
            "| 3 | Low Discomfort | Locked |\n"
            "| 4 | Moderate Social | Locked |\n"
            "| 5 | Moderate Threat | Locked |\n"
            "| 6 | Active Engagement | Locked |\n"
            "| 7 | High Visibility | Locked |\n"
            "| 8 | Professional Exposure | Locked |\n"
            "| 9 | Peak Performance | Locked |\n"
            "| 10 | Unshakeable | Locked |\n\n"
            "## Level Progression Log\n\n---\n"
        ),
        "for_action.md": (
            f"# Flags for Action Programme — {client_name.title()}\n\n"
            "Material from ISTDP Breakthrough sessions relevant to the Action Programme.\n"
            "Items here inform exposure targets, micro-action calibration, and defence awareness.\n\n---\n"
        ),
        "for_breakthrough.md": (
            f"# Flags for Breakthrough Programme — {client_name.title()}\n\n"
            "Material from Action Programme sessions relevant to ISTDP work.\n"
            "Shame, rage, grief, or defence patterns surfaced during exposures.\n\n---\n"
        ),
        "action_auto_state.md": (
            f"# Action Auto State — {client_name.title()}\n\n"
            "Machine-generated snapshot read at the start of every action session.\n"
        ),
    }

    for filename, default_content in files.items():
        path = client_dir / filename
        if not path.exists():
            path.write_text(default_content)

    scoreboard_path = client_dir / "action_scoreboard.json"
    if not scoreboard_path.exists():
        scoreboard = new_scoreboard()
        scoreboard_path.write_text(json.dumps(scoreboard, indent=2))


def load_scoreboard(client_name):
    path = SESSIONS_DIR / client_name / "action_scoreboard.json"
    if not path.exists():
        ensure_tracking_files(client_name)
    try:
        return json.loads(path.read_text())
    except Exception:
        return new_scoreboard()


def save_scoreboard(client_name, scoreboard):
    path = SESSIONS_DIR / client_name / "action_scoreboard.json"
    path.write_text(json.dumps(scoreboard, indent=2))


def load_auto_state(client_name):
    path = SESSIONS_DIR / client_name / "action_auto_state.md"
    return path.read_text() if path.exists() else ""


def current_week_key(now=None):
    now = now or datetime.now()
    return now.strftime("%Y-W%W")


def sessions_done_today(client_name):
    today = datetime.now().strftime("%Y-%m-%d")
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return 0
    return len(list(client_dir.glob(f"{today}_action_*.md")))


# ---------------------------------------------------------------------------
# Summary Parsing Utilities
# ---------------------------------------------------------------------------

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


def extract_summary_field(summary, field_prefix):
    for line in summary.split("\n"):
        if line.upper().startswith(field_prefix.upper()):
            return line.split(":", 1)[-1].strip()
    return ""


def parse_exposure_entries(summary):
    """Extract exposure descriptions from summary."""
    data = extract_machine_data(summary)
    return data.get("exposures_completed", [])


def parse_for_breakthrough_flags(summary):
    """Extract emotional material flagged for ISTDP."""
    data = extract_machine_data(summary)
    return data.get("flag_for_breakthrough", [])


def parse_tomorrow_target(summary):
    """Extract tomorrow's exposure target from summary."""
    data = extract_machine_data(summary)
    return data.get("tomorrow_target", "")


# ---------------------------------------------------------------------------
# Session Type Selection
# ---------------------------------------------------------------------------

def get_recent_action_types(client_name, count=5):
    """Get the session types from recent action sessions."""
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return []
    session_files = sorted(client_dir.glob("*_action_*.md"), reverse=True)
    types = []
    for f in session_files[:count]:
        content = f.read_text()
        for line in content.split("\n"):
            if line.startswith("**Session Type:"):
                for char in SESSION_TYPES:
                    if char in line.split(":")[-1]:
                        types.append(char)
                        break
                break
    return types


def recommend_session_type(client_name):
    """Recommend the best next action session type."""
    ensure_tracking_files(client_name)
    today_sessions = sessions_done_today(client_name)

    # Check if it's Sunday (weekly review day)
    if datetime.now().weekday() == 6:  # Sunday
        return {"type": "W", "reason": "Sunday is weekly review day."}

    # Default to daily check-in
    if today_sessions == 0:
        return {"type": "D", "reason": "Daily check-in — review exposures, log evidence, assign target."}

    # If already done a daily, suggest exposure coaching
    return {"type": "E", "reason": "Daily check-in done. Exposure coaching available for live support."}


def select_session_type(client_name):
    return recommend_session_type(client_name)["type"]


# ---------------------------------------------------------------------------
# System Prompt Builder
# ---------------------------------------------------------------------------

def build_system_prompt(client_name, session_type=None, mode="session"):
    """Build a context-efficient system prompt for the action session."""
    cfg_key = session_type if session_type in CONTEXT_CONFIG else "D"
    cfg = CONTEXT_CONFIG[cfg_key]

    # --- Programme sections ---
    prog_keys = cfg["programme_sections"]
    programme = load_programme_sections(prog_keys) if prog_keys else ""

    # --- Tool protocols ---
    tool_keys = SESSION_TOOL_MAP.get(cfg_key, [])
    tool_sections = load_programme_sections(tool_keys) if tool_keys else ""

    # --- Client data ---
    profile = load_client_profile(client_name)
    max_s = cfg["max_sessions"]
    summaries = load_all_action_summaries(client_name, max_sessions=max_s) if max_s > 0 else ""
    evidence = load_recent_evidence_log(client_name) if cfg.get("evidence_log") else ""
    exposure = load_exposure_tracker(client_name) if cfg.get("exposure_tracker") else ""
    flags = load_for_action_flags(client_name) if cfg.get("for_action_flags") else ""
    somatic = load_somatic_baseline(client_name)
    auto_state = load_auto_state(client_name) if mode == "session" else ""
    scoreboard = json.dumps(load_scoreboard(client_name), indent=2)

    # --- Assemble ---
    prompt = "You are running a live Action Programme behavioural coaching session.\n\n"

    prompt += """=== YOUR ROLE ===
You are a COACH, not a therapist. This programme is about ACTION, not processing.
- Be prescriptive. Assign exposures. Don't ask "what would you like to work on?" — tell the client what the programme requires.
- Be warm but firm. When avoidance is reported, don't shame — but don't let it slide. "The threat system won today. That's data, not a verdict. What's the smallest step you can take in the next 2 hours?"
- Celebrate deposits. "That's a deposit in the self-trust account. Your brain just got evidence that the prediction was wrong."
- Never collude with avoidance. If reasons are given for not doing an exposure, redirect to the micro-step.
- If emotional material surfaces (shame, rage, grief), flag it for the ISTDP Breakthrough Programme. Do NOT process it here. "That's material for your next Breakthrough session. In this programme, we do. What's the exposure for today?"
- NEVER use bullet points or markdown formatting — you are SPEAKING aloud.
- Keep responses spoken-length (2-4 sentences typically). SHORT responses land harder.
=== END ROLE ===

"""

    if programme:
        prompt += f"=== THE ACTION PROGRAMME ===\n{programme}\n=== END PROGRAMME ===\n\n"

    if tool_sections:
        prompt += f"=== ACTION TOOLS (protocols for this session) ===\n{tool_sections}\n=== END TOOLS ===\n\n"

    if profile:
        prompt += f"=== CLIENT PROFILE ===\n{profile}\n=== END PROFILE ===\n\n"

    if summaries:
        label = f"LAST {max_s} ACTION SESSION SUMMARIES" if max_s else "ACTION SESSION SUMMARIES"
        prompt += f"=== {label} ===\n{summaries}\n=== END SUMMARIES ===\n\n"

    if evidence:
        prompt += f"=== EVIDENCE LOG (last 7 days) ===\n{evidence}\n=== END EVIDENCE LOG ===\n\n"

    if exposure:
        prompt += f"=== EXPOSURE TRACKER ===\n{exposure}\n=== END EXPOSURE TRACKER ===\n\n"

    if somatic:
        prompt += f"=== SOMATIC BASELINE (shared with ISTDP) ===\n{somatic}\n=== END SOMATIC BASELINE ===\n\n"

    if flags:
        prompt += f"=== FLAGS FROM ISTDP PROGRAMME ===\n{flags}\n=== END FLAGS ===\n\n"

    if auto_state:
        prompt += f"=== AUTO STATE ===\n{auto_state}\n=== END AUTO STATE ===\n\n"

    if scoreboard:
        prompt += f"=== ACTION SCOREBOARD ===\n{scoreboard}\n=== END SCOREBOARD ===\n\n"

    # Thread from last session
    if mode == "session":
        thread = extract_thread_from_last_session(client_name)
        if thread:
            prompt += f"=== UNFINISHED THREAD FROM LAST SESSION ===\n{thread}\n=== END THREAD ===\n\n"

    # Session-type-specific instructions
    type_instructions = {
        "D": """=== DAILY ACTION CHECK-IN (5-10 minutes) ===

OPENING PROTOCOL:
1. Review the evidence log since last session
2. Ask: "What exposures did you complete? What did you avoid?"
3. For completed exposures: "What did you predict? What actually happened? Where's the gap?"
4. For avoided exposures: "What was the threat? What did your body do? What's the smallest version of that exposure you could do today?"
5. Check: gym status, cyclic sighing status, ATT practice status, shame spiral status

CLOSING PROTOCOL:
1. State tomorrow's exposure target — specific, time-bound
2. State the prediction to test
3. Confirm accountability
4. If emotional material surfaced, flag it: "Bring this to your next Breakthrough session"

EVIDENCE LOGGING — require specific data for each exposure:
- The specific prediction before (not vague)
- What actually happened (observable facts)
- Anxiety rating before and after (0-10)
- Safety behaviours dropped
- Attention focus (internal/external/mixed)
- One-sentence proof statement

Do NOT accept vague reports like "it went fine." Push for specifics: "What exactly did you predict would happen? And what exactly did happen?"
=== END CHECK-IN ===
""",
        "W": """=== WEEKLY REVIEW (15-20 minutes) ===

Run through these 9 questions systematically:
1. How many exposures completed this week?
2. How many avoided? What was the pattern in the avoidance?
3. What level am I working at? Ready to move up?
4. What's the gap between predictions and reality across the week?
5. ATT practice: how many days?
6. Gym: how many days?
7. Shame spirals: how many? What triggered them?
8. What material from this week should go to the ISTDP programme?
9. Next week's 3 committed exposures (state them clearly)

AFTER THE REVIEW:
- Update exposure level if criteria are met (see exposure hierarchy unlock criteria)
- Set 3 specific exposure commitments for next week
- Flag any emotional material for Breakthrough
- Check the fortnightly somatic baseline if due

Be honest. If progress stalled, say so. "The threat system held ground this week. That's data. The question is: what's the smallest exposure we can lock in for Monday?"
=== END WEEKLY REVIEW ===
""",
        "E": """=== EXPOSURE COACHING (5-15 minutes) ===

This is REAL-TIME coaching. The client is about to do, is doing, or just did an exposure.

PRE-EXPOSURE:
1. Body regulation first — guide through cyclic sighing (minimum 3 cycles)
2. State the specific prediction: "If I do X, then Y will happen"
3. Rate pre-exposure anxiety 0-10
4. Identify safety behaviours to drop
5. Set external attention focus: "Focus on the other person, the content, the environment. Not on yourself."

DURING EXPOSURE (if live):
- Brief check-ins only: "What's happening? Stay with it. Focus externally."
- Do NOT process — just coach through it

POST-EXPOSURE:
1. Rate post-exposure anxiety 0-10
2. Record what actually happened vs the prediction
3. Identify the gap: "Your brain predicted X. Reality delivered Y. That gap is evidence."
4. Log it
5. Check for post-event processing: "Is the replay starting? That's the threat system trying to rewrite what just happened. Let it go. What actually happened?"
6. If shame activated, deploy compassionate letter protocol or flag for Breakthrough

MICRO-STEP PROTOCOL (when full exposure feels impossible):
Every exposure has a minimum viable version. Find it:
- Can't make the call → send the text
- Can't send the text → open the chat and read
- Can't open the chat → hold the phone for 30 seconds
The micro-step still counts as a deposit. It breaks the avoidance loop.
=== END EXPOSURE COACHING ===
""",
    }

    if session_type and session_type in type_instructions:
        prompt += type_instructions[session_type]

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
                if (has_speech and silence_start and
                        time.time() - silence_start >= SILENCE_DURATION):
                    break
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
    global _whisper_model
    if _whisper_model is None:
        print("  Loading Whisper model (first time may take a minute)...")
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(WHISPER_MODEL, device="cpu",
                                       compute_type="int8")
    return _whisper_model


def transcribe(audio):
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
    import edge_tts
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    try:
        communicate = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE)
        await communicate.save(tmp.name)
        subprocess.run(["afplay", tmp.name], check=True, capture_output=True)
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)


def speak(text):
    print(f"\n  \033[34m🔊 Coach:\033[0m {text}\n")
    try:
        asyncio.run(_speak_async(text))
    except Exception as e:
        print(f"  (TTS error: {e} — response shown as text above)")


# ---------------------------------------------------------------------------
# AI Response (Claude or Ollama)
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
    print("  \033[33m⏳ Processing...\033[0m", flush=True)

    full_prompt = system_prompt + "\n\n"

    recent = conversation[-MAX_CONTEXT_EXCHANGES:]
    if recent:
        full_prompt += "=== CONVERSATION SO FAR ===\n"
        for role, msg in recent:
            label = "Client" if role == "user" else "Coach"
            full_prompt += f"{label}: {msg}\n\n"
        full_prompt += "=== END CONVERSATION ===\n\n"

    full_prompt += f"Client just said: {user_message}\n\n"
    full_prompt += "Respond as the coach. Speak naturally — this will be read aloud."

    try:
        if model == "claude":
            response, provider, err = _run_model_prompt(full_prompt, timeout=120)
            if not response:
                if err:
                    print(f"  {provider.capitalize()} error: {err[:200]}")
                return "I'm here. What exposure are we working on today?"
            return response

        elif model.startswith("ollama-"):
            ollama_models = {
                "ollama-r1:8b": "deepseek-r1:8b",
                "ollama-r1:14b": "deepseek-r1:14b",
                "ollama-r1:32b": "deepseek-r1:32b",
                "ollama-llama3.1:8b": "llama3.1:8b",
            }
            ollama_model = ollama_models.get(model, "deepseek-r1:14b")
            try:
                response_text = ""
                r = requests.post(
                    "http://localhost:11434/api/generate",
                    json={"model": ollama_model, "prompt": full_prompt, "stream": True},
                    timeout=180
                )
                r.raise_for_status()
                for line in r.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        response_text += chunk.get("response", "")
                if not response_text.strip():
                    return "I'm here. What exposure are we working on today?"
                return _clean_model_text(response_text)
            except requests.exceptions.ConnectionError:
                print("\n  ERROR: Ollama not running at localhost:11434")
                print("  Start Ollama with: ollama serve")
                return "I'm here. What exposure are we working on today?"
        else:
            return "Unknown model. Use 'claude' or 'ollama-*'."

    except subprocess.TimeoutExpired:
        return "Let's focus. What's the exposure target right now?"
    except FileNotFoundError:
        print("\n  ERROR: 'claude' command not found.")
        print("  Make sure Claude Code is installed: npm install -g @anthropic-ai/claude-code")
        sys.exit(1)
    except Exception as e:
        print(f"  Error: {e}")
        return "Stay with it. What's the next action?"


# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, client_name, session_type=None, mode="session", model="claude"):
        self.client_name = client_name
        self.client_dir = SESSIONS_DIR / client_name
        self.client_dir.mkdir(parents=True, exist_ok=True)
        ensure_tracking_files(client_name)
        self.mode = mode
        self.model = model

        self.start_time = datetime.now()
        self.conversation = []

        self.recommendation = recommend_session_type(client_name)
        self.session_type = session_type or self.recommendation["type"]
        self.session_number = self._next_session_number()

        if mode == "review":
            self.session_file = None  # weekly review saved separately
        else:
            self.session_file = self.client_dir / (
                f"{self.start_time.strftime('%Y-%m-%d')}"
                f"_action_{self.session_number:02d}.md"
            )

        self.system_prompt = build_system_prompt(client_name, self.session_type, mode)
        if mode == "session":
            self._rebuild_auto_state()

    def _next_session_number(self):
        today = self.start_time.strftime('%Y-%m-%d')
        existing = list(self.client_dir.glob(f"{today}_action_*.md"))
        return len(existing) + 1

    def add_exchange(self, user_msg, claude_msg):
        self.conversation.append(("user", user_msg))
        self.conversation.append(("assistant", claude_msg))
        self._save_transcript()

    def _save_transcript(self):
        if self.session_file is None:
            return

        duration = datetime.now() - self.start_time
        minutes = int(duration.total_seconds() / 60)

        content = f"""# Action Session — {self.client_name.title()}
**Date:** {self.start_time.strftime('%Y-%m-%d %H:%M')}
**Session:** {self.session_number}
**Session Type:** {self.session_type} — {SESSION_TYPES.get(self.session_type, '')}
**Duration:** {minutes} minutes (in progress)

---

## Transcript

"""
        elapsed = 0
        for i in range(0, len(self.conversation), 2):
            user_msg = self.conversation[i][1] if i < len(self.conversation) else ""
            claude_msg = self.conversation[i+1][1] if i+1 < len(self.conversation) else ""
            content += f"**[{elapsed:02d}:00] You:**\n{user_msg}\n\n"
            content += f"**Coach:**\n{claude_msg}\n\n---\n\n"
            elapsed += 2

        self.session_file.write_text(content)

    def generate_summary(self):
        """Ask Claude to generate an action session summary."""
        if not self.conversation:
            return

        if self.session_file is None:
            return

        print("\n  Generating session summary...")

        transcript = "\n".join(
            f"{'Client' if r == 'user' else 'Coach'}: {m}"
            for r, m in self.conversation
        )

        summary_prompt = f"""You just completed an Action Programme behavioural coaching session.
Session type: {self.session_type} — {SESSION_TYPES.get(self.session_type, 'Unknown')}

Here is the full transcript:
{transcript}

Generate a concise session summary with these sections:
1. SESSION SUMMARY (2-3 sentences — what happened, what was worked on)
2. SESSION TYPE USED: {self.session_type}
3. EXPOSURES COMPLETED (list each with: level, description, prediction, reality, anxiety before/after)
4. EXPOSURES AVOIDED (list each with: what was the threat, what the body did, micro-step offered)
5. SAFETY BEHAVIOURS DROPPED (which ones were dropped during exposures)
6. ATTENTION FOCUS (internal/external/mixed across the session)
7. GYM STATUS (Y/N + details)
8. CYCLIC SIGHING STATUS (Y/N)
9. ATT PRACTICE STATUS (Y/N + details)
10. SHAME SPIRALS (Y/N — if Y, what triggered, what protocol deployed)
11. PREDICTION VS REALITY GAP (summary of the evidence generated)
12. MATERIAL FOR ISTDP (any emotional material that surfaced — shame, rage, grief, defence patterns — flag for Breakthrough)
13. TOMORROW'S TARGET (specific exposure, time-bound, with prediction to test)
14. WEEKLY COMMITMENTS STATUS (if weekly review: the 3 commitments for next week)

Then add a final section exactly like this:
## MACHINE DATA
```json
{{
  "session_type": "{self.session_type}",
  "exposures_completed": ["description 1", "description 2"],
  "exposures_avoided": ["description 1"],
  "exposure_level_worked": 2,
  "gym": true,
  "cyclic_sighing": true,
  "att_practice": false,
  "shame_spiral": false,
  "avg_anxiety_drop": 3.5,
  "flag_for_breakthrough": ["emotional material to flag"],
  "tomorrow_target": "specific exposure description",
  "recommended_next_type": "D",
  "summary_status": "ok"
}}
```

Be honest. If avoidance won, say so. Evidence over theory. Deposits over plans."""

        try:
            summary, _, err = _run_model_prompt(summary_prompt, timeout=120)
            summary = summary or ""
            data = extract_machine_data(summary)
            if not data.get("summary_status"):
                retry_prompt = summary_prompt + "\n\nYour previous response was missing or malformed in the MACHINE DATA JSON block. Regenerate the full summary and ensure the MACHINE DATA block is valid JSON."
                retry_summary, _, _ = _run_model_prompt(retry_prompt, timeout=120)
                retry_summary = retry_summary or ""
                if extract_machine_data(retry_summary).get("summary_status"):
                    summary = retry_summary
            if not summary and err:
                raise RuntimeError(err)
        except Exception:
            summary = "(Summary generation failed — review transcript manually)"

        # Append summary to session file
        duration = datetime.now() - self.start_time
        minutes = int(duration.total_seconds() / 60)

        content = self.session_file.read_text()
        content = re.sub(r'\(in progress\)', '', content)
        content += f"\n\n## Session Summary\n\n{summary}\n"
        self.session_file.write_text(content)

        # Update tracking files
        self._update_evidence_log(summary)
        self._update_exposure_tracker(summary)
        self._update_for_breakthrough(summary)
        self._update_scoreboard(summary)
        self._rebuild_auto_state(summary)

        print(f"\n  📝 Session saved: {self.session_file}")
        return summary

    def _update_evidence_log(self, summary):
        """Append today's evidence to the evidence log."""
        log_path = self.client_dir / "evidence_log.md"
        data = extract_machine_data(summary)

        entry = f"\n### {self.start_time.strftime('%Y-%m-%d')} — Action Session {self.session_number} (Type {self.session_type})\n\n"
        entry += f"- **Gym:** {'Yes' if data.get('gym') else 'No'}\n"
        entry += f"- **Cyclic sighing:** {'Yes' if data.get('cyclic_sighing') else 'No'}\n"
        entry += f"- **ATT practice:** {'Yes' if data.get('att_practice') else 'No'}\n"
        entry += f"- **Exposure level worked:** {data.get('exposure_level_worked', 'N/A')}\n"

        exposures = data.get("exposures_completed", [])
        if exposures:
            entry += "- **Exposures completed:**\n"
            for exp in exposures:
                entry += f"  - {exp}\n"

        avoided = data.get("exposures_avoided", [])
        if avoided:
            entry += "- **Exposures avoided:**\n"
            for av in avoided:
                entry += f"  - {av}\n"

        entry += f"- **Avg anxiety drop:** {data.get('avg_anxiety_drop', 'N/A')}\n"
        entry += f"- **Shame spiral:** {'Yes' if data.get('shame_spiral') else 'No'}\n"
        entry += f"- **Tomorrow's target:** {data.get('tomorrow_target', 'TBD')}\n"
        entry += "\n---\n"

        existing = log_path.read_text() if log_path.exists() else (
            f"# Evidence Log — {self.client_name.title()}\n\n"
            "Daily exposure evidence: predictions vs reality.\n\n---\n"
        )
        log_path.write_text(existing + entry)

    def _update_exposure_tracker(self, summary):
        """Update exposure tracker if level should change."""
        data = extract_machine_data(summary)
        level_worked = data.get("exposure_level_worked")
        if not level_worked:
            return

        tracker_path = self.client_dir / "exposure_tracker.md"
        existing = tracker_path.read_text() if tracker_path.exists() else ""

        entry = f"\n### {self.start_time.strftime('%Y-%m-%d')} — Level {level_worked} exposure\n"
        exposures = data.get("exposures_completed", [])
        for exp in exposures:
            entry += f"- {exp}\n"
        entry += "\n"

        tracker_path.write_text(existing + entry)

    def _update_for_breakthrough(self, summary):
        """Append emotional material flagged for ISTDP."""
        flags = parse_for_breakthrough_flags(summary)
        if not flags:
            return

        path = self.client_dir / "for_breakthrough.md"
        existing = path.read_text() if path.exists() else (
            f"# Flags for Breakthrough Programme — {self.client_name.title()}\n\n"
            "Material from Action Programme sessions relevant to ISTDP work.\n\n---\n"
        )

        entry = f"\n### {self.start_time.strftime('%Y-%m-%d')} — Action Session {self.session_number}\n\n"
        for flag in flags:
            entry += f"- {flag}\n"
        entry += "\n"

        path.write_text(existing + entry)

    def _update_scoreboard(self, summary):
        scoreboard = load_scoreboard(self.client_name)
        data = extract_machine_data(summary)
        week = current_week_key(self.start_time)
        scoreboard["current_week"] = week

        # Reset weekly metrics on week rollover
        metrics = scoreboard.get("metrics", {})
        old_week = scoreboard.get("current_week", "")
        if old_week and old_week != week:
            metrics["exposures_this_week"] = 0
            metrics["avoidances_this_week"] = 0
            metrics["shame_spirals_this_week"] = 0

        if data.get("gym"):
            scoreboard["gym_streak"] = scoreboard.get("gym_streak", 0) + 1
        else:
            scoreboard["gym_streak"] = 0

        if data.get("cyclic_sighing"):
            scoreboard["cyclic_sighing_streak"] = scoreboard.get("cyclic_sighing_streak", 0) + 1
        else:
            scoreboard["cyclic_sighing_streak"] = 0

        if data.get("att_practice"):
            scoreboard["att_practice_days"] = scoreboard.get("att_practice_days", 0) + 1

        exposures = len(data.get("exposures_completed", []))
        avoidances = len(data.get("exposures_avoided", []))
        metrics["exposures_this_week"] = metrics.get("exposures_this_week", 0) + exposures
        metrics["avoidances_this_week"] = metrics.get("avoidances_this_week", 0) + avoidances
        if data.get("shame_spiral"):
            metrics["shame_spirals_this_week"] = metrics.get("shame_spirals_this_week", 0) + 1
        if data.get("avg_anxiety_drop"):
            metrics["avg_prediction_gap"] = data["avg_anxiety_drop"]

        level = data.get("exposure_level_worked")
        if level and level > scoreboard.get("current_exposure_level", 1):
            scoreboard["current_exposure_level"] = level

        scoreboard["metrics"] = metrics

        # Session record
        scoreboard.setdefault("sessions", []).append({
            "date": self.start_time.strftime("%Y-%m-%d"),
            "type": self.session_type,
            "week": week,
            "exposures": exposures,
            "avoidances": avoidances,
        })
        scoreboard["sessions"] = scoreboard["sessions"][-30:]

        scoreboard["recommended_next_type"] = data.get("recommended_next_type", "D")
        scoreboard["recommended_reason"] = data.get("tomorrow_target", "")
        scoreboard["summary_status"] = data.get("summary_status", "fallback")

        save_scoreboard(self.client_name, scoreboard)

    def _rebuild_auto_state(self, summary=None):
        scoreboard = load_scoreboard(self.client_name)
        auto_path = self.client_dir / "action_auto_state.md"
        data = extract_machine_data(summary) if summary else {}
        lines = [
            f"# Action Auto State — {self.client_name.title()}",
            "",
            "## Today",
            f"- Action sessions done today: {sessions_done_today(self.client_name)}",
            f"- Current week: {scoreboard.get('current_week', current_week_key())}",
            "",
            "## Streaks",
            f"- Gym streak: {scoreboard.get('gym_streak', 0)} days",
            f"- Cyclic sighing streak: {scoreboard.get('cyclic_sighing_streak', 0)} days",
            f"- ATT practice days total: {scoreboard.get('att_practice_days', 0)}",
            "",
            "## Exposure Level",
            f"- Current level: {scoreboard.get('current_exposure_level', 1)}",
            "",
            "## This Week",
            f"- Exposures completed: {scoreboard.get('metrics', {}).get('exposures_this_week', 0)}",
            f"- Exposures avoided: {scoreboard.get('metrics', {}).get('avoidances_this_week', 0)}",
            f"- Shame spirals: {scoreboard.get('metrics', {}).get('shame_spirals_this_week', 0)}",
            "",
            "## Tomorrow's Target",
            f"- {data.get('tomorrow_target', 'See latest session summary.')}",
            "",
            "## Flags from ISTDP",
        ]
        flags = load_for_action_flags(self.client_name)
        if flags and len(flags.strip().split("\n")) > 5:
            # Show last few lines of flags
            flag_lines = [l for l in flags.strip().split("\n") if l.startswith("- ")]
            for fl in flag_lines[-3:]:
                lines.append(f"  {fl}")
        else:
            lines.append("- None pending")

        auto_path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Weekly Review Generation
# ---------------------------------------------------------------------------

def generate_weekly_review(client_name):
    """Generate a structured weekly review from the past week's action data."""
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        print(f"  No sessions found for {client_name}")
        return

    week_content = []

    evidence = load_recent_evidence_log(client_name, days=7)
    if evidence:
        week_content.append(f"=== EVIDENCE LOG (last 7 days) ===\n{evidence}")

    exposure = load_exposure_tracker(client_name)
    if exposure:
        week_content.append(f"=== EXPOSURE TRACKER ===\n{exposure}")

    somatic = load_somatic_baseline(client_name)
    if somatic:
        week_content.append(f"=== SOMATIC BASELINE ===\n{somatic}")

    flags_from_istdp = load_for_action_flags(client_name)
    if flags_from_istdp:
        week_content.append(f"=== FLAGS FROM ISTDP ===\n{flags_from_istdp}")

    flags_to_istdp = load_for_breakthrough_flags(client_name)
    if flags_to_istdp:
        week_content.append(f"=== FLAGS SENT TO ISTDP ===\n{flags_to_istdp}")

    if not week_content:
        print("  No action data found for the past week.")
        return

    all_content = "\n\n".join(week_content)

    review_prompt = build_system_prompt(client_name, session_type="W", mode="review")
    review_prompt += f"\n\n=== THIS WEEK'S DATA ===\n{all_content}\n=== END DATA ===\n\n"
    review_prompt += "Generate the weekly review now. Run through all 9 questions. Be thorough, honest, and specific."

    print("  Generating weekly review...")

    try:
        review, _, err = _run_model_prompt(review_prompt, timeout=180)
        if not review and err:
            raise RuntimeError(err)
    except Exception as e:
        print(f"  Error generating review: {e}")
        return

    reviews_dir = client_dir / "action_weekly_reviews"
    reviews_dir.mkdir(exist_ok=True)

    now = datetime.now()
    week_num = now.strftime("%Y-W%W")
    review_file = reviews_dir / f"{week_num}.md"

    review_content = f"""# Action Programme Weekly Review — {client_name.title()}
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
    print("\033[2J\033[H")
    print("=" * 60)
    if mode == "review":
        print("  ACTION PROGRAMME — WEEKLY REVIEW")
    else:
        print("  ACTION PROGRAMME — SESSION")
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
    if mode == "review":
        print("  Generating weekly review...")
    else:
        print("  Speak naturally. Pause for 2 seconds to send.")
        print("  Say 'end session' to close and save.")
        print("  Press Ctrl+C to emergency stop (still saves).")
    print("=" * 60)


def confirm_session_type(client_name, recommendation):
    """Show recommendation, allow override."""
    rec_type = recommendation["type"]
    reason = recommendation.get("reason", "")
    print(f"\n  Recommended session type: {rec_type} — {SESSION_TYPES.get(rec_type, 'Unknown')}")
    if reason:
        print(f"  Why: {reason}")
    print("  Press Enter to accept, or type D/W/E to override.")
    choice = input("  Session type> ").strip().upper()
    if not choice:
        return rec_type
    if choice not in SESSION_TYPES:
        print("  Invalid choice. Using recommended type.")
        return rec_type
    return choice


def run_text_mode(session):
    """Text mode for the action session."""
    print("\n  TEXT MODE — type your messages (type 'end session' to finish)\n")

    opening_msg = (
        f"Session is starting now. This is a Type {session.session_type} session: "
        f"{SESSION_TYPES.get(session.session_type, '')}. "
    )

    evidence = load_recent_evidence_log(session.client_name, days=3)
    if evidence and "###" in evidence:
        opening_msg += "Review the evidence log and open with the daily check-in protocol. "
    else:
        opening_msg += "No recent evidence log entries. Open by asking about today's gym status and what exposure is planned. "

    opening_msg += "Begin."

    opening = get_ai_response(
        session.system_prompt, [],
        opening_msg,
        model=session.model
    )
    print(f"\n  \033[34mCoach:\033[0m {opening}\n")
    session.conversation.append(("assistant", opening))
    session._save_transcript()

    end_words = ("end session", "end", "quit", "exit", "done")

    while True:
        try:
            user_input = input("  \033[32mYou:\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        if user_input.lower() in end_words:
            break

        response = get_ai_response(
            session.system_prompt, session.conversation, user_input,
            model=session.model
        )
        print(f"\n  \033[34mCoach:\033[0m {response}\n")
        session.add_exchange(user_input, response)


def run_voice_mode(session):
    """Full voice mode — speak and listen."""
    get_whisper_model()

    print("\n  Starting session...\n")

    opening_context = (
        f"This is action session number {session.session_number}, Type {session.session_type}: "
        f"{SESSION_TYPES.get(session.session_type, '')}. "
    )

    evidence = load_recent_evidence_log(session.client_name, days=3)
    if evidence and "###" in evidence:
        opening_context += "There are recent evidence log entries — review them and open with the daily check-in protocol. "
    else:
        opening_context += "No recent evidence entries. Ask about gym status and today's exposure plan. "

    flags = load_for_action_flags(session.client_name)
    if flags and "- " in flags:
        opening_context += "There are flags from the ISTDP programme — reference any relevant ones. "

    opening_context += "Begin."

    opening = get_ai_response(
        session.system_prompt, [],
        opening_context,
        model=session.model
    )
    speak(opening)
    session.conversation.append(("assistant", opening))
    session._save_transcript()

    while True:
        try:
            audio = record_until_silence()
            if audio is None:
                continue

            print("  \033[33m📝 Transcribing...\033[0m", flush=True)
            text = transcribe(audio)

            if not text or len(text.strip()) < 2:
                continue

            print(f"\n  \033[32m🎙️  You:\033[0m {text}")

            if any(phrase in text.lower() for phrase in
                   ["end session", "end the session", "stop session",
                    "that's it for today", "let's stop"]):

                closing = get_ai_response(
                    session.system_prompt, session.conversation,
                    "I'd like to end the session now. "
                    "[COACH INSTRUCTION: Before closing: "
                    "1) State tomorrow's specific exposure target and the prediction to test. "
                    "2) Confirm accountability — who will the client tell? "
                    "3) If emotional material surfaced, flag it for Breakthrough. "
                    "Then close with encouragement.]",
                    model=session.model
                )
                speak(closing)
                session.add_exchange(text, closing)
                break

            response = get_ai_response(
                session.system_prompt, session.conversation, text,
                model=session.model
            )
            speak(response)
            session.add_exchange(text, response)

        except KeyboardInterrupt:
            print("\n\n  Session interrupted.")
            break


def main():
    global VOICE, WHISPER_MODEL

    parser = argparse.ArgumentParser(description="Action Programme Session")
    parser.add_argument("--client", "-c", default="sapandeep",
                        help="Client name (default: sapandeep)")
    parser.add_argument("--text", "-t", action="store_true",
                        help="Use text mode instead of voice")
    parser.add_argument("--voice", "-v", default=None,
                        help="TTS voice (default: en-GB-RyanNeural)")
    parser.add_argument("--whisper-model", "-w", default=None,
                        help="Whisper model size (default: base)")
    parser.add_argument("--review", "-r", action="store_true",
                        help="Generate weekly review")
    parser.add_argument("--session-type", "-s", default=None,
                        choices=list(SESSION_TYPES.keys()),
                        help="Force a specific session type (D/W/E)")
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

    # Session mode
    recommendation = recommend_session_type(args.client)
    selected_type = args.session_type
    if not selected_type:
        try:
            selected_type = confirm_session_type(args.client, recommendation)
        except EOFError:
            selected_type = recommendation["type"]

    session = Session(
        args.client,
        session_type=selected_type,
        model=args.model,
    )
    print_banner(args.client, session.session_number, session.session_type)

    def shutdown(sig, frame):
        print("\n\n  Saving session...")
        session.generate_summary()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    try:
        if args.text:
            run_text_mode(session)
        else:
            try:
                sd.query_devices(kind='input')
                run_voice_mode(session)
            except Exception as e:
                print(f"\n  Audio error: {e}")
                print("  Falling back to text mode...\n")
                run_text_mode(session)

        session.generate_summary()

    except Exception as e:
        print(f"\n  Unexpected error: {e}")
        try:
            session._save_transcript()
            print(f"  Transcript saved: {session.session_file}")
        except:
            pass

    print("\n  Session complete. Action over analysis.\n")


if __name__ == "__main__":
    main()
