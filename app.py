#!/usr/bin/env python3
"""
Breakthrough Programme — Web Interface
A browser-based text interface for the AI-driven therapeutic sessions.
"""

import os
import sys
import uuid
import json
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime
from functools import wraps
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

# Server-side session store — avoids cookie size limit
_sessions = {}

USERS_FILE = Path(__file__).parent / "users.json"


# ── AUTH HELPERS ─────────────────────────────────────────────────────────────

def load_users():
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text())
    return {}


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            return jsonify({"error": "Not authenticated"}), 401
        return f(*args, **kwargs)
    return decorated


# ── AUTH ROUTES ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    users = load_users()
    user = users.get(username)

    if not user or user["password"] != hash_password(password):
        return jsonify({"error": "Invalid username or password"}), 401

    session["username"] = username
    session["display_name"] = user.get("display_name", username.title())

    return jsonify({
        "status": "ok",
        "username": username,
        "display_name": user.get("display_name", username.title()),
    })


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    # Clean up any active session
    sid = session.get("sid")
    if sid and sid in _sessions:
        _sessions.pop(sid, None)
    session.clear()
    return jsonify({"status": "ok"})


@app.route("/api/auth/me", methods=["GET"])
def me():
    username = session.get("username")
    if not username:
        return jsonify({"authenticated": False}), 401
    return jsonify({
        "authenticated": True,
        "username": username,
        "display_name": session.get("display_name", username.title()),
    })


# ── SESSION ROUTES ───────────────────────────────────────────────────────────

@app.route("/api/session/start", methods=["POST"])
@login_required
def start_session():
    username = session["username"]
    data = request.json
    session_type = data.get("session_type") or None
    mode = data.get("mode", "session")

    client_dir = SESSIONS_DIR / username
    client_dir.mkdir(parents=True, exist_ok=True)

    if session_type not in SESSION_TYPES and mode == "session":
        session_type = select_session_type(username)

    system_prompt = build_system_prompt(username, session_type, mode)

    sid = str(uuid.uuid4())
    _sessions[sid] = {
        "client_name": username,
        "session_type": session_type,
        "mode": mode,
        "system_prompt": system_prompt,
        "conversation": [],
        "session_file": None,
    }
    session["sid"] = sid

    session_type_desc = SESSION_TYPES.get(session_type, "") if session_type else ""

    return jsonify({
        "status": "started",
        "client_name": username,
        "session_type": session_type,
        "session_type_desc": session_type_desc,
        "mode": mode,
    })


@app.route("/api/session/message", methods=["POST"])
@login_required
def send_message():
    sid = session.get("sid")
    if not sid or sid not in _sessions:
        return jsonify({"error": "No active session. Please start a session first."}), 400

    data = request.json
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Message is required"}), 400

    sess_data = _sessions[sid]
    response, error = get_claude_response(
        sess_data["system_prompt"], sess_data["conversation"], user_message
    )

    if error:
        return jsonify({"error": error}), 500

    sess_data["conversation"].append({"role": "user", "content": user_message})
    sess_data["conversation"].append({"role": "assistant", "content": response})

    _save_transcript(sess_data)

    return jsonify({"response": response})


@app.route("/api/session/end", methods=["POST"])
@login_required
def end_session():
    sid = session.get("sid")
    if not sid or sid not in _sessions:
        return jsonify({"error": "No active session"}), 400

    try:
        sess_data = _sessions[sid]
        conversation = sess_data["conversation"]

        if not conversation:
            _sessions.pop(sid)
            session.pop("sid", None)
            return jsonify({"status": "ended", "summary": ""})

        client_name = sess_data["client_name"]
        session_type = sess_data.get("session_type")
        mode = sess_data.get("mode", "session")

        summary = ""
        if mode == "session" and conversation:
            summary, error = generate_summary(
                client_name, session_type, conversation, sess_data["system_prompt"]
            )
            if error:
                summary = f"(Summary generation failed: {error})"
            else:
                _finalize_session(sess_data, summary)
                _git_push_sessions()

        _sessions.pop(sid)
        session.pop("sid", None)
        return jsonify({"status": "ended", "summary": summary})

    except Exception as e:
        _sessions.pop(sid, None)
        session.pop("sid", None)
        return jsonify({"error": f"Failed to end session: {str(e)}"}), 500


@app.route("/api/sessions/mine", methods=["GET"])
@login_required
def list_my_sessions():
    username = session["username"]
    client_dir = SESSIONS_DIR / username
    if not client_dir.exists():
        return jsonify({"sessions": []})

    files = []
    for f in sorted(client_dir.glob("*.md"), reverse=True):
        files.append({"name": f.name, "size": f.stat().st_size})
    return jsonify({"sessions": files})


@app.route("/api/sessions/mine/<filename>", methods=["GET"])
@login_required
def get_my_session(filename):
    username = session["username"]
    file_path = SESSIONS_DIR / username / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404
    return jsonify({"content": file_path.read_text()})


@app.route("/api/session/types", methods=["GET"])
def get_session_types():
    return jsonify({"types": SESSION_TYPES})


# ── FILE HELPERS ─────────────────────────────────────────────────────────────

def _save_transcript(sess_data):
    client_name = sess_data.get("client_name")
    session_type = sess_data.get("session_type")
    mode = sess_data.get("mode", "session")
    conversation = sess_data.get("conversation", [])

    if not client_name or not conversation:
        return

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
            checkin_path.write_text(f"# Check-ins — {client_name.title()}\n\nBrief daily check-ins.\n" + entry)
        return

    if not sess_data.get("session_file"):
        existing_files = sorted(client_dir.glob(f"{now.strftime('%Y-%m-%d')}_session_*.md"))
        session_number = len(existing_files) + 1
        sess_data["session_file"] = str(
            client_dir / f"{now.strftime('%Y-%m-%d')}_session_{session_number:02d}.md"
        )

    session_file = Path(sess_data["session_file"])
    if not session_file.parent.exists():
        return

    session_number = int(session_file.stem.split("_")[-1])
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


def _finalize_session(sess_data, summary):
    session_file = Path(sess_data.get("session_file", ""))
    if not session_file.exists():
        return
    content = session_file.read_text()
    content = content.replace("**Status:** In progress", "**Status:** Complete")
    content += f"\n\n## Session Summary\n\n{summary}\n"
    session_file.write_text(content)


def _git_push_sessions():
    repo_dir = Path(__file__).parent
    try:
        subprocess.run(["git", "add", "breakthrough/sessions/"], cwd=repo_dir, capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", f"Session: {datetime.now().strftime('%Y-%m-%d %H:%M')}"], cwd=repo_dir, capture_output=True, timeout=10)
        subprocess.run(["git", "push"], cwd=repo_dir, capture_output=True, timeout=30)
    except Exception:
        pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
