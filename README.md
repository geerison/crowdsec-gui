# CrowdSec GUI v1

A self-hosted admin GUI for [CrowdSec](https://crowdsec.net/) — view alerts and decisions, manage safe manual bans, rank offending IPs, and audit GUI actions.

## Architecture

```
Browser
  → https://crowdsec.example.com
  → Caddy (on host, TLS termination + basic auth)
  → crowdsec-ui container (127.0.0.1:8088)
  → Host helper service (127.0.0.1:9099)
  → docker exec crowdsec cscli ...
```

### Why not mount `/var/run/docker.sock` into the GUI container?

Mounting the Docker socket into any container gives that container **root-equivalent control over the entire host**. If the GUI were compromised (e.g., via a vulnerability in Flask, a dependency, or a template injection), an attacker would have full control of your server.

Instead, this project uses a **host-side helper service** that:
- runs as an unprivileged dedicated user (`crowdsec-gui`)
- listens only on `127.0.0.1`
- is allowed to run only five specific scripts via `sudo` (list decisions, list alerts, 4-hour ban, 100-year ban, unban IP)
- requires a shared secret header from the UI container
- logs every GUI-initiated ban and unban action

The GUI container has **no Docker access at all**.

---

## Project Structure

```
/docker/crowdsec-gui/
├── docker-compose.yml       ← UI container
├── .env.example             ← copy to .env and fill in
├── README.md
├── ui/
│   ├── Dockerfile
│   ├── app.py               ← Flask UI app
│   ├── requirements.txt
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── decisions.html
│   │   ├── alerts.html
│   │   ├── audit.html
│   │   └── offending_ips.html
│   └── static/
│       └── style.css
├── helper/
│   ├── helper.py                    ← Flask helper API (runs on HOST)
│   ├── requirements.txt
│   ├── crowdsec-list-decisions.sh   ← calls docker exec crowdsec cscli decisions list
│   ├── crowdsec-list-alerts.sh      ← calls docker exec crowdsec cscli alerts list
│   ├── crowdsec-ban.sh              ← adds a preset-duration manual IP ban
│   ├── crowdsec-permanent-ban.sh    ← adds a reversible 100-year IP ban
│   ├── crowdsec-unban.sh            ← calls docker exec crowdsec cscli decisions delete
│   ├── crowdsec-ip-validation.sh    ← canonicalizes IP/CIDR input
│   ├── crowdsec-gui-helper.service  ← systemd unit
│   └── sudoers.crowdsec-gui         ← sudoers snippet
└── caddy/
    └── crowdsec.example.com.Caddyfile
```

---

## Installation

### 1. Download and extract

```bash
# Download ZIP from GitHub and extract to /docker/crowdsec-gui
sudo mkdir -p /docker
# Upload/extract the ZIP here, then:
cd /docker/crowdsec-gui
```

### 2. Create `.env`

```bash
cp .env.example .env
HELPER_SECRET_VALUE="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
FLASK_SECRET_VALUE="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
sed -i "s/^HELPER_SECRET=.*/HELPER_SECRET=$HELPER_SECRET_VALUE/" .env
sed -i "s/^FLASK_SECRET=.*/FLASK_SECRET=$FLASK_SECRET_VALUE/" .env
unset HELPER_SECRET_VALUE FLASK_SECRET_VALUE
chmod 600 .env
```

### 3. Set up the host helper

#### a. Create a dedicated user

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin crowdsec-gui
```

#### b. Install helper files to `/opt/crowdsec-gui`

```bash
sudo install -d -o crowdsec-gui -g crowdsec-gui /opt/crowdsec-gui/helper
sudo install -o crowdsec-gui -g crowdsec-gui -m 644 \
  /docker/crowdsec-gui/helper/helper.py \
  /opt/crowdsec-gui/helper/helper.py
sudo install -o root -g root -m 644 \
  /docker/crowdsec-gui/helper/requirements.txt \
  /opt/crowdsec-gui/helper/requirements.txt
```

#### c. Install root-owned helper scripts

```bash
for script in \
  crowdsec-list-decisions.sh \
  crowdsec-list-alerts.sh \
  crowdsec-ip-validation.sh \
  crowdsec-unban.sh \
  crowdsec-ban.sh \
  crowdsec-permanent-ban.sh
do
  sudo install -o root -g root -m 755 \
    "/docker/crowdsec-gui/helper/$script" \
    "/opt/crowdsec-gui/helper/$script"
done
```

#### d. Copy the `.env` to `/opt/crowdsec-gui/.env`

```bash
sudo cp /docker/crowdsec-gui/.env /opt/crowdsec-gui/.env
sudo chown root:crowdsec-gui /opt/crowdsec-gui/.env
sudo chmod 640 /opt/crowdsec-gui/.env
```

#### e. Create Python venv for helper

```bash
sudo -u crowdsec-gui python3 -m venv /opt/crowdsec-gui/venv
sudo -u crowdsec-gui /opt/crowdsec-gui/venv/bin/pip install -r /opt/crowdsec-gui/helper/requirements.txt
```

#### f. Configure sudoers

```bash
sudo cp /opt/crowdsec-gui/helper/sudoers.crowdsec-gui /etc/sudoers.d/crowdsec-gui
sudo chmod 440 /etc/sudoers.d/crowdsec-gui
sudo visudo -cf /etc/sudoers.d/crowdsec-gui
```

#### g. Install and start the systemd service

```bash
sudo cp /opt/crowdsec-gui/helper/crowdsec-gui-helper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crowdsec-gui-helper
sleep 2
curl -fsS http://127.0.0.1:9099/health
```

### 4. Start the UI container

```bash
cd /docker/crowdsec-gui
docker compose config --quiet
docker compose up -d --build crowdsec-ui
```

Verify:
```bash
docker compose logs crowdsec-ui
curl -fsS http://127.0.0.1:8088/health
```

The UI will be available at `http://127.0.0.1:8088` on the host (only — not public yet).

### 5. Configure Caddy

Copy/adapt the Caddyfile:

```bash
# Replace 'crowdsec.example.com' with your actual domain
cp caddy/crowdsec.example.com.Caddyfile /etc/caddy/crowdsec.yourdomain.com.Caddyfile
```

Or add its contents to your main `Caddyfile`.

Generate a bcrypt password hash for basic auth:

```bash
caddy hash-password --plaintext "your_strong_password"
```

Replace the placeholder hash in the Caddyfile with the output.

Reload Caddy:

```bash
sudo systemctl reload caddy
```

### 6. Verify the full stack

1. Visit `https://crowdsec.yourdomain.com` in your browser.
2. Log in with the basic auth credentials.
3. The Dashboard should show CrowdSec status and current ban count.

---

## Configuration

| Variable | Where | Description |
|---|---|---|
| `HELPER_SECRET` | `.env` | Shared secret between UI container and helper. Must match on both sides. |
| `FLASK_SECRET` | `.env` | Required Flask session signing key for CSRF-protected forms. Keep stable across restarts; Compose refuses to start the UI without it. |
| `HELPER_URL` | `docker-compose.yml` | URL to reach the helper. Default: `http://127.0.0.1:9099` through host networking. |
| `AUDIT_LOG` | helper `systemd` env or `.env` | Path to the audit log file. Default: `/opt/crowdsec-gui/helper/crowdsec-audit.log` |
| `TRUSTED_PROXY_IPS` | `.env` | Comma-separated proxy source addresses trusted to set `X-Forwarded-For`. Default: loopback only. |

---

## Security Notes

- The helper binds **only to `127.0.0.1:9099`** — not reachable from outside.
- The UI container reaches the helper through host networking at `127.0.0.1:9099`.
- All ban and unban requests are **POST-only**, CSRF-protected, and validate/canonicalize IP or CIDR input in both the UI and helper.
- Every state-changing UI request includes a per-session CSRF token.
- The UI accepts `X-Forwarded-For` only from configured trusted proxy source addresses.
- Manual bans use fixed **15-minute, 4-hour, 24-hour, 7-day, or 100-year** durations and fixed reasons; the UI cannot pass arbitrary CLI arguments. CrowdSec decisions must expire, so the 100-year option is the reversible equivalent of a permanent ban.
- Ban and unban actions are **audit-logged** with timestamp, IP, and source address.
- The helper secret uses timing-safe comparison. Command failures are recorded in the system journal and returned to the GUI with a bounded error message.
- The helper `sudo` rules allow **only five specific scripts** — no arbitrary commands.
- Caddy handles TLS and basic auth before traffic ever reaches the UI container.
- **Do not** add `NOPASSWD: ALL` to the sudoers file or mount the Docker socket.

---

## GUI Pages

| Page | URL | Description |
|---|---|---|
| Dashboard | `/` | Status overview, active-ban count, recent alerts, your IP status, charts, and manual actions |
| Decisions | `/decisions` | Separate permanent and temporary/automatic decisions; filter, unban, promote a decision to a confirmed 100-year ban, or create a preset-duration ban |
| Alerts | `/alerts` | Recent CrowdSec alerts; filter by source IP or scenario |
| Offending IPs | `/offending-ips` | Top 10 source IPs by loaded alert count, with latest activity, top scenario, current-ban state, and filtered-page links |
| Audit | `/audit` | Log of all ban and unban actions performed through the GUI |

---

## Troubleshooting

**UI cannot start or forms return `Bad Request`:**
```bash
cd /docker/crowdsec-gui
grep '^FLASK_SECRET=' .env
docker compose config --quiet
docker compose up -d --build crowdsec-ui
```
`FLASK_SECRET` must be non-empty and must not change during normal updates. Reload the page after rebuilding the UI to receive a new CSRF token.

**Helper not reachable from the UI:**
```bash
sudo systemctl status crowdsec-gui-helper --no-pager
sudo journalctl -u crowdsec-gui-helper -n 100 --no-pager
curl -fsS http://127.0.0.1:9099/health
```

**Helper starts but cannot manage decisions:**
```bash
sudo visudo -cf /etc/sudoers.d/crowdsec-gui
sudo -u crowdsec-gui sudo /opt/crowdsec-gui/helper/crowdsec-list-decisions.sh
sudo journalctl -u crowdsec-gui-helper -n 100 --no-pager
```

**Audit log permission denied:**
```bash
sudo touch /opt/crowdsec-gui/helper/crowdsec-audit.log
sudo chown crowdsec-gui:crowdsec-gui /opt/crowdsec-gui/helper/crowdsec-audit.log
sudo chmod 640 /opt/crowdsec-gui/helper/crowdsec-audit.log
sudo systemctl restart crowdsec-gui-helper
```

**Helper virtual environment is missing Gunicorn or pip:**
```bash
sudo systemctl stop crowdsec-gui-helper
sudo apt-get install -y python3-venv
sudo rm -rf /opt/crowdsec-gui/venv
sudo -u crowdsec-gui python3 -m venv /opt/crowdsec-gui/venv
sudo -u crowdsec-gui /opt/crowdsec-gui/venv/bin/python -m pip install \
  -r /docker/crowdsec-gui/helper/requirements.txt
sudo systemctl start crowdsec-gui-helper
```

**CrowdSec container name mismatch:**
If your CrowdSec container is not named `crowdsec`, update every helper command script that calls `docker exec` before installing it.

---

## License

MIT — use freely, modify as needed.