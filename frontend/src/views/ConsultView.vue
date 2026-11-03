<template>
  <div class="consult">
    <!-- 会话列表 -->
    <aside class="sessions card">
      <el-button type="primary" class="new-btn" @click="openNew">
        <el-icon><Plus /></el-icon>
        新建问诊
      </el-button>

      <div class="session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === currentId }"
          @click="openSession(s.id)"
        >
          <div class="stitle">{{ s.title || '新问诊' }}</div>
          <div class="smeta">
            <el-tag size="small" :type="urgencyType(s.urgency)" effect="plain">
              {{ urgencyLabel(s.urgency) }}
            </el-tag>
            <span>{{ formatTime(s.updated_at) }}</span>
          </div>
        </div>
        <el-empty v-if="!sessions.length" description="暂无问诊记录" :image-size="54" />
      </div>
    </aside>

    <!-- 对话区 -->
    <section class="chat">
      <template v-if="currentId">
        <div class="chat-head card">
          <div class="chat-title">
            <span class="ct-text">{{ currentSession?.title || '问诊' }}</span>
            <el-tag v-if="triage?.department" size="small" effect="plain">{{ triage.department }}</el-tag>
          </div>
          <el-button size="small" :loading="recordLoading" @click="generateRecord">
            <el-icon><Document /></el-icon>
            生成病历
          </el-button>
        </div>

        <div class="messages" ref="msgBox">
          <ChatBubble v-for="m in messages" :key="m.id" :message="m" />

          <div v-if="streaming || streamText" class="chat-bubble assistant">
            <div class="avatar">🩺</div>
            <div class="body">
              <div class="bubble">
                <MarkdownRenderer v-if="streamText" :content="streamText" />
                <span v-else class="thinking">{{ stage || '思考中…' }}</span>
              </div>
            </div>
          </div>

          <div v-if="followups.length && !streaming" class="followups">
            <div class="fu-title">想判断更准确？补充这些信息：</div>
            <div class="fu-list">
              <el-tag
                v-for="(q, i) in followups"
                :key="i"
                class="fu-item"
                effect="plain"
                @click="quickAsk(q)"
              >
                {{ q }}
              </el-tag>
            </div>
          </div>
        </div>

        <div class="composer card">
          <el-input
            v-model="input"
            type="textarea"
            :rows="2"
            resize="none"
            maxlength="2000"
            placeholder="描述症状或继续追问；Enter 发送，Shift+Enter 换行"
            @keydown.enter.exact.prevent="send"
          />
          <div class="composer-foot">
            <span class="muted small">
              {{ streaming ? stage || '生成中…' : 'AI 生成内容仅供参考，不能替代医生面诊' }}
            </span>
            <el-button type="primary" :loading="streaming" :disabled="!input.trim()" @click="send">
              发送
            </el-button>
          </div>
        </div>
      </template>

      <div v-else class="empty-welcome">
        <div class="ew-icon">🩺</div>
        <h2>开始一次新的问诊</h2>
        <p class="muted">描述主要不适，系统会先做分诊，再基于真实病例知识库回答并给出就医方向</p>
        <el-input
          v-model="complaint"
          type="textarea"
          :rows="3"
          class="ew-input"
          placeholder="例如：孩子 8 岁，上课坐不住、注意力不集中，写作业拖拉，怀疑多动症"
        />
        <el-button type="primary" size="large" :loading="creating" @click="startNew">开始问诊</el-button>
      </div>
    </section>

    <!-- 右侧信息栏 -->
    <aside class="info">
      <TriageCard :triage="triage" />
      <CitationList :citations="citations" />
    </aside>

    <!-- 病历预览 -->
    <el-dialog v-model="recordDialog" title="本次问诊 · SOAP 病历" width="760px" top="6vh">
      <div v-if="record" class="record">
        <div class="rrow"><span class="rlabel">主诉</span><span>{{ record.chief_complaint }}</span></div>
        <div class="rrow"><span class="rlabel">现病史</span><span>{{ record.present_illness }}</span></div>
        <div class="rrow"><span class="rlabel">既往史</span><span>{{ record.past_history }}</span></div>
        <div class="rrow"><span class="rlabel">过敏史</span><span>{{ record.allergy_history }}</span></div>
        <div class="rrow"><span class="rlabel">体格检查</span><span>{{ record.physical_exam }}</span></div>
        <div class="rrow"><span class="rlabel">初步评估</span><span>{{ record.assessment }}</span></div>
        <div class="rrow"><span class="rlabel">初步诊断</span><span>{{ record.diagnosis }}</span></div>
        <div class="rrow"><span class="rlabel">诊疗计划</span><span>{{ record.plan }}</span></div>
        <p class="muted small">已保存为草稿，可在「我的病历」中继续编辑。</p>
      </div>
      <template #footer>
        <el-button @click="recordDialog = false">关闭</el-button>
        <el-button type="primary" @click="gotoRecords">去病历页编辑</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import CitationList from '@/components/chat/CitationList.vue'
