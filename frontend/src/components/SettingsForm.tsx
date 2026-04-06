import { useState } from 'react'
import type { ValidatePathResponse } from '../types'

/** 詳細設定のパラメータ */
interface AdvancedSettings {
  minEyeRatio: number
  minFaceScore: number
  yoloConfidence: number
}

/** SettingsForm コンポーネントの Props */
interface SettingsFormProps {
  /** スキャン開始時のコールバック */
  onStart: (
    source: string,
    threshold: number,
    spreadSplit: boolean,
    requireBothEyes: boolean,
    advanced: AdvancedSettings,
  ) => void
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
  const [requireBothEyes, setRequireBothEyes] = useState(() => {
    return localStorage.getItem('face-detective-requireBothEyes') === 'true'
  })
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [minEyeRatio, setMinEyeRatio] = useState(() => {
    const saved = localStorage.getItem('face-detective-minEyeRatio')
    const parsed = saved !== null ? Number(saved) : NaN
    return Number.isFinite(parsed) ? parsed : 25
  })
  const [minFaceScore, setMinFaceScore] = useState(() => {
    const saved = localStorage.getItem('face-detective-minFaceScore')
    const parsed = saved !== null ? Number(saved) : NaN
    return Number.isFinite(parsed) ? parsed : 50
  })
  const [yoloConfidence, setYoloConfidence] = useState(() => {
    const saved = localStorage.getItem('face-detective-yoloConfidence')
    const parsed = saved !== null ? Number(saved) : NaN
    return Number.isFinite(parsed) ? parsed : 20
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
    localStorage.setItem('face-detective-requireBothEyes', String(requireBothEyes))
    localStorage.setItem('face-detective-minEyeRatio', String(minEyeRatio))
    localStorage.setItem('face-detective-minFaceScore', String(minFaceScore))
    localStorage.setItem('face-detective-yoloConfidence', String(yoloConfidence))

    onStart(sourcePath.trim(), threshold, spreadSplit, requireBothEyes, {
      minEyeRatio: minEyeRatio / 100,
      minFaceScore: minFaceScore / 100,
      yoloConfidence: yoloConfidence / 100,
    })
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
          見開き画像の中央ストライプを検出し、2人の人物が検出された場合に左右に分割します
        </p>
      </div>

      {/* 両目フィルタオプション */}
      <div className="space-y-1">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={requireBothEyes}
            onChange={(e) => setRequireBothEyes(e.target.checked)}
            disabled={disabled}
            className="w-4 h-4 text-blue-500 rounded border-gray-300 focus:ring-blue-500 disabled:cursor-not-allowed"
          />
          <span className="text-sm font-medium text-gray-700">両目が映っている画像のみ抽出</span>
        </label>
        <p className="text-xs text-gray-400 ml-6">
          横顔や後ろ向きなど、両目が確認できない画像をスキップします
        </p>
      </div>

      {/* 詳細設定トグル */}
      <div>
        <button
          type="button"
          onClick={() => setShowAdvanced((prev) => !prev)}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 transition-colors"
        >
          <svg
            className={`w-4 h-4 transition-transform ${showAdvanced ? 'rotate-90' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
          詳細設定
        </button>

        {showAdvanced && (
          <div className="mt-3 space-y-4 pl-2 border-l-2 border-gray-200">

            {/* 顔検出信頼度 */}
            <div className="space-y-1">
              <div className="flex justify-between items-center">
                <label className="text-xs font-medium text-gray-600">顔検出信頼度</label>
                <span className="text-xs font-semibold text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded">
                  {minFaceScore}%
                </span>
              </div>
              <input
                type="range"
                min={10}
                max={90}
                value={minFaceScore}
                onChange={(e) => setMinFaceScore(Number(e.target.value))}
                disabled={disabled}
                className="w-full h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-gray-500 disabled:cursor-not-allowed"
              />
              <div className="flex justify-between text-xs text-gray-400">
                <span>10%（緩い）</span>
                <span>90%（厳しい）</span>
              </div>
            </div>

            {/* 両目間距離比率 */}
            <div className="space-y-1">
              <div className="flex justify-between items-center">
                <label className="text-xs font-medium text-gray-600">両目間距離比率</label>
                <span className="text-xs font-semibold text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded">
                  {minEyeRatio}%
                </span>
              </div>
              <input
                type="range"
                min={5}
                max={50}
                value={minEyeRatio}
                onChange={(e) => setMinEyeRatio(Number(e.target.value))}
                disabled={disabled}
                className="w-full h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-gray-500 disabled:cursor-not-allowed"
              />
              <div className="flex justify-between text-xs text-gray-400">
                <span>5%（横顔も許容）</span>
                <span>50%（正面のみ）</span>
              </div>
            </div>

            {/* YOLO検出信頼度 */}
            <div className="space-y-1">
              <div className="flex justify-between items-center">
                <label className="text-xs font-medium text-gray-600">人物検出信頼度（YOLO）</label>
                <span className="text-xs font-semibold text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded">
                  {yoloConfidence}%
                </span>
              </div>
              <input
                type="range"
                min={5}
                max={80}
                value={yoloConfidence}
                onChange={(e) => setYoloConfidence(Number(e.target.value))}
                disabled={disabled}
                className="w-full h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-gray-500 disabled:cursor-not-allowed"
              />
              <div className="flex justify-between text-xs text-gray-400">
                <span>5%（検出漏れ少）</span>
                <span>80%（誤検出少）</span>
              </div>
            </div>
          </div>
        )}
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
