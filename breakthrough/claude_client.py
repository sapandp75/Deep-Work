"""
Groq API client for the Breakthrough Programme web interface.
Falls back to Gemini if Groq rate-limits or fails.
"""

import os
from groq import Groq
from groq import AuthenticationError, RateLimitError

MAX_CONTEXT_EXCHANGES = 15
MODEL = "llama-3.1-8b-instant"


def _clean_text(text):
    """Strip markdown formatting from AI response."""
    text = text.replace("**", "").replace("*", "")
    text = text.replace("##", "").replace("#", "")
    text = text.replace("- ", "").replace("• ", "")
    return text.strip()


def _gemini_chat(system_prompt, messages, user_message):
    """
    Call Google Gemini as fallback.
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
            model="gemini-2.0-flash",
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_prompt, max_output_tokens=1024),
        )
        return _clean_text(response.text), None

    except Exception as e:
        return None, f"Gemini error: {str(e)}"


def get_claude_response(system_prompt, conversation, user_message):
    """
    Send message to Groq API, falling back to Gemini on rate limit or auth error.
    Returns (response_text, error_message).
    """
    api_key = os.environ.get("Groq_SB")
    recent = conversation[-(MAX_CONTEXT_EXCHANGES * 2):]

    if api_key:
        try:
            client = Groq(api_key=api_key)
            messages = [{"role": "system", "content": system_prompt}]
            for msg in recent:
                messages.append({"role": msg["role"], "content": msg["content"]})
            messages.append({"role": "user", "content": user_message})

            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=1024,
                messages=messages,
            )
            return _clean_text(response.choices[0].message.content), None

        except (AuthenticationError, RateLimitError):
            # Fall through to Gemini
            pass
        except Exception as e:
            # Fall through to Gemini for any other Groq error
            pass

    # Gemini fallback
    return _gemini_chat(system_prompt, recent, user_message)


def generate_summary(client_name, session_type, conversation, system_prompt):
    """
    Generate a session summary. Tries Groq first, falls back to Gemini.
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

    api_key = os.environ.get("Groq_SB")
    if api_key:
        try:
            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": summary_prompt}],
            )
            return response.choices[0].message.content.strip(), None
        except (AuthenticationError, RateLimitError):
            pass
        except Exception:
            pass

    # Gemini fallback for summary
    try:
        from google import genai
        from google.genai import types
        gemini_key = os.environ.get("Gemini_API_SB")
        if not gemini_key:
            return None, "Both Groq and Gemini APIs unavailable."
        client = genai.Client(api_key=gemini_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=summary_prompt,
            config=types.GenerateContentConfig(max_output_tokens=2048),
        )
        return response.text.strip(), None
    except Exception as e:
        return None, f"Summary failed: {str(e)}"
