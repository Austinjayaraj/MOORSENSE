import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

const backendTarget = process.env.MOORSENSE_BACKEND_URL || 'http://127.0.0.1:8000'

export default defineConfig({
  server: { proxy: { '/api': backendTarget, '/ws': { target: backendTarget, ws: true } } },
  plugins: [react(), tailwindcss()],
})
