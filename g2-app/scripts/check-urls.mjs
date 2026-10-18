// Fails the pack if dist/ contains an https origin that app.json's network whitelist doesn't list.
// Run after `vite build`: node scripts/check-urls.mjs
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

// Strings that appear in the bundle but are never requested (React's error-message links).
const NOT_REQUESTED = new Set(['https://react.dev'])

const app = JSON.parse(readFileSync('app.json', 'utf8'))
const net = app.permissions.find((p) => p.name === 'network')
const allowed = new Set((net?.whitelist ?? []).map((u) => new URL(u).origin))

const files = []
const walk = (d) => readdirSync(d).forEach((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : files.push(join(d, f))))
walk('dist')

const found = new Set()
for (const f of files.filter((f) => /\.(js|html|css)$/.test(f))) {
  for (const m of readFileSync(f, 'utf8').matchAll(/\b(?:https|wss):\/\/[a-zA-Z0-9.-]+(?::\d+)?/g)) found.add(m[0])
}
const missing = [...found].filter((o) => !allowed.has(o) && !NOT_REQUESTED.has(o))
console.log('origins in dist:', [...found].join(', ') || '(none)')
if (missing.length) {
  console.error('NOT in app.json whitelist:', missing.join(', '))
  process.exit(1)
}
console.log('whitelist ok')