import ChatBubble from '@/components/chat/ChatBubble.vue'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import TriageCard from '@/components/chat/TriageCard.vue'
import {
  recordApi,
  sessionApi,
  type Citation,
  type MessageInfo,
  type RecordInfo,
  type SessionInfo,
  type TriageInfo,
} from '@/api'
import { apiError } from '@/api/client'
import { useSSEChat } from '@/composables/useSSEChat'

const route = useRoute()
const router = useRouter()

const sessions = ref<SessionInfo[]>([])
const currentId = ref('')
const messages = ref<MessageInfo[]>([])
const triage = ref<TriageInfo | null>(null)
const citations = ref<Citation[]>([])
const followups = ref<string[]>([])
const input = ref('')
const complaint = ref('')
const stage = ref('')
const streamText = ref('')
const creating = ref(false)
const recordLoading = ref(false)
const recordDialog = ref(false)
const record = ref<RecordInfo | null>(null)
const msgBox = ref<HTMLElement | null>(null)

const { streaming, send: sendSSE } = useSSEChat()

const currentSession = computed(() => sessions.value.find((s) => s.id === currentId.value) || null)

function urgencyLabel(u: string) {
  return { emergency: '立即急诊', urgent: '24h 内', routine: '常规' }[u] || '常规'
}

function urgencyType(u: string): 'danger' | 'warning' | 'success' {
  const map = { emergency: 'danger', urgent: 'warning', routine: 'success' } as const
  return map[(u as keyof typeof map) || 'routine'] || 'success'
}

function formatTime(t?: string) {
  if (!t) return ''
  return new Date(t).toLocaleString('zh-CN', { hour12: false }).slice(5, 16)
}

async function scrollToBottom() {
  await nextTick()
  if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
}

async function loadSessions() {
  try {
    sessions.value = await sessionApi.list()
  } catch {
    sessions.value = []
  }
}

async function openSession(id: string) {
  if (!id) return
  currentId.value = id
  stage.value = ''
  streamText.value = ''
  followups.value = []
  try {
    const detail = await sessionApi.detail(id)
    messages.value = detail.messages
    triage.value = detail.triage
    const lastWithCitations = [...detail.messages]
      .reverse()
      .find((m) => m.role === 'assistant' && (m.meta?.citations || []).length)
    citations.value = (lastWithCitations?.meta?.citations || []) as Citation[]
    if (String(route.params.id || '') !== id) {
      router.replace(`/consult/${id}`)
    }
    await scrollToBottom()
  } catch (e) {
    ElMessage.error(apiError(e))
  }
}

function openNew() {
  currentId.value = ''
  messages.value = []
  triage.value = null
  citations.value = []
  followups.value = []
  router.replace('/consult')
}

