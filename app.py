#!/usr/bin/env python3
"""
Breakthrough Programme — Web Interface
A browser-based text interface for the AI-driven therapeutic sessions.
"""

import os
import sys
from pathlib import Path
from flask import Flask, render_template, request, jsonify, session

sys.path.insert(0, str(Path(__file__).parent / "breakthrough"))
from session_core import (
    build_system_prompt,
    SESSION_TYPES,
    select_session_type,
    SESSIONS_DIR,
)
from claude_client import get_claude_response, generate_summary

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "breakthrough-dev-secret")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/clients", methods=["GET"])
def list_clients():
    clients = []
    if SESSIONS_DIR.exists():
        for d in SESSIONS_DIR.iterdir():
            if d.is_dir():
                clients.append(d.name)
    return jsonify({"clients": sorted(clients)})


@app.route("/api/session/start", methods=["POST"])
def start_session():
    data = request.json
    client_name = data.get("client_name", "").strip()
    session_type = data.get("session_type") or None
    mode = data.get("mode", "session")

    if not client_name:
        return jsonify({"error": "Client name is required"}), 400

    # Initialize the client directory
    client_dir = SESSIONS_DIR / client_name
    client_dir.mkdir(parents=True, exist_ok=True)

    # Determine session type
    if session_type not in SESSION_TYPES and mode == "session":
        session_type = select_session_type(client_name)

    # Build system prompt
    system_prompt = build_system_prompt(client_name, session_type, mode)

    # Store in Flask session
    session["client_name"] = client_name
    session["session_type"] = session_type
    session["mode"] = mode
    session["system_prompt"] = system_prompt
    session["conversation"] = []

    session_type_desc = SESSION_TYPES.get(session_type, "") if session_type else ""

    return jsonify({
        "status": "started",
        "client_name": client_name,
        "session_type": session_type,
        "session_type_desc": session_type_desc,
        "mode": mode,
    })


@app.route("/api/session/message", methods=["POST"])
def send_message():
    if "client_name" not in session:
        return jsonify({"error": "No active session. Please start a session first."}), 400

    data = request.json
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Message is required"}), 400

    system_prompt = session.get("system_prompt", "")
    conversation = session.get("conversation", [])

    # Get Claude response
    response, error = get_claude_response(system_prompt, conversation, user_message)

    if error:
        return jsonify({"error": error}), 500

    # Update conversation
    conversation.append({"role": "user", "content": user_message})
    conversation.append({"role": "assistant", "content": response})
    session["conversation"] = conversation

    # Auto-save transcript
    _save_transcript(session)

    return jsonify({"response": response})


@app.route("/api/session/end", methods=["POST"])
def end_session():
    if "client_name" not in session:
        return jsonify({"error": "No active session"}), 400

    conversation = session.get("conversation", [])
    if not conversation:
        session.clear()
        return jsonify({"status": "ended", "summary": ""})

    client_name = session["client_name"]
    session_type = session.get("session_type")
    mode = session.get("mode", "session")

    summary = ""
    if mode == "session" and conversation:
        system_prompt = session.get("system_prompt", "")
        summary, error = generate_summary(
            client_name, session_type, conversation, system_prompt
        )
        if error:
            summary = f"(Summary generation failed: {error})"
        else:
            _finalize_session(session, summary)

    session.clear()
    return jsonify({"status": "ended", "summary": summary})


@app.route("/api/sessions/<client_name>", methods=["GET"])
def list_sessions(client_name):
    client_dir = SESSIONS_DIR / client_name
    if not client_dir.exists():
        return jsonify({"sessions": []})

    files = []
    for f in sorted(client_dir.glob("*.md"), reverse=True):
        files.append({
            "name": f.name,
            "size": f.stat().st_size,
        })
    return jsonify({"sessions": files})


@app.route("/api/sessions/<client_name>/<filename>", methods=["GET"])
def get_session(client_name, filename):
    file_path = SESSIONS_DIR / client_name / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404
    content = file_path.read_text()
    return jsonify({"content": content})


@app.route("/api/session/types", methods=["GET"])
def get_session_types():
    return jsonify({"types": SESSION_TYPES})


def _save_transcript(sess):
    """Save current session transcript to file."""
    client_name = sess.get("client_name")
    session_type = sess.get("session_type")
    mode = sess.get("mode", "session")
    conversation = sess.get("conversation", [])

    if not client_name or not conversation:
        return

    from datetime import datetime
    client_dir = SESSIONS_DIR / client_name
    client_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()

    if mode == "checkin":
        checkin_path = client_dir / "checkins.md"
        entry = f"\n---\n\n## Check-in — {now.strftime('%Y-%m-%d %H:%M')}\n\n"
        for msg in conversation:
            label = "You" if msg["role"] == "user" else "Claude"
            entry += f"**{label}:** {msg['content']}\n\n"
        if checkin_path.exists():
            checkin_path.write_text(checkin_path.read_text() + entry)
        else:
            header = f"# Check-ins — {client_name.title()}\n\nBrief daily check-ins.\n"
            checkin_path.write_text(header + entry)
        return

    # Full session
    existing_files = sorted(client_dir.glob(f"{now.strftime('%Y-%m-%d')}_session_*.md"))
    session_number = len(existing_files) + 1

    # Store session file path in session
    if "session_file" not in sess:
        sess["session_file"] = str(
            client_dir / f"{now.strftime('%Y-%m-%d')}_session_{session_number:02d}.md"
        )

    session_file = Path(sess.get("session_file", ""))
    if not session_file.parent.exists():
        return

    type_desc = SESSION_TYPES.get(session_type, "") if session_type else "Check-in"
    content = f"""# Breakthrough Session — {client_name.title()}
**Date:** {now.strftime('%Y-%m-%d %H:%M')}
**Session:** {session_number}
**Session Type:** {session_type or 'N/A'} — {type_desc}
**Status:** In progress

---

## Transcript

"""
    elapsed = 0
    for i in range(0, len(conversation), 2):
        user_msg = conversation[i]["content"] if i < len(conversation) else ""
        claude_msg = conversation[i + 1]["content"] if i + 1 < len(conversation) else ""
        content += f"**[{elapsed:02d}:00] You:**\n{user_msg}\n\n"
        content += f"**Claude:**\n{claude_msg}\n\n---\n\n"
        elapsed += 2

    session_file.write_text(content)


def _finalize_session(sess, summary):
    """Append summary to session file and update logs."""
    session_file = Path(sess.get("session_file", ""))
    if not session_file.exists():
        return

    content = session_file.read_text()
    content = content.replace("**Status:** In progress", "**Status:** Complete")
    content += f"\n\n## Session Summary\n\n{summary}\n"
    session_file.write_text(content)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
