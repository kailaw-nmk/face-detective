import { useState, useEffect, useRef } from 'react'
import type { WSMessage } from '../types'

/** useWebSocket フックの戻り値 */
interface UseWebSocketResult {
  /** 最後に受信したメッセージ */
  lastMessage: WSMessage | null
  /** WebSocket 接続状態 */
  isConnected: boolean
}

/**
 * WebSocket 接続を管理するカスタムフック。
 * jobId が指定されると自動的に接続し、変更または unmount 時にクリーンアップする。
 *
 * @param jobId - 接続先ジョブ ID。null の場合は接続しない
 * @returns lastMessage と isConnected を含むオブジェクト
 */
export function useWebSocket(jobId: string | null): UseWebSocketResult {
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    // jobId がなければ接続しない
    if (!jobId) {
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws/${jobId}`

    let ws: WebSocket

    try {
      ws = new WebSocket(url)
      wsRef.current = ws
    } catch (err) {
      console.error('WebSocket 接続の作成に失敗しました:', err)
      return
    }

    ws.onopen = () => {
      setIsConnected(true)
    }

    ws.onmessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data as string) as WSMessage
        setLastMessage(data)
      } catch (err) {
        console.error('WebSocket メッセージのパースに失敗しました:', err)
      }
    }

    ws.onerror = (event: Event) => {
      console.error('WebSocket エラーが発生しました:', event)
      setIsConnected(false)
    }

    ws.onclose = () => {
      setIsConnected(false)
      wsRef.current = null
    }

    return () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close()
      }
      wsRef.current = null
      setIsConnected(false)
    }
  }, [jobId])

  return { lastMessage, isConnected }
}
