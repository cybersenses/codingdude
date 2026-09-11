import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'node:fs'

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'))

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Build-time constants so the running bundle identifies itself on screen.
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
  },
  server: {
    proxy: {
      // Dev mode: proxy API calls to the codingdude server.
      '/api': {
        target: 'http://127.0.0.1:8765',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
