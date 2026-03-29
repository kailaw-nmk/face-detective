import { useState } from 'react'
import type { CompleteMessage } from '../types'

/** ResultSummary コンポーネントの Props */
interface ResultSummaryProps {
  /** 処理完了メッセージ。未受信の場合は null */
  result: CompleteMessage | null
  /** 新しいスキャンを開始するためのリセットコールバック */
  onReset: () => void
}

/**
 * スキャン完了後の結果サマリーコンポーネント。
 * 処理件数・抽出件数・スキップ件数・エラー件数を表示し、
 * エラーがある場合はエラーファイル一覧を開閉できる。
 */
function ResultSummary({ result, onReset }: ResultSummaryProps) {
  const [isErrorListOpen, setIsErrorListOpen] = useState(false)

  const total = result?.total ?? 0
  const extracted = result?.extracted ?? 0
  const skipped = result?.skipped ?? 0
  const errors = result?.errors ?? 0
  const errorFiles = result?.error_files ?? []

  return (
    <div className="bg-white rounded-xl shadow-md p-6 space-y-5">

      {/* ヘッダー */}
      <div className="flex items-center gap-2">
        <div className="w-5 h-5 rounded-full bg-green-500 flex items-center justify-center flex-shrink-0">
          <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h2 className="text-base font-semibold text-gray-800">処理完了</h2>
      </div>

      {/* 統計グリッド */}
      <div className="grid grid-cols-2 gap-3">
        <ResultCard
          label="合計スキャン"
          value={total}
          unit="件"
          color="text-gray-800"
          bgColor="bg-gray-50"
        />
        <ResultCard
          label="抽出"
          value={extracted}
          unit="件"
          color="text-green-600"
          bgColor="bg-green-50"
        />
        <ResultCard
          label="スキップ"
          value={skipped}
          unit="件"
          color="text-yellow-600"
          bgColor="bg-yellow-50"
        />
        <ResultCard
          label="エラー"
          value={errors}
          unit="件"
          color={errors > 0 ? 'text-red-600' : 'text-gray-400'}
          bgColor={errors > 0 ? 'bg-red-50' : 'bg-gray-50'}
        />
      </div>

      {/* エラーファイル一覧（エラーがある場合のみ表示） */}
      {errors > 0 && (
        <div className="border border-red-200 rounded-lg overflow-hidden">
          <button
            type="button"
            onClick={() => setIsErrorListOpen((prev) => !prev)}
            className="w-full flex items-center justify-between px-4 py-3 bg-red-50 text-sm font-medium text-red-700 hover:bg-red-100 transition-colors"
          >
            <span>エラーファイル一覧（{errorFiles.length} 件）</span>
            <svg
              className={`w-4 h-4 transition-transform ${isErrorListOpen ? 'rotate-180' : ''}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {isErrorListOpen && (
            <ul className="max-h-48 overflow-y-auto divide-y divide-red-100">
              {errorFiles.length > 0 ? (
                errorFiles.map((filePath, index) => (
                  <li
                    key={index}
                    className="px-4 py-2 text-xs font-mono text-gray-600 bg-white hover:bg-red-50"
                  >
                    {filePath}
                  </li>
                ))
              ) : (
                <li className="px-4 py-2 text-sm text-gray-500 bg-white">
                  詳細情報はありません
                </li>
              )}
            </ul>
          )}
        </div>
      )}

      {/* リセットボタン */}
      <button
        type="button"
        onClick={onReset}
        className="w-full py-2.5 px-4 text-sm font-medium text-white bg-blue-500 rounded-lg hover:bg-blue-600 transition-colors"
      >
        新しいスキャンを開始
      </button>
    </div>
  )
}

/** ResultCard コンポーネントの Props */
interface ResultCardProps {
  label: string
  value: number
  unit: string
  color: string
  bgColor: string
}

/**
 * 結果統計を表示するカードコンポーネント
 */
function ResultCard({ label, value, unit, color, bgColor }: ResultCardProps) {
  return (
    <div className={`${bgColor} rounded-lg p-4 text-center`}>
      <p className={`text-2xl font-bold ${color}`}>
        {value}
        <span className="text-sm font-normal ml-1">{unit}</span>
      </p>
      <p className="text-xs text-gray-500 mt-1">{label}</p>
    </div>
  )
}

export default ResultSummary
