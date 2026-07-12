# Deployment Notes

## Components
- Dockerized CrowdSec GUI UI
- Host-side helper service via systemd
- Caddy reverse proxy

## Important paths
- Source repo: `/docker/crowdsec-gui`
- Helper deploy path: `/opt/crowdsec-gui/helper`
- Helper service: `/etc/systemd/system/crowdsec-gui-helper.service`

## Install
Use:

```bash
sudo /usr/local/bin/install-crowdsec-gui
```

## Update
Use:

```bash
sudo /usr/local/bin/update-crowdsec-gui
```

## Reboot persistence
Check:

```bash
systemctl is-enabled caddy
systemctl is-enabled crowdsec-gui-helper
systemctl is-enabled docker
docker inspect -f '{{.HostConfig.NetworkMode}} {{.HostConfig.RestartPolicy.Name}}' crowdsec-ui
```

Expected:
- caddy: enabled
- crowdsec-gui-helper: enabled
- docker: enabled
- crowdsec-ui: `host unless-stopped`

## Notes
- UI uses `network_mode: host`
- Helper is reached at `http://127.0.0.1:9099`
- Caddy proxies to `127.0.0.1:8088`

## Rollback / recovery quick guide
Verify service status:

```bash
docker ps --filter name=crowdsec-ui
systemctl status crowdsec-gui-helper --no-pager
curl -fsS http://127.0.0.1:8088/health
curl -fsS http://127.0.0.1:9099/health
```

Inspect logs:

```bash
docker logs --tail 200 crowdsec-ui
journalctl -u crowdsec-gui-helper -n 200 --no-pager
journalctl -u caddy -n 200 --no-pager
```

Rollback to previous git commit:

```bash
cd /docker/crowdsec-gui
git log --oneline -n 5
git checkout <known-good-commit>
docker compose up -d --build crowdsec-ui
sudo systemctl restart crowdsec-gui-helper
```

Recover safely after rollback:

```bash
curl -fsS http://127.0.0.1:8088/health
curl -fsS http://127.0.0.1:9099/health
```
