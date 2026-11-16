import process from 'node:process'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The browser only ever talks to this dev server; `/api` is proxied to the
// backend, which stays bound to 127.0.0.1. For access from other devices,
// start.ps1 -Remote / start.sh --remote set LLM_COUNCIL_HOST to this PC's
// Tailscale IP so the app is reachable only inside the tailnet, not the LAN.
// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: process.env.LLM_COUNCIL_HOST || 'localhost',
    allowedHosts: ['.ts.net'], // Tailscale MagicDNS names (IP access is always allowed)
    proxy: {
      '/api': 'http://127.0.0.1:8001',
    },
  },
})
