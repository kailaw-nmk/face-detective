import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:52840',
      '/ws': {
        target: 'ws://localhost:52840',
        ws: true,
      },
    },
  },
})
