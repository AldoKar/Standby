import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

// Short timestamp stamped into the UI and first log line (dev, QR sideload and .ehpk look identical otherwise).
const buildId = new Date().toISOString().slice(5, 16).replace('T', ' ')

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    __BUILD_ID__: JSON.stringify(buildId),
  },
  resolve: {
    // Shared contract at the repo root. Matches "paths" in tsconfig.app.json.
    alias: { '@contracts': fileURLToPath(new URL('../contracts', import.meta.url)) },
  },
  server: {
    host: true, // expose on LAN so the phone can load it later via QR
    port: 5173,
    strictPort: true, // the simulator points at :5173, don't silently move ports
    fs: { allow: ['..'] }, // allow serving ../contracts
  },
})