async function startNew() {
  const text = complaint.value.trim()
  if (!text) {
    ElMessage.warning('请先描述主要不适')
    return
  }
  creating.value = true
  try {
    const res = await sessionApi.create({ chief_complaint: text })
    complaint.value = ''
    sessions.value.unshift(res.session)
    await openSession(res.session.id)
  } catch (e) {
    ElMessage.error(apiError(e))
  } finally {
    creating.value = false
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value || !currentId.value) return

  input.value = ''
  followups.value = []
  messages.value.push({ id: Date.now(), role: 'user', content: text })
  streamText.value = ''
  stage.value = ''
  await scrollToBottom()

  await sendSSE(
    { session_id: currentId.value, message: text },
    {
      onProgress: (s) => {
        stage.value = s
      },
      onToken: (t) => {
        streamText.value += t
        scrollToBottom()
      },
      onMeta: (m) => {
        citations.value = (m.citations || []) as Citation[]
        followups.value = m.followups || []
        if (m.urgency && triage.value) triage.value.urgency = m.urgency
      },
      onError: (msg) => ElMessage.error(msg || '生成失败，请重试'),
    },
  )

  const answer = streamText.value
  streamText.value = ''
  stage.value = ''

  if (answer.trim()) {
    // 以服务端为准刷新（含 meta、引用）
    const list = await sessionApi.messages(currentId.value).catch(() => null)
    if (list) messages.value = list
  }
  await loadSessions()
  await scrollToBottom()
}

function quickAsk(question: string) {
  input.value = question
  send()
}

async function generateRecord() {
  recordLoading.value = true
  try {
    record.value = await recordApi.generate(currentId.value)
    recordDialog.value = true
    await loadSessions()
  } catch (e) {
    ElMessage.error(apiError(e))
  } finally {
    recordLoading.value = false
  }
}

function gotoRecords() {
  recordDialog.value = false
  router.push('/records')
}

onMounted(async () => {
  await loadSessions()
  const id = String(route.params.id || '')
  if (id) {
    await openSession(id)
  } else if (sessions.value.length) {
    await openSession(sessions.value[0].id)
  }
})

watch(
  () => route.params.id,
  (id) => {
    if (id && String(id) !== currentId.value) openSession(String(id))
  },
)
</script>

<style scoped>
.consult {
  display: flex;
  height: calc(100vh - 56px);
  gap: 12px;
  padding: 12px;
}

.sessions {
  width: 240px;
  flex: 0 0 240px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.new-btn {
  width: 100%;
  margin-bottom: 8px;
}

.session-list {
  flex: 1;
  overflow-y: auto;
}

.session-item {
  padding: 10px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
  border: 1px solid transparent;
}

.session-item:hover {
  background: #f6f9f8;
}

.session-item.active {
  background: #e8f5f1;
  border-color: #bfe3d8;
}

.stitle {
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.smeta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
  font-size: 11px;
  color: var(--ac-muted);
}

.chat {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
}

.chat-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.ct-text {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 18px;
  background: #fff;
  border-radius: var(--ac-radius);
  border: 1px solid var(--ac-border);
}

.thinking {
  color: var(--ac-muted);
}

.followups {
  margin: 4px 0 8px 44px;
}

.fu-title {
  font-size: 12px;
  color: var(--ac-muted);
  margin-bottom: 6px;
}

.fu-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.fu-item {
  cursor: pointer;
}

.composer {
  padding: 10px 12px;
}

.composer :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none;
  padding: 6px 2px;
}

.composer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
}

.small {
  font-size: 12px;
}

.empty-welcome {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: #fff;
  border-radius: var(--ac-radius);
  border: 1px solid var(--ac-border);
  padding: 32px;
}

.ew-icon {
  font-size: 46px;
  margin-bottom: 8px;
}

.empty-welcome h2 {
  margin: 0 0 6px;
  font-size: 20px;
}

.ew-input {
  max-width: 560px;
  margin: 18px 0 14px;
}

.info {
  width: 300px;
  flex: 0 0 300px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.record .rrow {
  display: flex;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--ac-border);
  font-size: 13px;
  line-height: 1.7;
}

.rlabel {
  flex: 0 0 76px;
  color: var(--ac-muted);
}

@media (max-width: 1280px) {
  .info {
    display: none;
  }
}
</style>
