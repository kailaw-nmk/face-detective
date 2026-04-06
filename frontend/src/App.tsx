import { useState, useEffect } from 'react'
import type { AppState, ProgressMessage, CompleteMessage, StartResponse } from './types'
import { useWebSocket } from './hooks/useWebSocket'
import SettingsForm from './components/SettingsForm'
import ProgressPanel from './components/ProgressPanel'
import ResultSummary from './components/ResultSummary'

/**
 * アプリケーションのルートコンポーネント。
 * 状態管理・WebSocket メッセージ処理・API 呼び出しを担当する。
 */
function App() {
  const [appState, setAppState] = useState<AppState>('idle')
  const [jobId, setJobId] = useState<string | null>(null)
  const [progress, setProgress] = useState<ProgressMessage | null>(null)
  const [result, setResult] = useState<CompleteMessage | null>(null)
  const [stopError, setStopError] = useState<string | null>(null)

  const { lastMessage } = useWebSocket(jobId)

  // WebSocket メッセージを受信したときに状態を更新する
  useEffect(() => {
    if (!lastMessage) return

    if (lastMessage.type === 'progress') {
      setProgress(lastMessage)
    } else if (lastMessage.type === 'complete') {
      setResult(lastMessage)
      setAppState('complete')
      setJobId(null)
    } else if (lastMessage.type === 'error') {
      console.error('サーバーエラー:', lastMessage.message)
      // エラーが来ても complete に遷移してメッセージを表示する
      setResult({
        type: 'complete',
        total: progress?.processed ?? 0,
        extracted: progress?.extracted ?? 0,
        skipped: progress?.skipped ?? 0,
        errors: (progress?.errors ?? 0) + 1,
        error_files: [lastMessage.message],
      })
      setAppState('complete')
      setJobId(null)
    }
  }, [lastMessage, progress])

  /**
   * スキャンを開始する。
   * POST /api/start を呼び出し、取得した job_id で WebSocket 接続を開始する。
   */
  const handleStart = async (
    source: string,
    threshold: number,
    spreadSplit: boolean,
    requireBothEyes: boolean,
    advanced: { minEyeRatio: number; minFaceScore: number; yoloConfidence: number },
  ) => {
    setStopError(null)
    setProgress(null)
    setResult(null)

    try {
      const response = await fetch('/api/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_folder: source,
          threshold,
          spread_split: spreadSplit,
          require_both_eyes: requireBothEyes,
          min_eye_ratio: advanced.minEyeRatio,
          min_face_score: advanced.minFaceScore,
          yolo_confidence: advanced.yoloConfidence,
        }),
      })

      if (!response.ok) {
        const text = await response.text()
        console.error('スキャン開始エラー:', text)
        return
      }

      const data: StartResponse = await response.json() as StartResponse
      setJobId(data.job_id)
      setAppState('scanning')
    } catch (err) {
      console.error('スキャン開始リクエストに失敗しました:', err)
    }
  }

  /**
   * スキャンを中止する。
   * POST /api/stop を呼び出し、バックエンドの処理を停止させる。
   */
  const handleStop = async () => {
    if (!jobId) return

    try {
      const response = await fetch('/api/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId }),
      })

      if (!response.ok) {
        setStopError('中止リクエストに失敗しました')
        return
      }

      setAppState('idle')
      setJobId(null)
      setProgress(null)
    } catch (err) {
      console.error('中止リクエストに失敗しました:', err)
      setStopError('中止リクエストに失敗しました')
    }
  }

  /** アプリケーション状態をリセットして初期画面に戻る */
  const handleReset = () => {
    setAppState('idle')
    setJobId(null)
    setProgress(null)
    setResult(null)
    setStopError(null)
  }

  return (
    <div className="min-h-screen bg-gray-100 py-10 px-4">
      <div className="max-w-2xl mx-auto space-y-6">

        {/* ヘッダー */}
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-bold text-gray-900">Face Image Extractor</h1>
          <p className="text-sm text-gray-500">顔画像抽出ツール</p>
        </div>

        {/* メインコンテンツ（状態に応じて切り替え） */}
        {appState === 'idle' && (
          <SettingsForm onStart={handleStart} disabled={false} />
        )}

        {appState === 'scanning' && (
          <>
            <ProgressPanel progress={progress} />

            {/* 中止ボタン */}
            <div className="text-center">
              {stopError && (
                <p className="text-sm text-red-600 mb-2">{stopError}</p>
              )}
              <button
                type="button"
                onClick={handleStop}
                className="px-6 py-2 text-sm font-medium text-white bg-red-500 rounded-lg hover:bg-red-600 transition-colors"
              >
                中止
              </button>
            </div>
          </>
        )}

        {appState === 'complete' && (
          <ResultSummary result={result} onReset={handleReset} />
        )}

      </div>
    </div>
  )
}

export default App
