import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5180,
    cors: true,
    // Vite 8.x: 'all' como string nao funciona — usar array com hostnames + wildcards.
    // Hosts extras (dominio proprio, tunel) via env: VITE_ALLOWED_HOSTS="meuapp.com.br,.ngrok.io"
    allowedHosts: ['localhost', '127.0.0.1', '0.0.0.0',
                   ...(process.env.VITE_ALLOWED_HOSTS?.split(',').map(h => h.trim()).filter(Boolean) ?? [])],
    proxy: {
      '/api': 'http://localhost:5007',
      '/uploads': 'http://localhost:5007',
    },
  },
})
