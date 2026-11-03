<template>
  <div class="chat-bubble" :class="isUser ? 'user' : 'assistant'">
    <div class="avatar">{{ isUser ? '🙋' : '🩺' }}</div>
    <div class="body">
      <div class="bubble">
        <div v-if="isUser" class="plain">{{ message.content }}</div>
        <MarkdownRenderer v-else :content="message.content" />
      </div>
      <div class="time" v-if="tag">{{ tag }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownRenderer from './MarkdownRenderer.vue'
import type { MessageInfo } from '@/api'

const props = defineProps<{ message: MessageInfo }>()

const isUser = computed(() => props.message.role === 'user')

const tag = computed(() => {
  const meta = props.message.meta || {}
  if (!meta.answer_mode) return ''
  const map: Record<string, string> = {
    rag: '基于知识库',
    llm_direct: '通用医学知识',
    emergency: '急诊提示',
    chitchat: '寒暄',
    record_hint: '操作提示',
  }
  const base = map[meta.answer_mode] || meta.answer_mode
  const conf = typeof meta.confidence === 'number' && meta.answer_mode === 'rag'
    ? ` · 相似度 ${(meta.confidence * 100).toFixed(0)}%`
    : ''
  return base + conf
})
</script>
