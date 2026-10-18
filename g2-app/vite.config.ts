import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

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
    ...(command === 'build' && !process.env.VITE_ENGINE_URL
      ? { 'import.meta.env.VITE_ENGINE_URL': JSON.stringify(PROD_ENGINE_URL) }
      : {}),
  },
  server: {
    host: true, // expose on LAN so the phone can load it via QR
    port: 5173,
    strictPort: true, // the simulator points at :5173, don't silently move ports
  },
}))
