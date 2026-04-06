import type { ProgressMessage } from '../types'

/** ProgressPanel コンポーネントの Props */
interface ProgressPanelProps {
  /** 最新の進捗メッセージ。スキャン開始直後は null */
  progress: ProgressMessage | null
}

/**
 * スキャン進捗を表示するパネルコンポーネント。
 * プログレスバー、現在処理中ファイル名、各種カウンターを表示する。
 */
function ProgressPanel({ progress }: ProgressPanelProps) {
  const processed = progress?.processed ?? 0
  const total = progress?.total ?? 0
  const percentage = total > 0 ? Math.round((processed / total) * 100) : 0

  /** ファイルパスが長い場合に先頭を省略して表示する */
  const truncateFilePath = (path: string, maxLength = 60): string => {
    if (path.length <= maxLength) return path
    return '...' + path.slice(-(maxLength - 3))
  }

  return (
    <div className="bg-white rounded-xl shadow-md p-6 space-y-5">

      {/* ヘッダー */}
      <div className="flex items-center gap-2">
        <div className="w-3 h-3 rounded-full bg-blue-500 animate-pulse" />
        <h2 className="text-base font-semibold text-gray-800">スキャン中...</h2>
      </div>

      {/* プログレスバー */}
      <div className="space-y-1.5">
        <div className="flex justify-between text-sm text-gray-600">
          <span>{processed} / {total} ファイル</span>
          <span className="font-medium text-blue-600">{percentage}%</span>
        </div>
        <div className="w-full h-3 bg-gray-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-300 ease-out"
            style={{ width: `${percentage}%` }}
          />
        </div>
      </div>

      {/* 現在処理中ファイル */}
      <div className="space-y-1">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">現在処理中</p>
        <p className="text-sm text-gray-700 font-mono bg-gray-50 rounded px-3 py-2 truncate">
          {progress?.current_file
            ? truncateFilePath(progress.current_file)
            : '待機中...'}
        </p>
      </div>

      {/* 統計グリッド */}
      {(progress?.split_count ?? 0) > 0 ? (
        <div className="grid grid-cols-5 gap-3">
          <StatCard label="スキャン済み" value={progress?.processed ?? 0} color="text-gray-800" />
          <StatCard label="分割" value={progress?.split_count ?? 0} color="text-purple-600" />
          <StatCard label="抽出" value={progress?.extracted ?? 0} color="text-green-600" />
          <StatCard label="スキップ" value={progress?.skipped ?? 0} color="text-yellow-600" />
          <StatCard label="エラー" value={progress?.errors ?? 0} color="text-red-600" />
        </div>
      ) : (
        <div className="grid grid-cols-4 gap-3">
          <StatCard label="スキャン済み" value={progress?.processed ?? 0} color="text-gray-800" />
          <StatCard label="抽出" value={progress?.extracted ?? 0} color="text-green-600" />
          <StatCard label="スキップ" value={progress?.skipped ?? 0} color="text-yellow-600" />
          <StatCard label="エラー" value={progress?.errors ?? 0} color="text-red-600" />
        </div>
      )}
    </div>
  )
}

/** 統計カードの Props */
interface StatCardProps {
  label: string
  value: number
  color: string
}

/**
 * 統計値を表示する小カードコンポーネント
 */
function StatCard({ label, value, color }: StatCardProps) {
  return (
    <div className="bg-gray-50 rounded-lg p-3 text-center">
      <p className={`text-xl font-bold ${color}`}>{value}</p>
      <p className="text-xs text-gray-500 mt-0.5">{label}</p>
    </div>
  )
}

export default ProgressPanel
