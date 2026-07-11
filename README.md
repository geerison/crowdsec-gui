# CrowdSec GUI v1

A self-hosted admin GUI for [CrowdSec](https://crowdsec.net/) — view decisions, bans, and alerts; unban IPs; and audit all actions.

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
- is allowed to run only three specific scripts via `sudo` (list decisions, list alerts, unban IP)
- requires a shared secret header from the UI container
- logs every unban action

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
│   │   └── audit.html
│   └── static/
│       └── style.css
├── helper/
│   ├── helper.py                    ← Flask helper API (runs on HOST)
│   ├── requirements.txt
│   ├── crowdsec-list-decisions.sh   ← calls docker exec crowdsec cscli decisions list
│   ├── crowdsec-list-alerts.sh      ← calls docker exec crowdsec cscli alerts list
│   ├── crowdsec-unban.sh            ← calls docker exec crowdsec cscli decisions delete
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
# Edit .env and set a strong random HELPER_SECRET:
python3 -c "import secrets; print('HELPER_SECRET=' + secrets.token_hex(32))" >> .env
```

### 3. Set up the host helper

#### a. Create a dedicated user

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin crowdsec-gui
```

#### b. Copy helper files to `/opt/crowdsec-gui`

```bash
sudo mkdir -p /opt/crowdsec-gui
sudo cp -r /docker/crowdsec-gui/helper /opt/crowdsec-gui/helper
sudo chown -R crowdsec-gui:crowdsec-gui /opt/crowdsec-gui
```

#### c. Make scripts executable (and owned by root for sudoers safety)

```bash
sudo chown root:root /opt/crowdsec-gui/helper/*.sh
sudo chmod 755 /opt/crowdsec-gui/helper/*.sh
```

#### d. Copy the `.env` to `/opt/crowdsec-gui/.env`

```bash
sudo cp /docker/crowdsec-gui/.env /opt/crowdsec-gui/.env
sudo chown crowdsec-gui:crowdsec-gui /opt/crowdsec-gui/.env
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
sudo visudo -c  # verify no syntax errors
```

#### g. Install and start the systemd service

```bash
sudo cp /opt/crowdsec-gui/helper/crowdsec-gui-helper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crowdsec-gui-helper
sudo systemctl status crowdsec-gui-helper
```

### 4. Start the UI container

```bash
cd /docker/crowdsec-gui
docker compose up -d
```

Verify:
```bash
docker compose logs crowdsec-ui
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
| `HELPER_URL` | `docker-compose.yml` | URL to reach the helper. Default: `http://host.docker.internal:9099` |
| `AUDIT_LOG` | helper `systemd` env or `.env` | Path to the audit log file. Default: `/opt/crowdsec-gui/helper/crowdsec-audit.log` |

---

## Security Notes

- The helper binds **only to `127.0.0.1:9099`** — not reachable from outside.
- The UI container reaches the helper via `host.docker.internal` (Linux: `host-gateway`).
- All unban requests are **POST-only** with IP validation on both the UI and helper.
- Unban actions are **audit-logged** with timestamp, IP, and source address.
- The helper `sudo` rules allow **only three specific scripts** — no arbitrary commands.
- Caddy handles TLS and basic auth before traffic ever reaches the UI container.
- **Do not** add `NOPASSWD: ALL` to the sudoers file or mount the Docker socket.

---

## GUI Pages

| Page | URL | Description |
|---|---|---|
| Dashboard | `/` | Status overview, active ban count, recent alerts, your IP ban status |
| Decisions | `/decisions` | Full list of active bans; filter by IP or scenario; unban buttons |
| Alerts | `/alerts` | Recent CrowdSec alerts; filter by source IP or scenario |
| Audit | `/audit` | Log of all unban actions performed through the GUI |

---

## Troubleshooting

**Helper not reachable from UI container:**
```bash
# On host, verify helper is listening:
ss -tlnp | grep 9099
# From host, test helper:
curl -H "X-Helper-Secret: your_secret" http://127.0.0.1:9099/decisions
```

**`docker exec` permission denied in helper:**
```bash
# Verify sudoers is correct and the crowdsec-gui user can run the scripts:
sudo -u crowdsec-gui sudo /opt/crowdsec-gui/helper/crowdsec-list-decisions.sh
```

**CrowdSec container name mismatch:**
If your CrowdSec container is not named `crowdsec`, edit the three shell scripts in `helper/` and change `crowdsec` to your container name.

---

## License

MIT — use freely, modify as needed.