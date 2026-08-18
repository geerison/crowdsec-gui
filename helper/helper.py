"""
CrowdSec GUI Helper Service
Runs on the HOST (not in Docker). Listens on 127.0.0.1:9099.
Only the UI container (via host-gateway) should reach this.
"""

import os
import hmac
import ipaddress
import json
import subprocess
import datetime
from collections import deque
from flask import Flask, request, jsonify, abort

app = Flask(__name__)

HELPER_SECRET = os.environ.get("HELPER_SECRET", "")
AUDIT_LOG = os.environ.get("AUDIT_LOG", "/opt/crowdsec-gui/helper/crowdsec-audit.log")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIT_LINE_LIMIT = 200
COMMAND_ERROR_LIMIT = 500
BAN_DURATIONS = frozenset({"15m", "4h", "24h", "168h"})
PERMANENT_BAN_DURATION = "876000h"


def normalize_ip(value):
    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    try:
        if "/" in value:
            return str(ipaddress.ip_network(value, strict=False))
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def check_secret():
    """Abort if the shared secret header is missing or wrong."""
    if not HELPER_SECRET:
        app.logger.error("HELPER_SECRET is not set — refusing authenticated endpoints.")
        abort(503)
    incoming = request.headers.get("X-Helper-Secret", "")
    if not hmac.compare_digest(incoming, HELPER_SECRET):
        abort(403)


def _audit_field(value):
    return str(value).replace("\r", "_").replace("\n", "_").replace(" ", "_")


def write_audit(action, target_ip, result, requester_ip=None):
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    line = (
        f"{ts} action={_audit_field(action)} ip={_audit_field(target_ip)} "
        f"result={_audit_field(result)} from={_audit_field(requester_ip or 'unknown')}\n"
    )
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
        with open(AUDIT_LOG, "a") as f:
            f.write(line)
    except Exception as e:
        app.logger.error(f"Audit log write failed: {e}")


def run_script(script_name):
    script = os.path.join(SCRIPTS_DIR, script_name)
    result = subprocess.run(["sudo", script], capture_output=True, text=True, timeout=15)
    return result.stdout, result.stderr, result.returncode


def run_ip_script(script_name, ip):
    """Pass newline-terminated validated input through stdin, never command-line args."""
    script = os.path.join(SCRIPTS_DIR, script_name)
    result = subprocess.run(
        ["sudo", script],
        input=f"{ip}\n",
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout, result.stderr, result.returncode


def run_ban_script(ip, duration):
    return run_ip_script("crowdsec-ban.sh", f"{ip}\n{duration}")


def command_error(stdout, stderr):
    error = (stderr or stdout).strip()
    if not error:
        return "CrowdSec command failed without an error message"
    return error[:COMMAND_ERROR_LIMIT]


def json_body():
    check_secret()

    if not request.is_json:
        abort(400)

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        abort(400)

    return body


def normalize_decisions(data):
    """Flatten decisions nested inside alerts by recent cscli JSON output."""
    normalized = []

    for item in data:
        if not isinstance(item, dict):
            continue

        nested_decisions = item.get("decisions")
        if not isinstance(nested_decisions, list):
            normalized.append(item)
            continue

        for decision in nested_decisions:
            if not isinstance(decision, dict):
                continue

            normalized.append(
                {
                    **decision,
                    "scenario": decision.get("scenario") or item.get("scenario", ""),
                }
            )

    return normalized


@app.route("/health")
def health():
    return jsonify({"ok": True}), 200


@app.route("/decisions")
def decisions():
    check_secret()
    stdout, stderr, rc = run_script("crowdsec-list-decisions.sh")  # noqa: no user data
    if rc != 0:
        return jsonify({"error": stderr.strip()}), 500
    try:
        data = json.loads(stdout)
        return jsonify(normalize_decisions(data) if data else [])
    except json.JSONDecodeError:
        return jsonify([])


@app.route("/alerts")
def alerts():
    check_secret()
    stdout, stderr, rc = run_script("crowdsec-list-alerts.sh")
    if rc != 0:
        return jsonify({"error": stderr.strip()}), 500
    try:
        data = json.loads(stdout)
        return jsonify(data if data else [])
    except json.JSONDecodeError:
        return jsonify([])


@app.route("/unban", methods=["POST"])
def unban():
    body = json_body()
    ip = normalize_ip(body.get("ip"))

    if not ip:
        write_audit("unban_rejected", body.get("ip", ""), "invalid_ip", request.remote_addr)
        return jsonify({"error": "Invalid IP"}), 400

    stdout, stderr, rc = run_ip_script("crowdsec-unban.sh", ip)
    if rc != 0:
        error = command_error(stdout, stderr)
        write_audit("unban", ip, "failed", request.remote_addr)
        app.logger.error("unban failed for %s: %s", ip, error)
        return jsonify({"error": error}), 500

    write_audit("unban", ip, "success", request.remote_addr)
    return jsonify({"ok": True, "ip": ip})


@app.route("/ban", methods=["POST"])
def ban():
    return create_ban("ban", None)


@app.route("/ban/permanent", methods=["POST"])
def permanent_ban():
    return create_ban("ban_permanent", PERMANENT_BAN_DURATION)


def create_ban(audit_action, fixed_duration):
    body = json_body()
    ip = normalize_ip(body.get("ip"))

    if not ip:
        write_audit(
            f"{audit_action}_rejected", body.get("ip", ""), "invalid_ip", request.remote_addr
        )
        return jsonify({"error": "Invalid IP"}), 400

    duration = fixed_duration or body.get("duration", "4h")
    if not isinstance(duration, str) or duration not in BAN_DURATIONS | {PERMANENT_BAN_DURATION}:
        write_audit(f"{audit_action}_rejected", ip, "invalid_duration", request.remote_addr)
        return jsonify({"error": "Invalid ban duration"}), 400

    if fixed_duration:
        stdout, stderr, rc = run_ip_script("crowdsec-permanent-ban.sh", ip)
    else:
        stdout, stderr, rc = run_ban_script(ip, duration)
    if rc != 0:
        error = command_error(stdout, stderr)
        write_audit(audit_action, ip, "failed", request.remote_addr)
        app.logger.error("%s failed for %s: %s", audit_action, ip, error)
        return jsonify({"error": error}), 500

    write_audit(audit_action, ip, "success", request.remote_addr)
    return jsonify({"ok": True, "ip": ip, "duration": duration})


@app.route("/audit")
def audit():
    check_secret()
    try:
        with open(AUDIT_LOG) as f:
            lines = deque(f, maxlen=AUDIT_LINE_LIMIT)
        return jsonify({"lines": list(reversed([line.rstrip() for line in lines]))})
    except FileNotFoundError:
        return jsonify({"lines": []})
    except Exception as e:
        app.logger.error(f"Audit log read failed: {e}")
        return jsonify({"error": "Failed to read audit log"}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=9099, debug=False)
