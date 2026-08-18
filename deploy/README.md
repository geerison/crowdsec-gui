# Deployment and Recovery Guide

## Runtime layout

| Component | Location | Purpose |
|---|---|---|
| Source checkout | `/docker/crowdsec-gui` | Git checkout, Compose configuration, UI source, and helper source |
| UI | Docker container on `127.0.0.1:8088` | Flask/Gunicorn web UI |
| Helper | `/opt/crowdsec-gui/helper` | Root-owned command scripts and the unprivileged helper application |
| Helper service | `crowdsec-gui-helper.service` | Gunicorn on `127.0.0.1:9099` |
| Reverse proxy | Caddy | TLS and Basic Auth in front of the UI |

The checkout and active helper path are separate. A helper change is not live until it has been installed into `/opt/crowdsec-gui/helper` and the service restarted.

## Standard update

Run this from the branch deployed on the server:

```bash
cd /docker/crowdsec-gui
git pull --ff-only

for script in \
  crowdsec-list-decisions.sh \
  crowdsec-list-alerts.sh \
  crowdsec-ip-validation.sh \
  crowdsec-unban.sh \
  crowdsec-ban.sh \
  crowdsec-permanent-ban.sh
do
  sudo install -o root -g root -m 755 \
    "helper/$script" \
    "/opt/crowdsec-gui/helper/$script"
done

sudo install -o crowdsec-gui -g crowdsec-gui -m 644 \
  helper/helper.py /opt/crowdsec-gui/helper/helper.py
sudo install -o root -g root -m 644 \
  helper/requirements.txt /opt/crowdsec-gui/helper/requirements.txt
sudo install -o root -g root -m 440 \
  helper/sudoers.crowdsec-gui /etc/sudoers.d/crowdsec-gui
sudo install -o root -g root -m 644 \
  helper/crowdsec-gui-helper.service \
  /etc/systemd/system/crowdsec-gui-helper.service

sudo visudo -cf /etc/sudoers.d/crowdsec-gui
sudo systemctl daemon-reload
sudo systemctl restart crowdsec-gui-helper
sleep 2

docker compose config --quiet
docker compose up -d --build crowdsec-ui
```

Do not overwrite `/docker/crowdsec-gui/.env` or `/opt/crowdsec-gui/.env` during a normal update. They contain stable secrets. If `HELPER_SECRET` is intentionally changed, copy the source `.env` to `/opt/crowdsec-gui/.env`, set `root:crowdsec-gui` ownership, and restart both services.

## Post-update verification

```bash
curl -fsS http://127.0.0.1:8088/health
curl -fsS http://127.0.0.1:9099/health
sudo systemctl is-active crowdsec-gui-helper
docker compose ps
```

Then sign in through Caddy and verify Dashboard, Decisions, Alerts, Offending IPs, Audit, one preset-duration ban, one confirmed 100-year ban, and an unban.

## Repair procedures

### UI fails to start because `FLASK_SECRET` is missing

`FLASK_SECRET` is required for stable Gunicorn/CSRF sessions.

```bash
cd /docker/crowdsec-gui
grep '^FLASK_SECRET=' .env
```

If it is missing or empty, generate it once and keep it stable:

```bash
FLASK_SECRET_VALUE="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
sed -i "s/^FLASK_SECRET=.*/FLASK_SECRET=$FLASK_SECRET_VALUE/" .env
unset FLASK_SECRET_VALUE
chmod 600 .env
docker compose up -d --build crowdsec-ui
```

Reload the browser page after this change.

### Helper is unhealthy

```bash
sudo systemctl status crowdsec-gui-helper --no-pager
sudo journalctl -u crowdsec-gui-helper -n 100 --no-pager
curl -fsS http://127.0.0.1:9099/health
```

If the virtual environment lacks `pip` or Gunicorn:

```bash
sudo systemctl stop crowdsec-gui-helper
sudo apt-get install -y python3-venv
sudo rm -rf /opt/crowdsec-gui/venv
sudo -u crowdsec-gui python3 -m venv /opt/crowdsec-gui/venv
sudo -u crowdsec-gui /opt/crowdsec-gui/venv/bin/python -m pip install \
  -r /docker/crowdsec-gui/helper/requirements.txt
sudo systemctl start crowdsec-gui-helper
```

### Audit log cannot be written

```bash
sudo touch /opt/crowdsec-gui/helper/crowdsec-audit.log
sudo chown crowdsec-gui:crowdsec-gui /opt/crowdsec-gui/helper/crowdsec-audit.log
sudo chmod 640 /opt/crowdsec-gui/helper/crowdsec-audit.log
sudo systemctl restart crowdsec-gui-helper
```

### Privileged action fails

Check the helper journal first; the GUI shows a bounded version of the same CrowdSec error.

```bash
sudo visudo -cf /etc/sudoers.d/crowdsec-gui
sudo journalctl -u crowdsec-gui-helper -n 100 --no-pager
```

Re-run the **Standard update** helper-install section if a source update has not reached `/opt/crowdsec-gui/helper`.

## Backup and rollback

Before major changes:

```bash
ts="$(date +%Y%m%d-%H%M%S)"
sudo tar -czf "/root/crowdsec-gui-backup-${ts}.tar.gz" \
  /docker/crowdsec-gui/.env \
  /docker/crowdsec-gui \
  /opt/crowdsec-gui/helper \
  /opt/crowdsec-gui/.env
```

To roll back source, check out a known-good commit, run the standard update steps, then verify both health endpoints.
