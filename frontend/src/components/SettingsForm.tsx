import { useState } from 'react'
import type { ValidatePathResponse } from '../types'

/** SettingsForm コンポーネントの Props */
interface SettingsFormProps {
  /** スキャン開始時のコールバック */
  onStart: (source: string, threshold: number, spreadSplit: boolean) => void
  /** フォームを無効化するフラグ（スキャン中など） */
  disabled: boolean
}

/** パス検証の状態 */
type ValidationState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'valid'; imageCount: number; message: string }
  | { status: 'invalid'; message: string }

/**
 * スキャン設定入力フォームコンポーネント。
 * 入力フォルダ・保存先フォルダ・顔サイズ閾値を設定し、スキャンを開始する。
 */
function SettingsForm({ onStart, disabled }: SettingsFormProps) {
  const [sourcePath, setSourcePath] = useState(
    () => localStorage.getItem('face-detective-sourcePath') ?? ''
  )
  const [threshold, setThreshold] = useState(() => {
    const saved = localStorage.getItem('face-detective-threshold')
    const parsed = saved !== null ? Number(saved) : NaN
    return Number.isFinite(parsed) && parsed >= 1 && parsed <= 100 ? parsed : 5
  })
  const [spreadSplit, setSpreadSplit] = useState(() => {
    return localStorage.getItem('face-detective-spreadSplit') === 'true'
  })
  const [validation, setValidation] = useState<ValidationState>({ status: 'idle' })

  /**
   * 入力フォルダパスを API で検証する
   */
  const validatePath = async () => {
    const trimmed = sourcePath.trim()
    if (!trimmed) {
      setValidation({ status: 'invalid', message: 'フォルダパスを入力してください' })
      return
    }

    setValidation({ status: 'loading' })

    try {
      const response = await fetch('/api/validate-path', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: trimmed }),
      })

      const data: ValidatePathResponse = await response.json() as ValidatePathResponse

      if (data.valid) {
        setValidation({
          status: 'valid',
          imageCount: data.image_count,
          message: data.message,
        })
      } else {
        setValidation({ status: 'invalid', message: data.message })
      }
    } catch {
      setValidation({ status: 'invalid', message: 'パスの検証中にエラーが発生しました' })
    }
  }

  /** フォームの送信処理 */
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    if (!sourcePath.trim()) return
    if (validation.status !== 'valid') return

    localStorage.setItem('face-detective-sourcePath', sourcePath.trim())
    localStorage.setItem('face-detective-threshold', String(threshold))
    localStorage.setItem('face-detective-spreadSplit', String(spreadSplit))

    onStart(sourcePath.trim(), threshold, spreadSplit)
  }

  const isSourceValidated = validation.status === 'valid'
  const canSubmit = sourcePath.trim() !== '' && isSourceValidated && !disabled

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-md p-6 space-y-6">

      {/* 入力フォルダパス */}
      <div className="space-y-1">
        <label className="block text-sm font-medium text-gray-700">
          入力フォルダパス
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={sourcePath}
            onChange={(e) => {
              setSourcePath(e.target.value)
              setValidation({ status: 'idle' })
            }}
            onBlur={sourcePath.trim() ? validatePath : undefined}
            placeholder="例: C:\Users\Pictures または \\NAS\photos"
            disabled={disabled}
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:text-gray-400"
          />
          <button
            type="button"
            onClick={validatePath}
            disabled={disabled || !sourcePath.trim() || validation.status === 'loading'}
            className="px-4 py-2 text-sm font-medium text-white bg-gray-500 rounded-lg hover:bg-gray-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {validation.status === 'loading' ? '確認中...' : '確認'}
          </button>
        </div>

        {/* 検証結果メッセージ */}
        {validation.status === 'valid' && (
          <p className="text-sm text-green-600">
            {validation.message}（画像 {validation.imageCount} 件）
          </p>
        )}
        {validation.status === 'invalid' && (
          <p className="text-sm text-red-600">{validation.message}</p>
        )}
        {validation.status === 'valid' && sourcePath.trim() && (
          <p className="text-sm text-gray-500 mt-1">
            保存先: {sourcePath.trim().replace(/[\\/]+$/, '') + '_face'}
          </p>
        )}
      </div>

      {/* 顔サイズ閾値スライダー */}
      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <label className="block text-sm font-medium text-gray-700">
            顔サイズ閾値
          </label>
          <span className="text-sm font-semibold text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
            {threshold}%
          </span>
        </div>
        <input
          type="range"
          min={1}
          max={100}
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
          disabled={disabled}
          className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-500 disabled:cursor-not-allowed"
        />
        <div className="flex justify-between text-xs text-gray-400">
          <span>1%（小さい顔も対象）</span>
          <span>100%（顔で埋まった画像のみ）</span>
        </div>
      </div>

      {/* 見開き分割オプション */}
      <div className="space-y-1">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={spreadSplit}
            onChange={(e) => setSpreadSplit(e.target.checked)}
            disabled={disabled}
            className="w-4 h-4 text-blue-500 rounded border-gray-300 focus:ring-blue-500 disabled:cursor-not-allowed"
          />
          <span className="text-sm font-medium text-gray-700">見開き分割を実行</span>
        </label>
        <p className="text-xs text-gray-400 ml-6">
          見開き画像の中央ストライプを検出し、2つの顔が検出された場合に左右に分割します
        </p>
      </div>

      {/* 送信ボタン */}
      <button
        type="submit"
        disabled={!canSubmit}
        className="w-full py-2.5 px-4 text-sm font-medium text-white bg-blue-500 rounded-lg hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
      >
        スキャン開始
      </button>
    </form>
  )
}

export default SettingsForm
