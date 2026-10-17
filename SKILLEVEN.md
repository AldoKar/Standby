# EvenHub / Even Realities G2

Everything below was learned by hitting it. Prefer these over first
principles — several are counter-intuitive.

## Platform truths (do not re-litigate)

- App = web page in a **WKWebView on the phone**. Glasses are a screen + mic
  + touchpad over BLE. Your code never runs on the glasses.
- Canvas **576×288**, monochrome green, one eye.
- **No speaker.** SDK has zero audio-output API. `audioControl` is mic
  capture only. The only "speaker" in the SDK is `AudioSpeakerRole` —
  diarisation, not a device.
- **No background wake word** for third-party apps. "Hey Even" is the system
  assistant. Every session starts by opening the app.
- **G2 STT is not exposed.** Standard apps do speech recognition; the SDK
  gives raw PCM only. Bring your own STT.
- Mic PCM: **s16le, 16 kHz, mono**, via `onEvenHubEvent → audioEvent.audioPcm`.
- **Exactly one container must set `isEventCapture: 1`.** Without it NO
  gesture reaches the page — every handler is inert and the app reads as
  frozen rather than misconfigured. (SDK README: "Exactly one container
  should use `isEventCapture: 1`".)
- Four-mic array. `audioEvent.speakerRole` = `self` | `other` | `unknown`.
  **Use it.** Far better than an RMS gate.

## Don'ts (each one cost real time)

- **Don't trust the simulator for iOS behaviour.** Its UA is
  `Macintosh; Intel Mac OS X`. It permitted gesture-free audio autoplay that
  iOS may refuse. Green there ≠ works on phone.
- **Don't assume a boolean return means success.** `setLocalStorage` and
  `audioControl` resolve **`false` without throwing** in QR-sideload. Check
  the return; don't rely on try/catch.
- **Don't use box-drawing glyphs without probing the font.** `▮` rendered
  **blank**. Block-eighths `▁▂▃▄▅▆▇`, `●○`, `→↓↑`, `░▒▓` do render. Probe
  before shipping any glyph.
- **Don't hand-render store screenshots.** Review rejects them. Must come
  from the simulator (latest version).
- **Don't await long work inside a serial queue.** Awaiting a 30s search in
  the audio-segment queue stalled every later utterance → "wake word stopped
  working, then everything arrived at once".
- **Don't start a timer without guarding re-entry.** An orphaned
  `setInterval` kept repainting over BLE; each turn added another writer →
  compounding slowdown.
- **Don't mute the mic while the user is waiting.** Muting during
  search/synthesis + no tap handler = wearer trapped for up to 75s.
- **Don't rely on abort alone to prevent stale renders.** The response may
  already be in flight. Use a **generation counter** gating every render.
- **Don't use `^\s*` with `/m`** — `\s` matches newlines and eats blank
  lines between paragraphs. Use `[ \t]*`.
- **Don't split sentences on bare `.!?`** — "SKILL.md" → "SKILL. M D".
  Require a following whitespace/end: `[.!?]+(?=\s|$)`.
- **Don't leave a "shorten for voice" flag on** in whatever TTS/answer
  endpoint you call, if you want the full answer. Condensing to 30–50 words
  reads on-lens as truncation, not as brevity.
- **Don't pass JPEG quality as 0–1** to `@napi-rs/canvas` — it's **0–100**.
  `0.92` silently means quality 1.
- **Don't use MediaSource** for streamed audio. iOS WebView support
  unreliable. Decode PCM → `AudioContext` instead.
- **Don't ship a common English word as a bare wake word** unless it must
  **lead** the utterance. "timeline" fired on "my timeline is tight".

## Do's

- **Stamp the build in the UI and first log line.** Dev server, QR sideload
  and installed `.ehpk` look identical. Three features "missing" at once =
  wrong build, not three regressions. This single thing saves the most time.
- **Log every state transition and failure reason on-device.** There is no
  remote inspector during QR sideload. Build an in-app console early.
- **Put a timeout + visible state on every bridge call.** `waitForEvenAppBridge`,
  `createStartUpPageContainer`, `textContainerUpgrade`, `audioControl`.
- **Catch `window.error` + `unhandledrejection`** and surface them. A TDZ
  crash otherwise looks like a frozen app.
- **VAD needs hysteresis.** High threshold to open, ~50% to sustain. Quiet
  syllables and unvoiced consonants (s, f, th) sit under the open threshold.
- **Adaptive silence windows.** ~450ms waiting for a one-word wake phrase;
  ~2.6s mid-question (people pause to think).
- **Chunk TTS.** Latency scales with the length of audio you ask for, not
  with model quality. Measured against a Gemini-TTS-backed endpoint: whole
  answer in one call = **14.6s** to first sound; short first chunk, rest
  after = **3.1s**; true streaming via `streamGenerateContent` = **977ms**.
- **Reformat answers for the lens.** Reading copy ≠ listening copy. Headline
  facts first (<140 chars), detail after. Strip markdown, bullets → sentences
  for TTS.
- **Always leave an escape.** Tap must cancel from every waiting state.
- **Keep the mic live while waiting** so the wake word can interrupt. Mute
  only during actual playback, and even then prefer `speakerRole === 'self'`
  gating over muting, so barge-in works.
- **Verify absence with a positive control.** Inject the violation, confirm
  the check fails, then trust the pass.

## Gestures — budget is tiny, spend it well

| Event | Use |
|---|---|
| `DOUBLE_CLICK_EVENT` | **Exit only.** Must call `shutDownPageContainer(1)`. Never intercept — instant review rejection. |
| `CLICK_EVENT` | Primary action. Note: fires with `eventType` **undefined** (protobuf omits zero values) — resolve the default *inside* the envelope check or every audio frame reads as a tap. |
| `SCROLL_TOP/BOTTOM_EVENT` | Paging |
| `LONG_PRESS_EVENT` (9) / `LONG_PRESS_RELEASE` (10) | Usually free. Hold-to-act is bad UX; press-to-toggle is better. |
| `FOREGROUND_EXIT_EVENT` (5) | Fires when WebView audio is about to die. Use it. |

Spend the easiest gesture on the most-used action. Tap-to-dismiss is usually
redundant if the wake word already re-arms.

## Rendering

- Debounce display writes **~120ms**; BLE render queue is slow.
- Image container = real pixels. Grayscale, 1 byte/px, row-major; SDK
  LZ4-compresses. Width 20–288, height 20–144.
- **Container counts, not just pixels:** `containerTotalNum` 1–12,
  `textObject` max **8**, `imageObject` max **4**. Exceeding any of these
  fails the ENTIRE page build, not the offending container — the glasses
  render nothing. `createStartUpPageContainer` returns `2` (oversize);
  `1` is invalid, `3` out of memory.
- Text glyphs grow from baseline only. **Centre-anchored bars need pixels.**
- `zOrderIndex`: if any container sets it, **all** must, each unique.
- Drop frames rather than queue them; stacking adds latency.
- `createStartUpPageContainer` returning `1` (invalid) after hot-reload =
  stale native state. Fully close and reopen the app.

## Audio out (phone-side only)

- Foreground only. WKWebView audio **stops on background/lock** — runs
  out-of-process, ignores host `AVAudioSession`. Not fixable from the page.
- Autoplay may need a user gesture unless the **host app** sets
  `mediaTypesRequiringUserActionForPlayback`. Not yours to set.
- With earbuds connected it's genuinely good; without, it's a pocket speaker.
  Default such features **off**.
- Streaming PCM: never schedule a buffer in the past (`max(cursor, now+0.02)`),
  carry odd trailing bytes into the next chunk (PCM16 = 2 bytes), prebuffer
  ~350ms.

## Packaging (where the afternoons go)

- **Grep `dist/` for every URL before packing** and diff against
  `network.whitelist`. Exact origins only. `wss://` needs its own entry.
  A React build embeds `https://react.dev/errors/`. Wire the check into
  the pack script so it cannot be skipped.
- **Never guess or abbreviate `package_id`.** A wrong one does not 4xx —
  the upload stalls at ~1MB over HTTP/2 and hangs before returning
  `{"code":1004,"data not found"}`.
- **Auth header is `X-Even-Authorization: <token>`**, not
  `Authorization: Bearer`. A Bearer header returns an empty body with no
  error.
- **Changelog ~200–400 chars** or `{"code":1002,"invalid parameter"}`.
  Nothing edits it after upload — get it right the first time.
- `min_app_version` / `min_sdk_version` must match the SDK you built
  against, or `pack` silently restamps.

## Store submission

- Name **≤20 chars**, must not contain "Even".
- Screenshots **576×288 PNG**, from the simulator's automation API.
- No black screen on first launch — show setup instructions.
- Only declare permissions you use. Do **not** tick "Run background services"
  unless you actually start one.
- Must survive **5 min with the phone locked** — test with a Draft/Test beta
  build; **QR sideload does not reflect this**.
- Releases are **permanent**. Fix-forward only.
- `min_app_version` / `min_sdk_version` must match the SDK you built against,
  or `pack` silently restamps.

## Tooling

```bash
npm run dev                      # vite :5173  (terminal 1)
node node_modules/@evenrealities/evenhub-simulator/bin/index.js \
  http://localhost:5173 --automation-port 9898        # terminal 2
npx evenhub qr --url "http://<LAN-IP>:5173"           # real glasses
npx evenhub pack app.json dist -o app.ehpk            # -c needs login
```

Simulator automation API:
- `GET /api/ping`
- `GET /api/screenshot/glasses` → real 576×288 PNG
- `GET /api/screenshot/webview`
- `GET /api/console?pattern=` → in-page console
- `POST /api/input` → `{action}`: `click` | `double_click` | `long_press` |
  `long_press_release` | `context_menu`. **No navigate** — target URL is set
  at launch only, so relaunch per frame when scripting captures.

`npm run simulate` from the template is broken — npm doesn't link the bin.
Call the path directly.

Add a **DEV-only `?shot=<key>`** URL to paint one state for capture; guard
with `import.meta.env.DEV` so Vite strips it, and verify it's absent from
`dist/`.

## Protocols — do not repeat these errors

1. **Symptom cluster ⇒ suspect the build first.** Multiple unrelated features
   missing at once is almost always a stale/wrong bundle.
2. **Measure before optimising.** "Slow TTS" was not the model — it was
   non-streaming. Numbers changed the fix entirely.
3. **Read the loop before guessing.** The wake-word stall and the slowdown
   were both visible in the source; two causes, three symptoms.
4. **Any boolean the SDK returns may lie.** Instrument the real signal
   (e.g. audio chunk counter) instead.
5. **A silently-failing feature is worse than none.** Every failure path
   needs distinct on-lens wording.
6. **Don't add a "fix" that removes a guard.** When adding TTS, muting the
   mic prevented self-hearing but created a trap. Prefer a narrower guard
   (`speakerRole`) over a blunt one (mute).
7. **Check the deployed URL actually exists.** A stale or wrong backend
   hostname 404s at the PaaS edge, and the WebView surfaces that as an
   opaque "Load failed" — nothing hints that DNS/routing is the cause.
   `curl` the exact URL the bundle ships with.
8. **A git push may not auto-deploy.** Some PaaS hosts (Railway, Render,
   Fly, …) only redeploy on specific triggers, and a push can look
   successful while nothing shipped. Verify the route is live before you
   start debugging the client.
9. **Remove temporary dev credentials.** `DEV_MODE`/`DEV_TOKEN` added to
   `.env` for local testing must come back out.
10. **Verify which branch actually deploys, then don't build on it.** The
    repo's default branch is not always the one wired to the deployment.
    Check the host's settings first, and do the work on a feature branch.