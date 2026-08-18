# Production Checklist

## Before updating

```bash
cd /docker/crowdsec-gui
git status --short
git branch --show-current
grep '^HELPER_SECRET=' .env
grep '^FLASK_SECRET=' .env
sudo systemctl is-active crowdsec-gui-helper
curl -fsS http://127.0.0.1:9099/health
```

- Keep `.env` outside Git and preserve both secrets during updates.
- Ensure the current branch is the branch intended for production.
- Review the deployment guide when a change touches `helper/`, `docker-compose.yml`, or `.env.example`.

## Deploy

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

## Verify services and logs

```bash
docker compose ps
sudo systemctl is-active crowdsec-gui-helper
sudo systemctl is-active caddy
curl -fsS http://127.0.0.1:8088/health
curl -fsS http://127.0.0.1:9099/health
docker compose logs crowdsec-ui --tail=50
sudo journalctl -u crowdsec-gui-helper -n 50 --no-pager
```

## Verify in the browser

- Caddy requires Basic Auth and serves the expected TLS certificate.
- Dashboard loads and shows CrowdSec status, charts, and a human-readable ban duration.
- Decisions separates permanent bans from temporary and automatic decisions.
- A preset-duration manual ban works, a confirmed 100-year ban works, and an unban works.
- Alerts and Offending IPs load; Offending IPs links to filtered Alerts and Decisions pages.
- Audit shows GUI actions without exposing secrets.

## Reboot persistence

```bash
systemctl is-enabled caddy
systemctl is-enabled crowdsec-gui-helper
systemctl is-enabled docker
docker inspect -f '{{.HostConfig.NetworkMode}} {{.HostConfig.RestartPolicy.Name}}' crowdsec-ui
```

## Repair triggers

- If Compose reports a missing `FLASK_SECRET`, set a stable non-empty value in `/docker/crowdsec-gui/.env`, then rebuild the UI.
- If helper actions fail, inspect `sudo journalctl -u crowdsec-gui-helper -n 100 --no-pager`, validate sudoers with `visudo`, and reinstall helper files from the checkout.
- If audit writes fail, recreate `/opt/crowdsec-gui/helper/crowdsec-audit.log` owned by `crowdsec-gui:crowdsec-gui` with mode `640`.
