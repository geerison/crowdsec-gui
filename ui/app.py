import os
import re
import json
import math
import datetime
import hmac
import secrets
import requests
from collections import Counter
from flask import Flask, render_template, request, redirect, url_for, flash, abort, session

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(24))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true",
)

HELPER_URL = os.environ.get("HELPER_URL", "http://127.0.0.1:9099")
HELPER_SECRET = os.environ.get("HELPER_SECRET", "")

_DEFAULT_SECRET_VALUES = {"", "change_me_to_a_random_secret", "change-me"}

VALID_IP_RE = re.compile(
    r"^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$"
    r"|^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(/\d{1,3})?$"
)


def _check_secret_config():
    """Warn at startup if HELPER_SECRET is missing or still set to a default value."""
    if HELPER_SECRET in _DEFAULT_SECRET_VALUES:
        app.logger.error(
            "HELPER_SECRET is not set or is still the default placeholder. "
            "All helper requests will be rejected (403). "
            "Set a strong random value in .env and restart the UI container."
        )


def helper_headers():
    return {"X-Helper-Secret": HELPER_SECRET}


def csrf_token():
    token = session.get("csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.context_processor
def csrf_context():
    return {"csrf_token": csrf_token}


def validate_csrf():
    submitted = request.form.get("csrf_token", "")
    if not hmac.compare_digest(submitted, session.get("csrf_token", "")):
        abort(400)


def helper_get(path):
    try:
        r = requests.get(f"{HELPER_URL}{path}", headers=helper_headers(), timeout=5)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.ConnectionError:
        return None, "Cannot reach helper service"
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        if status == 403:
            return None, (
                "Helper returned 403 Forbidden — HELPER_SECRET mismatch. "
                "Ensure the same HELPER_SECRET is set in both .env (for the UI) "
                "and /opt/crowdsec-gui/.env (for the helper service), then restart both."
            )
        if status == 503:
            return None, (
                "Helper returned 503 — HELPER_SECRET is not configured on the helper. "
                "Set HELPER_SECRET in /opt/crowdsec-gui/.env and restart crowdsec-gui-helper."
            )
        return None, f"Helper error {status}: {e}"
    except Exception as e:
        return None, str(e)


def helper_post(path, payload):
    try:
        r = requests.post(
            f"{HELPER_URL}{path}",
            json=payload,
            headers=helper_headers(),
            timeout=10,
        )
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.ConnectionError:
        return None, "Cannot reach helper service"
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        if status == 403:
            return None, (
                "Helper returned 403 Forbidden — HELPER_SECRET mismatch. "
                "Ensure the same HELPER_SECRET is set in both .env (for the UI) "
                "and /opt/crowdsec-gui/.env (for the helper service), then restart both."
            )
        if status == 503:
            return None, (
                "Helper returned 503 — HELPER_SECRET is not configured on the helper. "
                "Set HELPER_SECRET in /opt/crowdsec-gui/.env and restart crowdsec-gui-helper."
            )
        return None, f"Helper error {status}: {e.response.text if e.response else e}"
    except Exception as e:
        return None, str(e)


with app.app_context():
    _check_secret_config()


def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


def _paginate(data, page, per_page):
    """Return (page_slice, page, total_pages, total)."""
    total = len(data)
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    return data[offset:offset + per_page], page, total_pages, total


@app.route("/health")
def health():
    return {"ok": True}, 200


@app.route("/")
def dashboard():
    decisions, err_d = helper_get("/decisions")
    alerts, err_a = helper_get("/alerts")

    client_ip = get_client_ip()
    banned_ips = set()
    if decisions:
        for d in decisions:
            banned_ips.add(d.get("value", ""))

    total_bans = len(decisions) if decisions else 0
    recent_alerts = len(alerts) if alerts else 0
    is_banned = client_ip in banned_ips
    crowdsec_ok = err_d is None

    now_utc = datetime.datetime.utcnow()
    now_str = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    # Chart: alerts per hour over last 24h
    hour_labels = [
        (now_utc - datetime.timedelta(hours=23 - i)).strftime("%H:00")
        for i in range(24)
    ]
    hour_data = [0] * 24
    scenario_counter = Counter()

    if alerts:
        for a in alerts:
            scenario = a.get("scenario", "")
            if scenario:
                scenario_counter[scenario] += 1
            try:
                ts = a.get("created_at", "")
                if ts:
                    # Normalise: strip sub-seconds and timezone, keep date+time
                    ts_clean = ts.replace("Z", "").split("+")[0].split(".")[0]
                    dt = datetime.datetime.fromisoformat(ts_clean)
                    delta_h = int((now_utc - dt).total_seconds() / 3600)
                    if 0 <= delta_h < 24:
                        hour_data[23 - delta_h] += 1
            except Exception:
                pass

    top_scenarios = scenario_counter.most_common(10)

    return render_template(
        "dashboard.html",
        crowdsec_ok=crowdsec_ok,
        total_bans=total_bans,
        recent_alerts=recent_alerts,
        client_ip=client_ip,
        is_banned=is_banned,
        error=err_d or err_a,
        now=now_str,
        hour_labels=json.dumps(hour_labels),
        hour_data=json.dumps(hour_data),
        scenario_labels=json.dumps([s for s, _ in top_scenarios]),
        scenario_data=json.dumps([c for _, c in top_scenarios]),
        has_chart_data=bool(alerts),
    )


@app.route("/decisions")
def decisions():
    filter_ip = request.args.get("ip", "").strip()
    filter_scenario = request.args.get("scenario", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 25

    data, err = helper_get("/decisions")
    if data is None:
        data = []

    if filter_ip:
        data = [d for d in data if filter_ip in d.get("value", "")]
    if filter_scenario:
        data = [d for d in data if filter_scenario.lower() in d.get("scenario", "").lower()]

    paged, page, total_pages, total = _paginate(data, page, per_page)

    return render_template(
        "decisions.html",
        decisions=paged,
        error=err,
        filter_ip=filter_ip,
        filter_scenario=filter_scenario,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=per_page,
    )


@app.route("/unban", methods=["POST"])
def unban():
    validate_csrf()
    ip = request.form.get("ip", "").strip()
    if not ip or not VALID_IP_RE.match(ip):
        flash(f"Invalid IP address: {ip}", "error")
        return redirect(url_for("decisions"))

    result, err = helper_post("/unban", {"ip": ip})
    if err:
        flash(f"Unban failed: {err}", "error")
    else:
        flash(f"Unbanned {ip} successfully.", "success")

    return redirect(url_for("decisions"))


@app.route("/alerts")
def alerts():
    filter_ip = request.args.get("ip", "").strip()
    filter_scenario = request.args.get("scenario", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 50

    data, err = helper_get("/alerts")
    if data is None:
        data = []

    if filter_ip:
        data = [
            a for a in data
            if filter_ip in a.get("source", {}).get("ip", "")
        ]
    if filter_scenario:
        data = [
            a for a in data
            if filter_scenario.lower() in (a.get("scenario") or "").lower()
        ]

    paged, page, total_pages, total = _paginate(data, page, per_page)

    return render_template(
        "alerts.html",
        alerts=paged,
        error=err,
        filter_ip=filter_ip,
        filter_scenario=filter_scenario,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=per_page,
    )


@app.route("/audit")
def audit():
    page = request.args.get("page", 1, type=int)
    per_page = 50
    data, err = helper_get("/audit")
    lines = data.get("lines", []) if data else []
    paged, page, total_pages, total = _paginate(lines, page, per_page)
    return render_template(
        "audit.html",
        lines=paged,
        error=err,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=per_page,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8088, debug=False)
