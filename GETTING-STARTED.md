# Handle It v2: getting started

Read [`docs/SPEC.md`](docs/SPEC.md) first: it's the product we're building. The shared contract lives in [`contract/`](contract/).

## Run the demo in 1 minute

```bash
cd engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 and press **Simulate cancellation**. Then drive the glasses mirror with **Press**, **Hold** and **Swipe down**, all the way to "Room held / Door code 4417". The engine runs the whole flow on mock data, so everyone can build against it now.

Tests: `cd engine && python test_engine.py`

## Who builds what

| Folder | Owner | Start here |
|---|---|---|
| `engine/` | P1 backend | Replace mocks with real pieces behind the same endpoints; deploy to Vultr with HTTPS |
| `agents/` | P2 Fetch agents | `agents/README.md`: get the orchestrator talking to the engine from asi1.ai |
| `g2-app/` | P3 G2 | `g2-app/README.md`: render `hud.screen`, post gestures to `/input` |
| `voice/` + `dashboard/` | P4 voice and dashboard | `voice/README.md`: ElevenLabs agent and tools; `dashboard/index.html` |
| `contract/` | Everyone | Change it only by PR, and tell the team |

## Rules

- Each person works on their own branch and opens PRs into `main`.
- Never commit `.env` or API keys; use `engine/.env.example`.
- Money decisions live only in `engine/app/policy.py`.
