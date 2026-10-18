# Run the agents on the Vultr server

Both agents run next to the engine under systemd, so ASI:One always reaches them (a laptop that sleeps
leaves `@standby` stuck on "Reasoning..."). They need no open ports: they reach Agentverse through
their mailboxes, outbound only, and talk to the engine on `127.0.0.1:8000`.

**Only one copy of each agent may run.** The seed decides the address, and the address owns the
Agentverse mailbox. Stop any copy on a laptop before starting these.

## One-time setup (as root, on the server)

The engine must already be deployed (`engine/DEPLOY.md`) at `/opt/handle-it`.

1. Seeds and keys. The services read `/opt/handle-it/engine/.env`, then `/opt/handle-it/.env`.
   One of them needs `AGENT_SEED`, `CALLER_SEED` and `ANTHROPIC_API_KEY`. Check without printing:

   ```bash
   grep -c '^AGENT_SEED=.' /opt/handle-it/.env /opt/handle-it/engine/.env
   grep -c '^CALLER_SEED=.' /opt/handle-it/.env /opt/handle-it/engine/.env
   ```

   Each seed should show `1` in one file.

2. Python environment:

   ```bash
   cd /opt/handle-it/agents
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   chown -R handleit:handleit /opt/handle-it
   ```

3. Services:

   ```bash
   cp /opt/handle-it/agents/deploy/standby-agent.service /opt/handle-it/agents/deploy/standby-caller.service /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now standby-caller standby-agent
   ```

4. Check the addresses. They must be the registered ones:

   ```bash
   journalctl -u standby-agent -n 30 --no-pager | grep -i agent1
   journalctl -u standby-caller -n 30 --no-pager | grep -i agent1
   ```

   - Orchestrator: `agent1qwyumnrwayag0jyfy28ajzwwdn5rxz4awr4ft5rltr86zs36444z5f6mmzf`
   - Caller: `agent1q2480yjzfu7jv4sk7x9v2s0v7zf89mj9czpqs3sqtaypt5kyd4xkg7yge07`

   A different address means a different seed: fix the `.env` and restart.

5. In [asi1.ai](https://asi1.ai): `@standby is UA1 on time?`, then `@standby My UA183 got cancelled, handle it`.

## Update after a merge

```bash
cd /opt/handle-it && git pull && chown -R handleit:handleit . && systemctl restart standby-caller standby-agent
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `@standby` stuck on "Reasoning..." | `systemctl status standby-agent`; another copy running elsewhere with the same seed |
| `AGENT_SEED is not set` in the logs | Step 1: the seed isn't in either `.env` |
| Replies but "live answers unavailable" | The engine needs `ANTHROPIC_API_KEY` (and `AEROAPI_KEY` for live flights) |
| Logs: `journalctl -u standby-agent -f` | |
