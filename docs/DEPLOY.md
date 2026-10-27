# Deploying Vigiliae

This guide targets a small Linux VPS (1–2 vCPU is enough; the reference
deployment is 4 vCPU / 7.5 GB). Windows works for development but is untested
in production.

## 0. What you need

- A Linux host with Python 3.10+ (3.12 recommended), or Docker.
- A domain name (optional, recommended for HTTPS).
- A thinking kernel on `PATH` (optional). Without one, chat is queue-only.
- A long random token: `python -c "import secrets; print('bot-' + secrets.token_urlsafe(24))"`.

---

## 1. Docker (recommended)

```bash
git clone https://github.com/<your-org>/vigiliae.git
cd vigiliae
cp .env.example .env
$EDITOR .env                  # set BOT_TOKEN; set DSH_BIN if you have a kernel
cp agents.yaml.template agents.yaml
docker compose up -d
docker compose logs -f vigiliae
```

Open `http://<server>:8110` — or put nginx in front (section 3) and use HTTPS.

Register the example agents:

```bash
docker compose exec vigiliae python -m vigiliae.agents sync
```

Upgrade:

```bash
git pull
docker compose build
docker compose up -d
```

The schema is created with `CREATE TABLE IF NOT EXISTS`, and agents are
upserted, so an upgrade does not drop data. (Adding new columns to `tasks` on
an existing database may require a manual `ALTER TABLE`; check `CHANGELOG.md`.)

---

## 2. Bare metal (venv + systemd)

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin vigiliae
sudo mkdir -p /opt/vigiliae && sudo chown vigiliae:vigiliae /opt/vigiliae
sudo -u vigiliae git clone https://github.com/<your-org>/vigiliae.git /opt/vigiliae
cd /opt/vigiliae
sudo -u vigiliae python3 -m venv .venv
sudo -u vigiliae .venv/bin/pip install -r requirements.txt
sudo -u vigiliae cp .env.example .env
sudo -u vigiliae cp agents.yaml.template agents.yaml
sudo -u vigiliae $EDITOR .env    # set BOT_TOKEN etc.
```

`/etc/systemd/system/vigiliae.service`:

```ini
[Unit]
Description=Vigiliae
After=network.target

[Service]
Type=simple
User=vigiliae
Group=vigiliae
WorkingDirectory=/opt/vigiliae
EnvironmentFile=/opt/vigiliae/.env
ExecStart=/opt/vigiliae/.venv/bin/python -m vigiliae
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vigiliae
sudo systemctl status vigiliae
journalctl -u vigiliae -f
```

Note: `EnvironmentFile` values are read by systemd, so `BOT_TOKEN` is available
to the process without being visible in `ps`.

---

## 3. nginx + HTTPS

```nginx
server {
    listen 443 ssl http2;
    server_name bot.example.com;

    ssl_certificate     /etc/letsencrypt/live/bot.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bot.example.com/privkey.pem;

    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:8110;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
```

Use `certbot --nginx -d bot.example.com` for the certificate. Vigiliae itself
does not terminate TLS and binds to `127.0.0.1` by default for this reason.

If you run Docker, publish the port on localhost only:

```yaml
ports:
  - "127.0.0.1:8110:8110"
```

---

## 4. Connect your local agent

The local agent needs two things: a heartbeat loop and a brief poll on startup.
Keep the token in an environment variable, not on the command line (shell
history leaks).

`~/.config/vigiliae/local-agent.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
URL="${VIGILIAE_URL:?set VIGILIAE_URL, e.g. https://bot.example.com}"
TOKEN="${BOT_TOKEN:?set BOT_TOKEN}"

# login once, keep the cookie
curl -s -c /tmp/vigiliae.cookie "$URL/login?k=$TOKEN" -o /dev/null

while true; do
  curl -s -b /tmp/vigiliae.cookie -X POST "$URL/api/heartbeat" \
       -H 'Content-Type: application/json' \
       -d '{"role":"local","meta":{"host":"laptop"}}' >/dev/null || true
  sleep 30
done
```

On session start, pull what happened while you were away:

```bash
curl -s -b /tmp/vigiliae.cookie "$URL/api/brief?mark_read=1" | python -m json.tool
```

Reply from the local agent:

```bash
curl -s -b /tmp/vigiliae.cookie -X POST "$URL/api/messages" \
     -H 'Content-Type: application/json' \
     -d '{"sender":"dsh","body":"Done. I fixed the data gap.","reply_to":12}'
```

For a systemd user service, wrap the loop above in a unit with
`Restart=always`; do not use a cron job for heartbeats (the minimum interval is
one minute and flapping is worse).

---

## 5. Backup

SQLite is a single file. Use the online backup command (safe while running):

```bash
mkdir -p /var/backups/vigiliae
sqlite3 /opt/vigiliae/data/vigiliae.db ".backup '/var/backups/vigiliae/vigiliae-$(date +%F).db'"
find /var/backups/vigiliae -name 'vigiliae-*.db' -mtime +14 -delete
```

Put that in a daily cron/systemd timer. Also back up `agents.yaml` and `.env`
(the latter in a password manager, not in git).

Restore: stop the service, replace `data/vigiliae.db`, start it.

---

## 6. Security checklist

- [ ] `BOT_TOKEN` is long and random; `.env` is `chmod 600` and not in git.
- [ ] Vigiliae binds to `127.0.0.1` (or Docker publishes on localhost only).
- [ ] HTTPS is terminated by nginx/Caddy.
- [ ] The service runs as an unprivileged user.
- [ ] `DSH_HOME` / workspace contains no credentials the agent should not read.
- [ ] `DSH_DAILY_LIMIT` is set to a number you can afford.
- [ ] Tasks that touch production data use `need_approve=1`.
- [ ] Logs are rotated (logrotate or `data/logs` size check).
- [ ] You have tested restore from backup at least once.

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 unauthorized` on every API call | token missing / wrong cookie | `curl "$URL/login?k=$TOKEN"` then reuse the cookie |
| Login page loops | cookie blocked / wrong domain | check HTTPS, `SameSite=Lax`, and that the cookie domain matches |
| Chat replies are slow | kernel takes 30–180 s | expected; the answer is written asynchronously |
| `cloud_thinking: true` but no reply | kernel failed / quota hit | `data/logs/`, `DSH_DAILY_LIMIT`, `DSH_BIN` |
| `deferred` every morning | heavy job fired in a peak window | expected; see `/api/deferred` |
| Container healthcheck fails | app not listening on `0.0.0.0` | set `VIGILIAE_HOST=0.0.0.0` |
| `database is locked` | two writers / slow disk | keep one container; check disk latency |
| Agents do not run | not synced / disabled | `python -m vigiliae.agents sync`, then `GET /api/tasks` |
