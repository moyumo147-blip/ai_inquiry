<template>
  <div class="page">
    <h1 class="page-title">我的病历</h1>
    <p class="page-subtitle">由问诊对话自动生成的 SOAP 病历，可编辑后保存为草稿</p>

    <div class="card panel">
      <el-table :data="records" v-loading="loading" empty-text="还没有病历，去「智能问诊」生成一份吧">
        <el-table-column prop="chief_complaint" label="主诉" min-width="240" show-overflow-tooltip />
        <el-table-column prop="diagnosis" label="初步诊断" width="140" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.status === 'draft' ? '草稿' : row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="160">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column width="110">
          <template #default="{ row }">
            <el-button link type="primary" @click="open(row)">查看 / 编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="drawer" size="560px" :title="editing?.chief_complaint || '病历'">
      <el-form v-if="editing" label-position="top" class="form">
        <el-form-item label="主诉">
          <el-input v-model="editing.chief_complaint" type="textarea" :rows="1" autosize />
        </el-form-item>
        <el-form-item label="现病史">
          <el-input v-model="editing.present_illness" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="既往史">
          <el-input v-model="editing.past_history" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="过敏史">
          <el-input v-model="editing.allergy_history" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="体格检查">
          <el-input v-model="editing.physical_exam" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="初步评估">
          <el-input v-model="editing.assessment" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="初步诊断">
          <el-input v-model="editing.diagnosis" />
        </el-form-item>
        <el-form-item label="诊疗计划">
          <el-input v-model="editing.plan" type="textarea" :rows="4" />
        </el-form-item>
        <p class="muted small">
          病历由 AI 依据问诊对话生成，需经医生审核；本系统不提供处方与用药剂量。
        </p>
      </el-form>

      <template #footer>
        <el-button @click="drawer = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { recordApi, type RecordInfo } from '@/api'
import { apiError } from '@/api/client'

const records = ref<RecordInfo[]>([])
const loading = ref(false)
const saving = ref(false)
const drawer = ref(false)
const editing = ref<RecordInfo | null>(null)

function formatTime(t?: string) {
  if (!t) return '—'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}

async function load() {
  loading.value = true
  try {
    records.value = await recordApi.list()
  } catch (e) {
    ElMessage.error(apiError(e))
  } finally {
    loading.value = false
  }
}

function open(record: RecordInfo) {
  editing.value = { ...record }
  drawer.value = true
}

async function save() {
  if (!editing.value) return
  saving.value = true
  try {
    const { id, soap, created_at, updated_at, session_id, ...payload } = editing.value
    await recordApi.update(id, payload)
    ElMessage.success('已保存')
    drawer.value = false
    await load()
  } catch (e) {
    ElMessage.error(apiError(e))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.panel {
  padding: 16px 18px;
}

.form {
  padding-right: 8px;
}

.small {
  font-size: 12px;
}
</style>
