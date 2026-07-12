# Production Checklist

## Update flow
```bash
cd /docker/crowdsec-gui
git pull
sudo /usr/local/bin/update-crowdsec-gui
```

## Verify services
```bash
docker compose ps
sudo systemctl status crowdsec-gui-helper --no-pager
sudo systemctl status caddy --no-pager
```

## Verify logs
```bash
docker compose logs crowdsec-ui --tail=50
sudo journalctl -u crowdsec-gui-helper -n 50 --no-pager
```

## Verify helper endpoints
```bash
cd /docker/crowdsec-gui
curl -s http://127.0.0.1:9099/decisions -H "X-Helper-Secret: $(grep '^HELPER_SECRET=' .env | cut -d= -f2-)" | head
curl -s http://127.0.0.1:9099/alerts -H "X-Helper-Secret: $(grep '^HELPER_SECRET=' .env | cut -d= -f2-)" | head
```

## Verify UI manually
- Dashboard loads
- CrowdSec status is reachable
- Decisions page works
- Alerts page works
- Audit page works
- Charts render
- Pagination works
- Manual unban works

## Reboot persistence
```bash
systemctl is-enabled caddy
systemctl is-enabled crowdsec-gui-helper
systemctl is-enabled docker
docker inspect -f '{{.HostConfig.NetworkMode}} {{.HostConfig.RestartPolicy.Name}}' crowdsec-ui
```

```
