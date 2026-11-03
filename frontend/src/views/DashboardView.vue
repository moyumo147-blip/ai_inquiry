<template>
  <div class="page">
    <h1 class="page-title">概览</h1>
    <p class="page-subtitle">基于真实医患病例的 AI 预问诊 · 分诊 / 问诊 / 病历</p>

    <el-row :gutter="16">
      <el-col :span="6" v-for="card in statCards" :key="card.label">
        <div class="card stat">
          <div class="stat-label">{{ card.label }}</div>
          <div class="stat-value">{{ card.value }}</div>
          <div class="stat-hint">{{ card.hint }}</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="15">
        <div class="card panel">
          <div class="panel-head">
            <span class="panel-title">最近问诊</span>
            <el-button text type="primary" @click="router.push('/consult')">去问诊 →</el-button>
          </div>
          <el-table :data="sessions" v-loading="loading" size="small" empty-text="还没有问诊记录">
            <el-table-column prop="title" label="主诉" min-width="220" show-overflow-tooltip />
            <el-table-column label="科室" width="120">
              <template #default="{ row }">{{ row.department || '—' }}</template>
            </el-table-column>
            <el-table-column label="紧急度" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="urgencyType(row.urgency)">{{ urgencyLabel(row.urgency) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="消息" width="80">
              <template #default="{ row }">{{ row.message_count }}</template>
            </el-table-column>
            <el-table-column label="更新时间" width="160">
              <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
            </el-table-column>
            <el-table-column width="90">
              <template #default="{ row }">
                <el-button link type="primary" @click="router.push(`/consult/${row.id}`)">打开</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>

      <el-col :span="9">
        <div class="card panel quick">
          <div class="panel-head"><span class="panel-title">快速开始</span></div>
          <el-button type="primary" size="large" class="quick-btn" @click="router.push('/consult')">
            <el-icon><ChatDotRound /></el-icon> 开始一次问诊
          </el-button>
          <el-button size="large" class="quick-btn" @click="router.push('/cases')">
            <el-icon><Search /></el-icon> 检索病例知识库
          </el-button>
          <el-button size="large" class="quick-btn" @click="router.push('/records')">
            <el-icon><Document /></el-icon> 查看我的病历
          </el-button>

          <el-divider />

          <div class="tips">
            <div class="tip">💡 描述症状时带上「年龄 + 时长 + 伴随症状」，分诊更准。</div>
            <div class="tip danger">⚠️ 胸痛、呼吸困难、意识不清请立即拨打 120，不要等待线上回复。</div>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { sessionApi, systemApi, type SessionInfo, type StatsInfo } from '@/api'

const router = useRouter()
const loading = ref(false)
const sessions = ref<SessionInfo[]>([])
const stats = ref<StatsInfo | null>(null)

const statCards = computed(() => [
  { label: '病例知识库', value: stats.value?.cases ?? '—', hint: `覆盖 ${stats.value?.departments ?? '—'} 个科室` },
  { label: '医患问答', value: stats.value?.qa_pairs ?? '—', hint: '用于相似问答参考' },
  { label: '我的问诊', value: stats.value?.sessions ?? '—', hint: '进行中与已完成会话' },
  { label: '我的病历', value: stats.value?.records ?? '—', hint: 'SOAP 结构化病历' },
])

function urgencyLabel(u: string) {
  return { emergency: '立即急诊', urgent: '24h 内', routine: '常规' }[u] || '常规'
}

function urgencyType(u: string): 'danger' | 'warning' | 'success' {
  return ({ emergency: 'danger', urgent: 'warning', routine: 'success' } as const)[u as 'routine'] || 'success'
}

function formatTime(t?: string) {
  if (!t) return '—'
  return new Date(t).toLocaleString('zh-CN', { hour12: false }).slice(5, 16)
}

onMounted(async () => {
  loading.value = true
  try {
    const [list, s] = await Promise.all([sessionApi.list(), systemApi.stats()])
    sessions.value = list.slice(0, 6)
    stats.value = s
  } catch {
    /* 静默 */
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.stat {
  padding: 18px 20px;
}

.stat-label {
  font-size: 13px;
  color: var(--ac-muted);
}

.stat-value {
  font-size: 30px;
  font-weight: 600;
  margin: 6px 0 2px;
  color: var(--ac-primary-dark);
}

.stat-hint {
  font-size: 12px;
  color: var(--ac-muted);
}

.panel {
  padding: 16px 18px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.panel-title {
  font-weight: 600;
}

.quick-btn {
  width: 100%;
  margin: 6px 0 0;
  justify-content: flex-start;
}

.tips {
  font-size: 12px;
  color: var(--ac-muted);
  line-height: 1.8;
}

.tip + .tip {
  margin-top: 8px;
}

.tip.danger {
  color: var(--ac-danger);
}
</style>
