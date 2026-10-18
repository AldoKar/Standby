# Instructions for coding agents

Handle It, LA Hacks AI Hackathon. Hard deadline: Sunday Oct 18, 12:00 PM PDT; code freeze 10:00 AM.

## Read first

- `docs/SPEC.md`: the product. Build exactly this flow; no extra features.
- `contract/`: `events.md`, `api.md`, `mock-data.json`. This is the interface between all parts.
- `GETTING-STARTED.md`: how to run the engine and who owns which folder.

## Ownership

| Folder | Owner |
|---|---|
| `engine/` | P1 backend |
| `agents/` | P2 Fetch agents |
| `g2-app/` | P3 glasses |
| `voice/`, `dashboard/` | P4 voice and dashboard |
| `contract/`, `docs/` | Everyone, by PR only |

Only edit the folders your person owns. If you need a change elsewhere (a new endpoint, a new event field), don't make it; write down what's needed for the owner.

`backend/`, `contracts/` and `frontend/` are the old plan. Don't build on them. You may copy code from them, such as the Even SDK wiring in `frontend/src/glasses/bridge.ts`.

## Rules

- **Contract first.** Never rename or remove an event, field or endpoint without a PR that edits `contract/` and a heads-up to the team.
- **Money decisions live only in `engine/app/policy.py`.** An LLM never decides a spend and never sees card data.
- **The engine writes all glasses screen copy** (`hud.screen`). The glasses only render `lines` (at most 3) and send gestures to `POST /input`.
- **Glasses gestures:** tap → `press`, long press → `hold`, swipe down → `swipe_down`. Never use double press: on the root page it opens the system exit dialog.
- **The voice agent** says it is an AI in its first sentence, calls business lines only, and never phones or pays the airline that cancelled.
- **No secrets in git.** Use `.env` files (see `engine/.env.example`).
- **Keep it demo-reliable:** every external call has a fallback (recorded call, text instead of cards, simulator instead of glasses).

## Workflow

- Work on your own branch (`p1-engine`, `p2-agents`, `p3-g2`, `p4-voice`) and open PRs into `main`.
- Before a PR: `cd engine && python test_engine.py` must pass. If you touched the flow, also click through the dashboard at http://localhost:8000 (Simulate → Press → Press → Hold → Hold).
- Small commits with clear messages. Pull `main` often; teammates push all night.
