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

```bash
useradd --system --no-create-home --home-dir /opt/handle-it --shell /usr/sbin/nologin handleit
git clone https://github.com/AldoKar/LA-AI-Hakcthon-Project /opt/handle-it
cd /opt/handle-it/engine
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env    # then edit it: nano .env
chown -R handleit:handleit /opt/handle-it
chmod 600 .env
```

The repo must be public for this clone, or use a GitHub deploy key or token. Keep the whole repo: the engine reads `contract/mock-data.json` and serves `dashboard/index.html` from the repo root.

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
curl -sI https://DOMAIN/state
curl -N https://DOMAIN/events
```

The first should return `200` with no certificate warning. The second should print `state.snapshot`, then `hud.screen`, then `: heartbeat` every 15 s. While it runs, `curl -X POST https://DOMAIN/simulate/cancel` from another terminal should push new events right away. Then open `https://DOMAIN` for the dashboard.

Give the team `https://DOMAIN` as the engine URL (G2 app, agents, dashboard).

## Updating after a push

```bash
cd /opt/handle-it && sudo -u handleit git pull
sudo -u handleit engine/.venv/bin/pip install -r engine/requirements.txt
systemctl restart handle-it
```

A restart wipes the in-memory demo state, the same as `/demo/reset`, and SSE clients reconnect on their own.

## Troubleshooting

| Symptom | Look at |
|---|---|
| `502` from Caddy | `journalctl -u handle-it -n 50`, the engine crashed or isn't running |
| Certificate error | `journalctl -u caddy -n 50`. Usually DNS doesn't point to the VM yet, or port 80/443 is blocked |
| Events arrive late or in bursts | Make sure `/etc/caddy/Caddyfile` still has `flush_interval -1` |
| A `.env` change has no effect | `systemctl restart handle-it` |

Keep **one** uvicorn worker. State and SSE subscribers live in memory, so a second worker would split them.
