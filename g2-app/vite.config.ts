import { networkInterfaces } from 'node:os'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const PORT = 5173

/** The laptop's LAN address for the "Link glasses" QR in dev (the phone can't open localhost). */
function lanUrl(): string {
  const ips = Object.values(networkInterfaces())
    .flat()
    .filter((a) => a && a.family === 'IPv4' && !a.internal)
    .map((a) => a!.address)
  // Prefer the usual home/office ranges over VPN or virtual adapters.
  const ip = ips.find((a) => /^(192\.168|10)\./.test(a)) ?? ips.find((a) => /^172\.(1[6-9]|2\d|3[01])\./.test(a)) ?? ips[0]
  return ip ? `http://${ip}:${PORT}` : ''
}

// Short timestamp stamped into the UI and first log line (dev, QR sideload and .ehpk look identical otherwise).
const buildId = new Date().toISOString().slice(5, 16).replace('T', ' ')

// Engine baked into production builds (.ehpk). Must match the network whitelist in app.json.
// Override with VITE_ENGINE_URL; `npm run dev` keeps the old fallback (same host on :8000).
const PROD_ENGINE_URL = 'https://149.28.76.19.sslip.io'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  plugins: [react()],
  define: {
    __BUILD_ID__: JSON.stringify(buildId),
    __LAN_URL__: JSON.stringify(command === 'serve' ? lanUrl() : ''),
    ...(command === 'build' && !process.env.VITE_ENGINE_URL
      ? { 'import.meta.env.VITE_ENGINE_URL': JSON.stringify(PROD_ENGINE_URL) }
      : {}),
  },
  server: {
    host: true, // expose on LAN so the phone can load it via QR
    port: PORT,
    strictPort: true, // the simulator points at :5173, don't silently move ports
  },
}))
