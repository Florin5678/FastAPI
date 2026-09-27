import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, forward API calls to a local `uvicorn app.main:app` on :8000.
// In production FastAPI serves the built files itself, so everything is same-origin.
const api = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': api,
      '/auth': api,
      '/gmail': api,
      '/emails': api,
      '/summaries': api,
      '/digest': api,
      '/widgets': api,
    },
  },
})
