import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  test: { environment: 'jsdom', css: false },
  plugins: [react()],
  server: {
    // Same-origin API calls in development, so session/CSRF cookies just work.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
      },
    },
  },
})
