/**
 * WebSocket および API 通信で使用する型定義
 */

/** 処理進捗メッセージ */
export type ProgressMessage = {
  type: 'progress'
  current_file: string
  processed: number
  total: number
  extracted: number
  skipped: number
  errors: number
  split_count?: number
}

/** 処理完了メッセージ */
export type CompleteMessage = {
  type: 'complete'
  total: number
  extracted: number
  skipped: number
  errors: number
  split_count?: number
  error_files: string[]
}

/** エラーメッセージ */
export type ErrorMessage = {
  type: 'error'
  message: string
}

/** WebSocket で受信するメッセージの Union 型 */
export type WSMessage = ProgressMessage | CompleteMessage | ErrorMessage

/** アプリケーション全体の状態 */
export type AppState = 'idle' | 'scanning' | 'complete'

/** パス検証 API レスポンス */
export type ValidatePathResponse = {
  valid: boolean
  image_count: number
  message: string
}

/** スキャン開始 API レスポンス */
export type StartResponse = {
  job_id: string
  dest_folder: string
}
