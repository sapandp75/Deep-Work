# Architecture — Breakthrough Programme Webapp

## Goal
Share the Breakthrough Programme ISTDP therapy app with friends/family (zero tech background) at zero cost.

---

## Overview

```
Electron Desktop App (installed on user's machine)
    ├── UI: HTML/JS chat + voice interface
    ├── Sessions: read/write to user-chosen local folder
    ├── Login: local credentials
    └── API calls ──→ Replit Backend ──→ Groq / Gemini
                                      ←── AI response
```

---

## Component 1: Replit Backend (API proxy)

**Purpose:** Receive conversation, call AI, return response. Nothing else.

- Framework: Python FastAPI
- Hosted: Replit (owner's existing membership, $0)
- Holds: Groq + Gemini API keys (environment variables, never in code)
- Receives: `{ system_prompt, messages, user_message }`
- Returns: `{ response }`
- Stores: **nothing** — stateless, no session data, no user data

**AI routing:**
- Primary: Groq (Llama 3.3 70B) — ~14,400 req/day free
- Fallback: Gemini 2.0 Flash — 1500 req/day free
- Auto-switches to fallback if Groq rate limit hit

---

## Component 2: Electron Desktop App

**Purpose:** Full featured local app with file system access.

- Built with: Electron (wraps HTML/JS UI)
- Distributed: GitHub releases (downloadable installer)
- Installation: double-click, like any Mac/Windows app
- No terminal, no Python, no technical knowledge needed

### Features
- Voice input via Web Speech API (STT)
- Voice output via speechSynthesis (TTS)
- Full file system access → automatic session management
- Simple login (local username/password)
- Calls Replit backend for AI responses

---

## Session Storage — Privacy First

**Sessions stored entirely on user's machine.**

### First Launch
1. App asks user to choose a sessions folder (one time only)
2. Folder path saved in app settings

### Every Session After
1. Login → app scans folder → loads all previous sessions automatically
2. Session runs with full context
3. Session ends → transcript auto-saved to folder
4. Next session picks up automatically — no manual action needed

### Privacy Guarantee
- Server sees: only the current conversation turn (required for AI call)
- Server stores: nothing
- Even app owner cannot access user session data
- User's data lives only on their machine

---

## Login / Auth

- Simple username + password
- Stored locally in Electron app (not on server)
- Purpose: label sessions by user (not security auth)
- No OAuth, no email, no verification
- Owner creates accounts manually for friends/family during testing phase

---

## Voice

| Component | Solution | Quality | Cost |
|---|---|---|---|
| STT | Browser Web Speech API | Good | $0 |
| TTS | Browser speechSynthesis | Good | $0 |

Can upgrade to server-side Whisper + Edge TTS later if quality needs improvement.

---

## AI Backends

| Backend | Model | Speed | Quality | Cost |
|---|---|---|---|---|
| Groq (primary) | Llama 3.3 70B | ~500 tok/sec | Very good | $0 (free tier) |
| Gemini (fallback) | Gemini 2.0 Flash | Fast | Very good | $0 (free tier) |
| Claude (owner only) | Sonnet 4.6 via `claude -p` | Fast | Best | $0 (Pro plan) |
| Ollama (optional) | DeepSeek R1 14B | Moderate | Good | $0 (local) |

---

## Dynamic Prompt Loading

Load only relevant KB sections per session type (not full 100KB every time):

| Session Type | Components Loaded | Approx Size |
|---|---|---|
| Check-in | Programme summary + recent 1-2 sessions | ~10KB |
| Type A (ISTDP Pressure) | Programme + KB §1-4, 10, 24-25 | ~20KB |
| Type B (Core Transform) | Programme + KB §5, 29 | ~15KB |
| Type C (Inner Child) | Programme + KB §19, 25, 29 | ~15KB |
| Type D (Micro-action) | Programme summary + recent sessions + micro-actions | ~12KB |
| Type E (Somatic only) | KB §2, 11, 25, 27 only | ~8KB |
| Weekly review | All summaries + progress log only | ~10KB |

**Benefit:** ~15-25KB per session vs 100KB full load → faster inference on all backends.

---

## Cost Breakdown

| Layer | Solution | Cost |
|---|---|---|
| Hosting | Replit (existing membership) | $0 |
| AI primary | Groq free tier (owner's key) | $0 |
| AI fallback | Gemini free tier (owner's key) | $0 |
| STT | Browser Web Speech API | $0 |
| TTS | Browser speechSynthesis | $0 |
| Session storage | User's local machine | $0 |
| Distribution | GitHub releases | $0 |
| **Total** | | **$0** |

---

## Distribution

1. Owner pushes code to GitHub
2. GitHub Actions builds Electron installer (Mac + Windows)
3. Friends/family get a download link
4. They install like any app — double click, done

---

## Multi-User Design

The existing terminal app is already multi-user:
- All functions use `client_name` parameter
- Sessions stored under `sessions/{client_name}/`
- Login username maps directly to `client_name`
- Each user has completely separate session history, micro-actions, progress log

---

## Build Order (when ready to start)

1. `.gitignore` — exclude `__pycache__`, `.pyc`, PDFs, session data
2. Replit FastAPI backend — `/chat` endpoint with Groq + Gemini routing
3. HTML/JS frontend — chat UI + voice
4. Electron shell — wrap frontend, add file system access
5. Dynamic prompt loading — per session type
6. GitHub Actions — build + release Electron installers
7. Test with friends/family

---

## Status
Architecture decided. No code written yet.
