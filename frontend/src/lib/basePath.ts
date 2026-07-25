/**
 * ビルド時の base パス (`/` または `/face-detect/`) を前置した URL を組み立てる。
 *
 * Tailscale Serve のパスマウント経由では `/face-detect` がブラウザから送られるため、
 * API / WebSocket の URL にも同じプレフィックスが必要になる。
 * `import.meta.env.BASE_URL` は vite が `base` 設定から埋め込む値で、末尾にスラッシュを含む。
 */

/**
 * API パスに base を前置した絶対パスを返す。
 *
 * @param path - `/api/start` のようなルート起点のパス
 * @returns base を前置したパス（例: `/face-detect/api/start`）
 */
export function apiPath(path: string): string {
  return `${import.meta.env.BASE_URL}${path.replace(/^\//, '')}`
}

/**
 * WebSocket の絶対 URL を組み立てる。
 *
 * @param path - `/ws/<jobId>` のようなルート起点のパス
 * @returns `ws://` または `wss://` から始まる絶対 URL
 */
export function wsUrl(path: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${apiPath(path)}`
}
