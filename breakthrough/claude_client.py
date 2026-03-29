"""
Claude API client for the Breakthrough Programme web interface.
Uses the Anthropic Python SDK instead of the claude CLI.
"""

import os
import anthropic

MAX_CONTEXT_EXCHANGES = 15


def get_claude_response(system_prompt, conversation, user_message):
    """
    Send message to Claude via Anthropic API.
    Returns (response_text, error_message).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "ANTHROPIC_API_KEY is not set. Please add it in the Secrets tab."

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Build messages list from conversation history
        messages = []
        recent = conversation[-(MAX_CONTEXT_EXCHANGES * 2):]
        for msg in recent:
            messages.append({"role": msg["role"], "content": msg["content"]})

        # Add current user message
        messages.append({"role": "user", "content": user_message})

        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )

        text = response.content[0].text.strip()

        # Clean any markdown formatting
        text = text.replace("**", "").replace("*", "")
        text = text.replace("##", "").replace("#", "")
        text = text.replace("- ", "").replace("• ", "")

        return text, None

    except anthropic.AuthenticationError:
        return None, "Invalid ANTHROPIC_API_KEY. Please check your API key in the Secrets tab."
    except anthropic.RateLimitError:
        return None, "Rate limit reached. Please wait a moment and try again."
    except Exception as e:
        return None, f"API error: {str(e)}"


def generate_summary(client_name, session_type, conversation, system_prompt):
    """
    Generate a session summary using Claude.
    Returns (summary_text, error_message).
    """
    from .session_core import SESSION_TYPES

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "ANTHROPIC_API_KEY is not set."

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

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2048,
            messages=[{"role": "user", "content": summary_prompt}],
        )
        summary = response.content[0].text.strip()
        return summary, None
    except Exception as e:
        return None, str(e)
