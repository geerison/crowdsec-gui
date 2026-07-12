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
