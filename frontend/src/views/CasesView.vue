<template>
  <div class="page">
    <h1 class="page-title">病例知识库</h1>
    <p class="page-subtitle">
      54,118 条真实医患问答病例（只读）· 支持关键词检索与向量语义检索
    </p>

    <div class="card panel">
      <el-tabs v-model="mode">
        <el-tab-pane label="关键词检索" name="keyword">
          <div class="filters">
            <el-input
              v-model="keyword"
              placeholder="疾病 / 症状 / 医院"
              clearable
              style="width: 280px"
              @keyup.enter="search(1)"
            />
            <el-select
              v-model="department"
              placeholder="全部科室"
              clearable
              filterable
              style="width: 200px"
            >
              <el-option
                v-for="d in departments"
                :key="d.department"
                :label="`${d.department}（${d.count}）`"
                :value="d.department"
              />
            </el-select>
            <el-button type="primary" :loading="loading" @click="search(1)">检索</el-button>
            <span class="muted small">共 {{ total }} 条</span>
          </div>

          <el-table :data="items" v-loading="loading" size="small" empty-text="没有匹配的病例">
            <el-table-column prop="disease" label="疾病" width="180" show-overflow-tooltip />
            <el-table-column prop="department" label="科室" width="130" />
            <el-table-column prop="hospital" label="医院" width="200" show-overflow-tooltip />
            <el-table-column prop="snippet" label="病情摘要" min-width="300" show-overflow-tooltip />
            <el-table-column width="90">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row.case_id)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-if="total > pageSize"
            class="pager"
            layout="prev, pager, next"
            :total="total"
            :page-size="pageSize"
            :current-page="page"
            @current-change="search"
          />
        </el-tab-pane>

        <el-tab-pane label="语义检索（向量）" name="semantic">
          <div class="filters">
            <el-input
              v-model="semanticQuery"
              placeholder="用一句话描述，例如：孩子注意力不集中、写作业拖拉"
              style="width: 460px"
              @keyup.enter="runSemantic"
            />
            <el-button type="primary" :loading="semanticLoading" @click="runSemantic">语义检索</el-button>
          </div>

          <div v-if="semanticMeta" class="muted small meta">
            最高相似度 {{ (semanticMeta.confidence * 100).toFixed(1) }}% · 覆盖度 {{ semanticMeta.coverage }}
          </div>

          <div v-for="c in semanticCases" :key="c.case_id" class="case-card" @click="openDetail(c.case_id)">
            <div class="cc-head">
              <el-tag size="small" effect="plain">{{ c.department || '未知科室' }}</el-tag>
              <span class="cc-disease">{{ c.disease }}</span>
              <span class="cc-sim">{{ (c.similarity * 100).toFixed(1) }}%</span>
            </div>
            <div class="cc-body">{{ c.snippet }}</div>
            <div class="cc-foot">{{ c.hospital }}</div>
          </div>
          <el-empty v-if="!semanticCases.length && !semanticLoading" description="输入一句话试试语义检索" :image-size="60" />
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog v-model="detailDialog" width="760px" title="病例详情" top="6vh">
      <div v-if="detail" class="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="疾病">{{ detail.disease }}</el-descriptions-item>
          <el-descriptions-item label="科室">{{ detail.department }}</el-descriptions-item>
          <el-descriptions-item label="医院" :span="2">{{ detail.hospital }}</el-descriptions-item>
          <el-descriptions-item label="患者诉求" :span="2">{{ detail.help_wanted || '未提供' }}</el-descriptions-item>
        </el-descriptions>

        <h4>病情描述</h4>
        <p class="detail-text">{{ detail.patient_description || '未提供' }}</p>

        <h4>医患对话（{{ (detail.qa_pairs || []).length }} 轮）</h4>
        <div v-for="qa in detail.qa_pairs" :key="qa.turn_no" class="qa">
          <div class="q"><b>患者：</b>{{ qa.patient_question }}</div>
          <div class="a"><b>医生：</b>{{ qa.doctor_answer }}</div>
        </div>
        <p v-if="!(detail.qa_pairs || []).length" class="muted">该病例没有结构化对话记录</p>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { caseApi, type CaseItem } from '@/api'
import { apiError } from '@/api/client'

const mode = ref<'keyword' | 'semantic'>('keyword')

const keyword = ref('')
const department = ref('')
const departments = ref<{ department: string; count: number }[]>([])
const items = ref<CaseItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const loading = ref(false)

const semanticQuery = ref('')
const semanticLoading = ref(false)
const semanticCases = ref<any[]>([])
const semanticMeta = ref<{ confidence: number; coverage: string } | null>(null)

const detailDialog = ref(false)
const detail = ref<any>(null)

async function loadDepartments() {
  try {
    departments.value = await caseApi.departments(30)
  } catch {
    departments.value = []
  }
}

async function search(p = 1) {
  page.value = p
  loading.value = true
  try {
    const res = await caseApi.search({
      keyword: keyword.value,
      department: department.value,
      page: p,
      page_size: pageSize,
    })
    items.value = res.items
    total.value = res.total
  } catch (e) {
    ElMessage.error(apiError(e))
  } finally {
    loading.value = false
  }
}

async function runSemantic() {
  const q = semanticQuery.value.trim()
  if (q.length < 2) {
    ElMessage.warning('请至少输入 2 个字')
    return
  }
  semanticLoading.value = true
  try {
    const res = await caseApi.semantic({ q, top_k: 6 })
    semanticCases.value = res.cases
    semanticMeta.value = { confidence: res.confidence, coverage: res.coverage }
  } catch (e) {
    ElMessage.error(apiError(e))
  } finally {
    semanticLoading.value = false
  }
}

async function openDetail(caseId: number) {
  try {
    detail.value = await caseApi.detail(caseId)
    detailDialog.value = true
  } catch (e) {
    ElMessage.error(apiError(e))
  }
}

onMounted(async () => {
  await Promise.all([loadDepartments(), search(1)])
})
</script>

<style scoped>
.panel {
  padding: 8px 18px 18px;
}

.filters {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 8px 0 14px;
  flex-wrap: wrap;
}

.small {
  font-size: 12px;
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}

.meta {
  margin-bottom: 10px;
}

.case-card {
  border: 1px solid var(--ac-border);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: 0.15s;
}

.case-card:hover {
  border-color: var(--ac-primary);
  background: #f8fdfb;
}

.cc-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.cc-disease {
  font-weight: 600;
  font-size: 14px;
  flex: 1;
}

.cc-sim {
  color: var(--ac-primary);
  font-size: 13px;
}

.cc-body {
  font-size: 13px;
  color: #43505e;
  line-height: 1.7;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.cc-foot {
  margin-top: 6px;
  font-size: 12px;
  color: var(--ac-muted);
}

.detail h4 {
  margin: 16px 0 6px;
}

.detail-text {
  font-size: 13px;
  line-height: 1.8;
  color: #43505e;
  white-space: pre-wrap;
}

.qa {
  font-size: 13px;
  line-height: 1.7;
  padding: 8px 10px;
  border-radius: 8px;
  background: #fafbfc;
  margin-bottom: 8px;
}

.qa .a {
  margin-top: 4px;
  color: #2c4a43;
}
</style>
