#!/usr/bin/env python3
"""
Breakthrough Session — Interactive Voice Therapy Sessions
Uses: Whisper (STT) + Claude Code CLI (AI) + Edge TTS (speech)
Runs on your Mac using your Claude Max subscription. Zero extra cost.
"""

import os
import sys
import time
import wave
import signal
import tempfile
import asyncio
import subprocess
import argparse
import json
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

# ---------------------------------------------------------------------------
# System Prompt Builder
# ---------------------------------------------------------------------------

def load_programme():
    """Load the Breakthrough Programme document."""
    if PROGRAMME_FILE.exists():
        return PROGRAMME_FILE.read_text()
    print(f"WARNING: Programme file not found at {PROGRAMME_FILE}")
    print("Sessions will run without the full programme context.")
    return ""

def load_client_profile(client_name):
    """Load existing client profile if it exists."""
    profile_path = SESSIONS_DIR / client_name / "profile.md"
    if profile_path.exists():
        return profile_path.read_text()
    return ""

def load_all_session_summaries(client_name):
    """Load summaries from ALL previous sessions (not just the most recent)."""
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return ""

    session_files = sorted(client_dir.glob("*_session_*.md"))
    summaries = []

    for f in session_files:
        content = f.read_text()
        if "## Session Summary" in content:
            idx = content.index("## Session Summary")
            # Extract the header line for context
            header = ""
            for line in content.split("\n")[:5]:
                if line.startswith("**Date:") or line.startswith("**Session:") or line.startswith("**Session Type:"):
                    header += line + "\n"
            summary_text = content[idx:]
            summaries.append(f"--- {f.name} ---\n{header}{summary_text}")

    if not summaries:
        return ""

    return "\n\n".join(summaries)

def load_micro_actions(client_name):
    """Load current micro-actions."""
    path = SESSIONS_DIR / client_name / "micro_actions.md"
    if path.exists():
        return path.read_text()
    return ""

def load_somatic_baseline(client_name):
    """Load somatic baseline data."""
    path = SESSIONS_DIR / client_name / "somatic_baseline.md"
    if path.exists():
        return path.read_text()
    return ""

def load_progress_log(client_name):
    """Load the progress log."""
    path = SESSIONS_DIR / client_name / "progress_log.md"
    if path.exists():
        return path.read_text()
    return ""

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
                session_type = line.split(":")[-1].strip().rstrip("*")
                types.append(session_type)
                break

    return types

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

def build_system_prompt(client_name, session_type=None, mode="session"):
    """Build the full system prompt from programme + client context."""
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
        # Full session mode
        if session_type and session_type in SESSION_TYPES:
            prompt += f"""=== SESSION TYPE: {session_type} ===
Today's session type: **{SESSION_TYPES[session_type]}**

{"Follow the ISTDP pressure escalation ladder from Section 3B. If rage emerges, follow the rage-guilt-grief sequence to completion. Do NOT redirect to compassion before rage is somatically processed." if session_type == "A" else ""}{"Guide the full Core Transformation process: identify the part, welcome it, follow positive intentions downward to core state, reverse and transform each layer, grow up the part." if session_type == "B" else ""}{"Direct contact with the Vulnerable Child. Age regression, resource installation, compassionate dialogue. Provide experientially what was never given." if session_type == "C" else ""}{"Focus on real-life experiences and micro-action debriefs. Link external events to body sensations. Bridge internal work to external evidence." if session_type == "D" else ""}{"No narrative. No interpretation. 30 minutes of precise somatic tracking only. Location, sensation, temperature, movement, impulse. Train the body awareness muscle." if session_type == "E" else ""}
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
# Claude Code Integration
# ---------------------------------------------------------------------------

def get_claude_response(system_prompt, conversation, user_message):
    """Send message to Claude via Claude Code CLI and get response."""
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

    except subprocess.TimeoutExpired:
        return "Let's pause here for a moment. Take a breath. What are you noticing right now?"
    except FileNotFoundError:
        print("\n  ERROR: 'claude' command not found.")
        print("  Make sure Claude Code is installed: npm install -g @anthropic-ai/claude-code")
        sys.exit(1)
    except Exception as e:
        print(f"  Error: {e}")
        return "Stay with what's present. What's happening in your body?"

# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, client_name, session_type=None, mode="session"):
        self.client_name = client_name
        self.client_dir = SESSIONS_DIR / client_name
        self.client_dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode

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
3. DEFENCES OBSERVED (which defence layers activated, count each type: Protector/Critic/Overcompensator)
4. SOMATIC DATA (any body sensations reported, shifts noticed)
5. FELT SHIFTS (did genuine felt change occur? Y/N + description)
6. RAGE-GUILT-GRIEF PROGRESS (which stages accessed: none/rage/guilt/grief/complete)
7. PRESSURE LADDER (highest level reached 1-4 if ISTDP was used, and the response)
8. SHAME ACCESSED (Y/N + context if yes)
9. MICRO-ACTIONS (assign 2-3 specific actions for the coming days — specific, calibrated, tied to core wound)
10. THREAD FOR NEXT SESSION (what to follow up on)
11. RECOMMENDED NEXT SESSION TYPE (A/B/C/D/E based on what emerged)

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

# ---------------------------------------------------------------------------
# Weekly Review Generation
# ---------------------------------------------------------------------------

def generate_weekly_review(client_name):
    """Generate a structured weekly review from the past week's sessions."""
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        print(f"  No sessions found for {client_name}")
        return

    # Collect all session files from the past 7 days
    cutoff = datetime.now() - timedelta(days=7)
    week_content = []

    # Session files
    for f in sorted(client_dir.glob("*_session_*.md")):
        try:
            date_str = f.name[:10]
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date >= cutoff:
                week_content.append(f"=== {f.name} ===\n{f.read_text()}")
        except (ValueError, IndexError):
            continue

    # Check-ins
    checkins_path = client_dir / "checkins.md"
    if checkins_path.exists():
        week_content.append(f"=== Check-ins ===\n{checkins_path.read_text()}")

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
        opening_msg
    )
    print(f"\n  \033[34mClaude:\033[0m {opening}\n")
    session.conversation.append(("assistant", opening))
    session._save_transcript()

    end_words = ("done", "end", "quit", "exit") if session.mode == "checkin" else ("end session", "end", "quit", "exit")

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
            session.system_prompt, session.conversation, user_input
        )
        print(f"\n  \033[34mClaude:\033[0m {response}\n")
        session.add_exchange(user_input, response)

def run_voice_mode(session):
    """Full voice mode — speak and listen."""

    # Load whisper up front
    get_whisper_model()

    # Opening — Claude initiates the session
    print("\n  Starting session...\n")
    opening = get_claude_response(
        session.system_prompt, [],
        f"The client just sat down for a live voice session. This is a Type {session.session_type} session: "
        f"{SESSION_TYPES.get(session.session_type, '')}. "
        f"This is session number {session.session_number}. "
        "Begin with the appropriate session opening from Section 5."
    )
    speak(opening)
    session.conversation.append(("assistant", opening))
    session._save_transcript()

    # Main loop
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
                    "I'd like to end the session now."
                )
                speak(closing)
                session.add_exchange(text, closing)
                break

            # Get Claude's response
            response = get_claude_response(
                session.system_prompt, session.conversation, text
            )
            speak(response)
            session.add_exchange(text, response)

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
        session = Session(args.client, mode="checkin")
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
    session = Session(args.client, session_type=args.session_type)
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
