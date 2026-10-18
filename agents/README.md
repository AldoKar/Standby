![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# Fetch.ai agents (owner: P2)

| Agent | Name | Address | Job |
|---|---|---|---|
| Orchestrator | `handle-it` | _fill in after first run_ | ASI:One front door: plans within the mandate, calls the engine, hires the Caller, reports in chat |
| Caller | `handle-it-caller` | _fill in after first run_ | Places disclosed AI calls to business lines; paid $1.99 per call through the Payment Protocol |

## Run

```bash
cd agents
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
BACKEND_URL=http://localhost:8000 python orchestrator/agent.py
```

On first run the agent prints its address and an inspector link. Open the link and connect the mailbox, so the agent is reachable from Agentverse and ASI:One. Run both agents on the Vultr box under systemd for the demo.

## Checklist (Fetch requirements)

- [ ] Both agents registered on Agentverse in the **Innovation Lab** category, manifests published
- [ ] The whole flow runs in one asi1.ai chat: "My UA183 got cancelled, handle it" → options → "book" → call → result
- [ ] By 6 PM: ASI:One finds the agent by @handle and by plain-language query; check whether it shows 2 messages per user turn
- [ ] Interactive Cards for the options, the review step and the result (text fallback: "reply book")
- [ ] Caller paid through the Payment Protocol, with one retry-on-voicemail path
- [ ] Names and addresses filled in above; shared-chat URL saved for the Submission Agent
