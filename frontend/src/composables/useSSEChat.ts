import { ref } from 'vue'

import type { ChatResult } from '@/api'

export interface SSEMeta extends Omit<ChatResult, 'answer'> {
  answer?: string
}

interface Handlers {
  onToken?: (text: string) => void
  onProgress?: (stage: string) => void
  onMeta?: (meta: SSEMeta) => void
  onDone?: () => void
  onError?: (message: string) => void
}

/**
 * 问诊 SSE：直接读 fetch 的 ReadableStream（EventSource 不支持 POST + Bearer）。
 * 后端事件：progress / token / meta / done / error，均为 `data: {json}`。
 */
export function useSSEChat() {
  const streaming = ref(false)
  let controller: AbortController | null = null

  async function send(
    payload: { session_id: string; message: string; department?: string; enable_retrieval?: boolean },
    handlers: Handlers = {},
  ) {
    controller?.abort()
    controller = new AbortController()
    streaming.value = true

    try {
      const resp = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('ac_token') || ''}`,
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      })

      if (!resp.ok || !resp.body) {
        const text = await resp.text().catch(() => '')
        throw new Error(text || `HTTP ${resp.status}`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const blocks = buffer.split(/\r?\n\r?\n/)
        buffer = blocks.pop() ?? ''

        for (const block of blocks) {
          const dataLine = block.split(/\r?\n/).find((line) => line.startsWith('data:'))
          if (!dataLine) continue
          const raw = dataLine.slice(5).trim()
          if (!raw) continue

          let event: any
          try {
            event = JSON.parse(raw)
          } catch {
            continue
          }

          switch (event.type) {
            case 'token':
              handlers.onToken?.(event.content ?? '')
              break
            case 'progress':
              handlers.onProgress?.(event.stage ?? '')
              break
            case 'meta':
              handlers.onMeta?.(event)
              break
            case 'done':
              handlers.onDone?.()
              break
            case 'error':
              handlers.onError?.(event.message || '流式输出异常')
              break
          }
        }
      }
    } catch (error: any) {
      if (error?.name !== 'AbortError') {
        handlers.onError?.(error?.message || '网络异常')
      }
    } finally {
      streaming.value = false
    }
  }

  function abort() {
    controller?.abort()
    streaming.value = false
  }

  return { streaming, send, abort }
}
