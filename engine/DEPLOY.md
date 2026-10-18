# Deploy the engine to Vultr

The result: `https://<your-domain>` serves the engine with a valid certificate. Caddy terminates HTTPS and forwards to uvicorn on `127.0.0.1:8000`, and systemd keeps uvicorn running and restarts it after crashes and reboots.

```
G2 / dashboard / agents ──HTTPS──► Caddy :443 ──► uvicorn 127.0.0.1:8000 (systemd)
```

Files: [`deploy/handle-it.service`](deploy/handle-it.service) (systemd unit) and [`deploy/Caddyfile`](deploy/Caddyfile).

## 1. Create the VM

In the Vultr console: **Deploy → Cloud Compute → Ubuntu 24.04**, the smallest plan, a region close to LA. Add your SSH key. Write down the public IPv4.

If you attach a Vultr **Firewall Group**, allow TCP 22, 80 and 443.

## 2. Pick a domain

Let's Encrypt needs a hostname, not a bare IP. Either:

- **No setup:** `<ip>.sslip.io`, e.g. `203.0.113.10.sslip.io`. It resolves to that IP automatically.
- **Your own domain:** add an `A` record pointing to the VM's IP and wait until `nslookup <domain>` returns it.

Below, replace `DOMAIN` with your choice and `IP` with the VM's IP.

## 3. Install packages

```bash
ssh root@IP
```

```bash
apt update && apt install -y python3-venv git debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy
```

## 4. Get the code

The repo is private, so the server reads it with a **deploy key**: a read-only key that only works for this repo and lives only on the server.

```bash
useradd --system --no-create-home --home-dir /opt/handle-it --shell /usr/sbin/nologin handleit
ssh-keygen -t ed25519 -N "" -f /root/.ssh/handleit_deploy -C handle-it-vultr
cat /root/.ssh/handleit_deploy.pub
```

A repo admin adds that `ssh-ed25519 ...` line in GitHub: **Settings → Deploy keys → Add deploy key**, without write access. Then:

```bash
GIT_SSH_COMMAND="ssh -i /root/.ssh/handleit_deploy -o StrictHostKeyChecking=accept-new" \
  git clone git@github.com:AldoKar/LA-AI-Hakcthon-Project.git /opt/handle-it
git -C /opt/handle-it config core.sshCommand "ssh -i /root/.ssh/handleit_deploy"
git config --global --add safe.directory /opt/handle-it
cd /opt/handle-it/engine
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env    # at least CALL_MODE=mock and ANTHROPIC_API_KEY=...
.venv/bin/python test_engine.py    # must end with "engine ok"; also feeds GET /tests on the dashboard
chown -R handleit:handleit /opt/handle-it
chmod 600 .env
```

Keep the whole repo: the engine reads `contract/mock-data.json` and serves `dashboard/` from the repo root.

## 5. Start the engine with systemd

```bash
cp /opt/handle-it/engine/deploy/handle-it.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now handle-it
curl -s localhost:8000/state | head -c 200; echo
```

## 6. Put Caddy in front

```bash
sed "s/DOMAIN/YOUR_DOMAIN/" /opt/handle-it/engine/deploy/Caddyfile > /etc/caddy/Caddyfile
systemctl reload caddy
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

Caddy requests the certificate on the first request. It can take up to a minute.

## 7. Check it

From your laptop:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://DOMAIN/state
curl -N https://DOMAIN/events
```

(In PowerShell, write `curl.exe` and add `--ssl-no-revoke`.) The first should print `200` with no certificate error. The second should print `state.snapshot`, then `hud.screen`, then `: heartbeat` every 15 s. While it runs, `curl -X POST https://DOMAIN/simulate/cancel` from another terminal should push new events right away. Then open `https://DOMAIN` for the dashboard.

Give the team `https://DOMAIN` as the engine URL (G2 app, agents, dashboard).

## Updating after a push

As root (the deploy key belongs to root):

```bash
cd /opt/handle-it && git pull
engine/.venv/bin/pip install -r engine/requirements.txt
(cd engine && .venv/bin/python test_engine.py)
chown -R handleit:handleit /opt/handle-it
systemctl restart handle-it
```

If the pull changed `engine/deploy/handle-it.service`, copy it again first, since systemd runs its own copy:

```bash
cp /opt/handle-it/engine/deploy/handle-it.service /etc/systemd/system/ && systemctl daemon-reload
```

A restart takes about 3 seconds (open `/events` streams are cut after 3 s) and wipes the in-memory demo state, the same as `/demo/reset`. The glasses and dashboard reconnect on their own.

## Troubleshooting

| Symptom | Look at |
|---|---|
| `502` from Caddy | Right after a restart, wait a few seconds. Otherwise `journalctl -u handle-it -n 50`: the engine crashed or isn't running |
| `curl` on Windows: `CRYPT_E_REVOCATION_OFFLINE` | The laptop's network blocks the certificate revocation check, not a server problem. Use `curl.exe --ssl-no-revoke`; browsers are fine |
| `git pull`: `Permission denied (publickey)` | The deploy key is missing from GitHub, or the pull didn't run as root |
| `not checked: no ANTHROPIC_API_KEY` in a call outcome | Add the key to `engine/.env`, then `systemctl restart handle-it` |
| `/tests` returns 404 | Run `.venv/bin/python test_engine.py` once in `engine/` |
| Certificate error | `journalctl -u caddy -n 50`. Usually DNS doesn't point to the VM yet, or port 80/443 is blocked |
| Events arrive late or in bursts | Make sure `/etc/caddy/Caddyfile` still has `flush_interval -1` |
| A `.env` change has no effect | `systemctl restart handle-it` |

Keep **one** uvicorn worker. State and SSE subscribers live in memory, so a second worker would split them.
