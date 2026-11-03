<template>
  <div class="triage-card card" v-if="triage">
    <div class="head">
      <span class="title">分诊结果</span>
      <el-tag :type="urgencyType" effect="dark" size="small">{{ urgencyLabel }}</el-tag>
    </div>

    <div class="dept">
      <el-icon><OfficeBuilding /></el-icon>
      <span>{{ triage.department || '全科医学科' }}</span>
    </div>

    <div v-if="triage.red_flags?.length" class="block">
      <div class="label">⚠️ 需要留意</div>
      <div class="tags">
        <el-tag v-for="flag in triage.red_flags" :key="flag" type="danger" effect="plain" size="small">
          {{ flag }}
        </el-tag>
      </div>
    </div>

    <div v-if="triage.advice" class="block">
      <div class="label">下一步</div>
      <div class="text">{{ triage.advice }}</div>
    </div>

    <div v-if="triage.questions?.length" class="block">
      <div class="label">还需要了解</div>
      <ul class="questions">
        <li v-for="q in triage.questions" :key="q">{{ q }}</li>
      </ul>
    </div>

    <div v-if="triage.recommended_tests?.length" class="block">
      <div class="label">建议检查</div>
      <div class="tags">
        <el-tag v-for="t in triage.recommended_tests" :key="t" size="small" effect="plain">{{ t }}</el-tag>
      </div>
    </div>
  </div>

  <div v-else class="triage-card card empty">
    <el-icon><FirstAidKit /></el-icon>
    <p>还没有分诊结果</p>
    <p class="muted small">在左侧新建问诊时填写主诉，系统会自动分诊</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TriageInfo } from '@/api'

const props = defineProps<{ triage: TriageInfo | null }>()

const URGENCY: Record<string, { label: string; type: 'danger' | 'warning' | 'success' }> = {
  emergency: { label: '立即急诊', type: 'danger' },
  urgent: { label: '24h 内就诊', type: 'warning' },
  routine: { label: '常规门诊', type: 'success' },
}

const urgencyLabel = computed(() => URGENCY[props.triage?.urgency || 'routine']?.label ?? '常规门诊')
const urgencyType = computed(() => URGENCY[props.triage?.urgency || 'routine']?.type ?? 'success')
</script>

<style scoped>
.triage-card {
  padding: 14px 16px;
  font-size: 13px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.title {
  font-weight: 600;
}

.dept {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 15px;
  font-weight: 600;
  color: var(--ac-primary-dark);
  margin-bottom: 10px;
}

.block {
  margin-bottom: 10px;
}

.label {
  color: var(--ac-muted);
  font-size: 12px;
  margin-bottom: 4px;
}

.text {
  line-height: 1.6;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.questions {
  margin: 0;
  padding-left: 18px;
  line-height: 1.7;
}

.empty {
  text-align: center;
  color: var(--ac-muted);
  padding: 28px 16px;
}

.empty .el-icon {
  font-size: 26px;
  margin-bottom: 6px;
}

.small {
  font-size: 12px;
}
</style>
