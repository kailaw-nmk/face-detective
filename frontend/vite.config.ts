import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// OtaGenX のポータル配下 (Tailscale Serve のパスマウント) で配信する場合は
// VITE_BASE_PATH=/face-detect/ を指定してビルドする。
// 未指定時は従来どおり '/' となり、単体起動 (npm run dev) の挙動は変わらない。
export default defineConfig({
  base: process.env.VITE_BASE_PATH ?? '/',
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:52840',
      '/ws': {
        target: 'ws://127.0.0.1:52840',
        ws: true,
      },
    },
  },
})
