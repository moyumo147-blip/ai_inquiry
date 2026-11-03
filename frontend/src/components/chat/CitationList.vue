<template>
  <div class="citations card" v-if="citations.length">
    <div class="head">
      <span class="title">参考病例 {{ citations.length }}</span>
      <span class="muted small">真实病例</span>
    </div>
    <div v-for="c in citations" :key="c.case_id" class="item">
      <div class="row">
        <el-tag size="small" effect="plain">{{ c.department || '未知科室' }}</el-tag>
        <span class="hospital">{{ c.hospital || '未收录医院' }}</span>
        <span class="sim" v-if="c.similarity">{{ (c.similarity * 100).toFixed(0) }}%</span>
      </div>
      <div class="disease">{{ c.disease }}</div>
      <div class="snippet">{{ c.snippet }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Citation } from '@/api'

defineProps<{ citations: Citation[] }>()
</script>

<style scoped>
.citations {
  padding: 12px 14px;
}

.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 8px;
}

.title {
  font-weight: 600;
}

.small {
  font-size: 12px;
}

.item {
  padding: 8px 0;
  border-top: 1px dashed var(--ac-border);
}

.item:first-of-type {
  border-top: none;
}

.row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.hospital {
  font-size: 12px;
  color: var(--ac-muted);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sim {
  font-size: 12px;
  color: var(--ac-primary);
}

.disease {
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 2px;
}

.snippet {
  font-size: 12px;
  color: var(--ac-muted);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
