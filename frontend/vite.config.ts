import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 配信用のビルドは npm run build が --base=/face-detect/ を渡すため、
// ここの既定値 '/' が使われるのは npm run dev のときだけ。
// dev サーバー (:52841) は従来どおりルート直下で動く。
//
// build に --base が付いているのは、素の vite build で作った dist が
// /assets/... を参照し、localhost:52840 では動くのに Tailscale Serve の
// /face-detect/ 経由だけ真っ白になるため。localhost だけ見ていると
// 気付けないので、既定を安全側に倒している。
// VITE_BASE_PATH を指定すれば dev 側の base も上書きできる。
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
