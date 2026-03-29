# CLAUDE.md — Breakthrough Programme Project

## META RULE 0 (highest priority — all Claude instances must follow)
**Never make any changes to files or code without explicit user approval.**
- Discussion = discussion only. Do not treat a question or idea as a request to edit.
- Always propose a plan first, then wait for the user to say "go ahead" or equivalent.
- Reading files and researching the codebase is fine without permission.
- Only write/edit files after the user explicitly approves the proposed change.

---

## What This Project Is
An AI-powered ISTDP (Intensive Short-Term Dynamic Psychotherapy) therapy session app.
- Built for deep psychological transformation work
- Uses voice (STT + TTS) for natural spoken sessions
- Follows the Breakthrough Programme — a structured ISTDP protocol
- Currently works as a terminal app on Mac using `claude -p` CLI
- Being expanded into a webapp/desktop app for friends/family to use free

---

## Current State (Terminal App — Working)
- **Main script:** `breakthrough/breakthrough_session.py`
- Uses `claude -p` subprocess for AI responses (Claude Sonnet 4.6)
- Whisper (faster-whisper) for STT
- Edge TTS for speech output
- Sessions saved as markdown files under `breakthrough/sessions/{client_name}/`
- Already multi-user by design — `client_name` parameter used throughout
- Only hardcoded user reference: `default="sapandeep"` at line 1098 (CLI default only)
- 5 session types: A (ISTDP Pressure), B (Core Transform), C (Inner Child), D (Micro-action), E (Somatic)

---

## Key File Paths
- **Session engine:** `breakthrough/breakthrough_session.py`
- **Breakthrough Programme:** `The_Breakthrough_Programme.md` (~41KB)
- **ISTDP Knowledge Base:** `resources/ISTDP_Knowledge_Base.md` (~55KB, 30 sections)
- **Resource index:** `ISTDP_Resources.md`
- **Session files:** `breakthrough/sessions/{client_name}/`
- **Architecture doc:** `ARCHITECTURE.md`

---

## Webapp — Architecture Decided, Not Built Yet
See `ARCHITECTURE.md` for full details. Summary:

### Stack
- **Backend:** Python FastAPI on Replit (API only, no session storage)
- **Frontend + Desktop shell:** Electron app (installed locally by users)
- **AI Primary:** Groq (Llama 3.3 70B) — owner's API key, free tier
- **AI Fallback:** Gemini 2.0 Flash — owner's API key, free tier
- **Owner's personal use:** keeps `claude -p` (Claude Sonnet, best quality)
- **Voice:** Browser Web Speech API (STT) + speechSynthesis (TTS)

### Key Decisions
- Sessions stored on **user's local machine** (full privacy, no server storage)
- User chooses a folder once on first launch — fully automatic after that
- Simple username/password login (local, just for session labelling)
- Friends/family need zero technical knowledge — install app, open, use
- Total cost: **$0 for everyone**

---

## Model Selection
| Backend | Model | Use case |
|---|---|---|
| `claude` | Claude Sonnet 4.6 via `claude -p` | Owner's personal sessions (best quality) |
| `groq` | Llama 3.3 70B | Primary free backend for others |
| `gemini` | Gemini 2.0 Flash | Fallback if Groq limits hit |
| `ollama` | DeepSeek R1 14B | Local offline option (M-series Mac) |

---

## Dynamic Prompt Loading (design decision, not built yet)
Load only relevant KB sections per session type instead of full 100KB:
- Check-in: Programme summary + recent 1-2 sessions only
- Type A: Programme + KB sections 1-4, 10, 24-25
- Type B: Programme + KB sections 5, 29
- Type C: Programme + KB sections 19, 25, 29
- Type D: Programme summary + recent sessions + micro-actions
- Type E: KB sections 2, 11, 25, 27 only
- Weekly review: All summaries + progress log only

---

## ISTDP Knowledge Base — 30 Sections
1–4: Triangle of Conflict; Anxiety Pathways; Defence Taxonomy; Pressure Ladder
5: Central Dynamic Sequence (8-phase Davanloo)
6: Ego-Superego Separation
7: Intervention Language Library
8: Psychodiagnostic Decision Tree
9: Self-Supervision Checklist
10: Rage-Guilt-Grief Sequence Enhanced
11: Bracing / Feeling-Access Calibration Thresholds
12: Clinical Processes Summary
13–14: Class slides: Triangles, Anxiety Thresholds, Graded Format
15–16: Repression cases
17–18: Anxiety pathways + psychodiagnostic specifics
19: Dissociative / Fragile Patient Markers
20: Transference Resistance Types
21: Five Monitoring Factors
22: Evidence Base (effect sizes, meta-analyses)
23: Cost-Effectiveness Data
24: Psychodiagnosis Algorithm Complete (6 response patterns)
25: Somatic Pathways of Each Feeling
26: Functional Somatic Disorders Protocol
27: Bracing Technique
28: Portraying Technique + Guilt
29: Full Treatment Phase Arc
30: UTA Spectrum

---

## Next Steps (not started)
1. Add `.gitignore` (exclude `__pycache__`, `.pyc`, session data, PDFs)
2. Build Replit FastAPI backend with Groq + Gemini backends
3. Build Electron desktop app with HTML/JS UI
4. Implement dynamic prompt loading per session type
5. Test with friends/family
