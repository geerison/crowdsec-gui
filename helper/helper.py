"""
CrowdSec GUI Helper Service
Runs on the HOST (not in Docker). Listens on 127.0.0.1:9099.
Only the UI container (via host-gateway) should reach this.
"""

import os
import re
import json
import subprocess
import datetime
from flask import Flask, request, jsonify, abort

app = Flask(__name__)

HELPER_SECRET = os.environ.get("HELPER_SECRET", "")
HELPER_HOST = os.environ.get("HELPER_HOST", "127.0.0.1")
HELPER_PORT = int(os.environ.get("HELPER_PORT", "9099"))
AUDIT_LOG = os.environ.get("AUDIT_LOG", "/opt/crowdsec-gui/helper/crowdsec-audit.log")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

_DEFAULT_SECRET_VALUES = {"", "change_me_to_a_random_secret", "change-me"}


def _check_secret_config():
    """Warn at startup if HELPER_SECRET is missing or still set to a default value."""
    if HELPER_SECRET in _DEFAULT_SECRET_VALUES:
        app.logger.error(
            "HELPER_SECRET is not set or is still the default placeholder. "
            "All authenticated requests will be rejected (403). "
            "Set a strong random value in /opt/crowdsec-gui/.env and restart the service."
        )

VALID_IP_RE = re.compile(
    r"^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$"
    r"|^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(/\d{1,3})?$"
)


def check_secret():
    """Abort if the shared secret header is missing or wrong."""
    if HELPER_SECRET in _DEFAULT_SECRET_VALUES:
        app.logger.error(
            "HELPER_SECRET is not configured. "
            "Set a strong random value in /opt/crowdsec-gui/.env and restart the service."
        )
        abort(503)
    incoming = request.headers.get("X-Helper-Secret", "")
    if incoming != HELPER_SECRET:
        app.logger.warning(
            "Rejected request to %s — X-Helper-Secret header mismatch. "
            "Ensure HELPER_SECRET matches in both the UI container and the helper service.",
            request.path,
        )
        abort(403)


def write_audit(action, target_ip, result, requester_ip=None):
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    line = f"{ts} action={action} ip={target_ip} result={result} from={requester_ip or 'unknown'}\n"
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


def run_unban_script(ip):
    """Pass the validated IP via stdin to avoid putting user data on the command line."""
    script = os.path.join(SCRIPTS_DIR, "crowdsec-unban.sh")
    result = subprocess.run(
        ["sudo", script],
        input=ip,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout, result.stderr, result.returncode


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
        return jsonify(data if data else [])
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
    check_secret()

    if not request.is_json:
        abort(400)

    body = request.get_json(silent=True) or {}
    ip = body.get("ip", "").strip()

    if not ip or not VALID_IP_RE.match(ip):
        write_audit("unban_rejected", ip, "invalid_ip", request.remote_addr)
        return jsonify({"error": "Invalid IP"}), 400

    stdout, stderr, rc = run_unban_script(ip)
    if rc != 0:
        write_audit("unban", ip, f"failed: {stderr.strip()}", request.remote_addr)
        return jsonify({"error": stderr.strip()}), 500

    write_audit("unban", ip, "success", request.remote_addr)
    return jsonify({"ok": True, "ip": ip})


@app.route("/audit")
def audit():
    check_secret()
    try:
        with open(AUDIT_LOG) as f:
            lines = f.read().splitlines()
        return jsonify({"lines": list(reversed(lines))[-200:]})
    except FileNotFoundError:
        return jsonify({"lines": []})
    except Exception as e:
        app.logger.error(f"Audit log read failed: {e}")
        return jsonify({"error": "Failed to read audit log"}), 500


with app.app_context():
    _check_secret_config()


if __name__ == "__main__":
    app.run(host=HELPER_HOST, port=HELPER_PORT, debug=False)
