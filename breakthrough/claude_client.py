"""
AI client for the Breakthrough Programme web interface.
Backend priority: Ollama (local) → Groq → Gemini
"""

import os
import requests
from groq import Groq
from groq import AuthenticationError, RateLimitError

MAX_CONTEXT_EXCHANGES = 15
GROQ_MODEL = "llama-3.1-8b-instant"
OLLAMA_HOST = "http://localhost:11434"


def _clean_text(text):
    """Strip markdown formatting from AI response."""
    text = text.replace("**", "").replace("*", "")
    text = text.replace("##", "").replace("#", "")
    text = text.replace("- ", "").replace("• ", "")
    return text.strip()


def _ollama_chat(system_prompt, messages, user_message, max_tokens=1024):
    """
    Call local Ollama instance.
    Returns (response_text, error_message).
    """
    model = os.environ.get("OLLAMA_MODEL")
    if not model:
        return None, "OLLAMA_MODEL not set."

    payload = {
        "model": model,
        "stream": False,
        "options": {"num_predict": max_tokens},
        "messages": [{"role": "system", "content": system_prompt}]
        + [{"role": m["role"], "content": m["content"]} for m in messages]
        + [{"role": "user", "content": user_message}],
    }

    try:
        r = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        text = r.json()["message"]["content"]
        return _clean_text(text), None
    except requests.exceptions.ConnectionError:
        return None, "Ollama not running. Start it with: ollama serve"
    except Exception as e:
        return None, f"Ollama error: {str(e)}"


def _groq_chat(system_prompt, messages, user_message, max_tokens=1024):
    """
    Call Groq API.
    Returns (response_text, error_message).
    """
    api_key = os.environ.get("Groq_SB")
    if not api_key:
        return None, "Groq_SB not set."

    try:
        client = Groq(api_key=api_key)
        msgs = [{"role": "system", "content": system_prompt}]
        for m in messages:
            msgs.append({"role": m["role"], "content": m["content"]})
        msgs.append({"role": "user", "content": user_message})

        response = client.chat.completions.create(
            model=GROQ_MODEL, max_tokens=max_tokens, messages=msgs
        )
        return _clean_text(response.choices[0].message.content), None

    except (AuthenticationError, RateLimitError):
        return None, "Groq rate limit or auth error."
    except Exception as e:
        return None, f"Groq error: {str(e)}"


def _gemini_chat(system_prompt, messages, user_message, max_tokens=1024):
    """
    Call Google Gemini as final fallback.
    Returns (response_text, error_message).
    """
    api_key = os.environ.get("Gemini_API_SB")
    if not api_key:
        return None, "Gemini_API_SB not set."

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt, max_output_tokens=max_tokens
            ),
        )
        if response.text is None:
            return None, "Gemini returned empty response (possibly blocked by safety filters)."
        return _clean_text(response.text), None

    except Exception as e:
        return None, f"Gemini error: {str(e)}"


def get_claude_response(system_prompt, conversation, user_message):
    """
    Send message using Ollama → Groq → Gemini fallback chain.
    Returns (response_text, error_message).
    """
    recent = conversation[-(MAX_CONTEXT_EXCHANGES * 2):]

    # 1. Ollama (local Mac only — when OLLAMA_MODEL is set)
    if os.environ.get("OLLAMA_MODEL"):
        text, err = _ollama_chat(system_prompt, recent, user_message)
        if text:
            return text, None

    # 2. Groq
    text, err = _groq_chat(system_prompt, recent, user_message)
    if text:
        return text, None

    # 3. Gemini
    return _gemini_chat(system_prompt, recent, user_message)


def generate_summary(client_name, session_type, conversation, system_prompt):
    """
    Generate session summary using Ollama → Groq → Gemini fallback chain.
    Returns (summary_text, error_message).
    """
    from .session_core import SESSION_TYPES

    transcript = "\n".join(
        f"{'Client' if m['role'] == 'user' else 'Therapist'}: {m['content']}"
        for m in conversation
    )
    type_desc = SESSION_TYPES.get(session_type, "Unknown") if session_type else "Unknown"

    summary_prompt = f"""You just completed a Breakthrough Programme therapy session.
Session type: {session_type} — {type_desc}

Here is the full transcript:
{transcript}

Generate a concise session summary with these sections:
1. SESSION SUMMARY (2-3 sentences — what happened, what emerged)
2. SESSION TYPE USED: {session_type}
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

    # 1. Ollama
    if os.environ.get("OLLAMA_MODEL"):
        text, err = _ollama_chat("", [], summary_prompt, max_tokens=2048)
        if text:
            return text, None

    # 2. Groq
    api_key = os.environ.get("Groq_SB")
    if api_key:
        try:
            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": summary_prompt}],
            )
            return response.choices[0].message.content.strip(), None
        except Exception:
            pass

    # 3. Gemini
    try:
        from google import genai
        from google.genai import types
        gemini_key = os.environ.get("Gemini_API_SB")
        if not gemini_key:
            return None, "All AI backends unavailable."
        client = genai.Client(api_key=gemini_key)
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=summary_prompt,
            config=types.GenerateContentConfig(max_output_tokens=2048),
        )
        if response.text is None:
            return None, "Gemini returned empty response (possibly blocked by safety filters)."
        return response.text.strip(), None
    except Exception as e:
        return None, f"Summary failed: {str(e)}"
