# Deploy on Oracle Cloud (Always Free) + Auto Schedule 4 Shorts/Day

This project now supports built-in scheduling with APScheduler and can auto-upload **4 unique videos/day** for `horror` and `mystery`.

## 1. Create Oracle VM

Recommended:
- Shape: `VM.Standard.A1.Flex`
- OS: Ubuntu 22.04
- Public IP enabled
- Open ingress TCP ports: `22`, `8000` (or `80/443` if adding Nginx)

## 2. SSH and bootstrap dependencies

```bash
ssh ubuntu@<YOUR_VM_PUBLIC_IP>
```

Copy this repo to `/opt/yt-shorts`, then run:

```bash
cd /opt/yt-shorts
sudo bash deploy/oracle/bootstrap.sh
```

## 3. Configure environment

```bash
cd /opt/yt-shorts
cp .env.example .env
nano .env
```

Set required keys:
- `PEXELS_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

Scheduler vars (already tuned for 4/day):

```env
SCHEDULER_ENABLED=true
SCHEDULE_TIMES=00:10,06:10,12:10,18:10
SCHEDULE_TIMEZONE=Asia/Kolkata
SCHEDULE_UPLOAD=true
SCHEDULE_NICHES=horror,mystery
SCHEDULE_MISFIRE_GRACE_SECONDS=3600
```

## 4. Install and start as a systemd service

```bash
cd /opt/yt-shorts
sudo bash deploy/oracle/install_service.sh
```

Useful commands:

```bash
sudo systemctl restart yt-shorts
sudo systemctl status yt-shorts
journalctl -u yt-shorts -f
```

## 5. Verify

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Manual trigger from UI/API:
- Open `http://<VM_IP>:8000`
- Generate a test short

Check scheduler logs for automatic runs every 6 hours.

## Notes

- Keep `--workers 1` in systemd (`uvicorn`) so only one scheduler instance runs.
- Story uniqueness is enforced using recent script history from SQLite plus novelty scoring.
- CTA remains at the end of each generated script.
