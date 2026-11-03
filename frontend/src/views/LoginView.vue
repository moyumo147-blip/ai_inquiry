<template>
  <div class="login-page">
    <div class="left">
      <div class="brand">
        <span class="logo">🩺</span>
        <div>
          <h1>安诊</h1>
          <p class="sub">AI 预问诊系统</p>
        </div>
      </div>

      <h2 class="slogan">基于 5.4 万条真实医患病例<br />把「该挂什么科、要不要紧」讲清楚</h2>

      <ul class="features">
        <li><b>智能分诊</b>：按主诉判断科室、紧急程度与红旗症状</li>
        <li><b>知识库问诊</b>：回答引用真实病例，相似度可查</li>
        <li><b>SOAP 病历</b>：一次对话生成结构化门诊病历</li>
        <li><b>安全护栏</b>：胸痛、呼吸困难等强制急诊话术</li>
      </ul>

      <p class="disclaimer">
        本系统仅用于健康科普与就医方向参考，不能替代执业医师的面诊、检查与处方。<br />
        如出现紧急情况，请立即拨打 120。
      </p>
    </div>

    <div class="right">
      <el-card class="box" shadow="never">
        <el-tabs v-model="tab" stretch>
          <el-tab-pane label="登录" name="login">
            <el-form :model="loginForm" label-position="top" @submit.prevent="doLogin">
              <el-form-item label="用户名">
                <el-input v-model="loginForm.username" placeholder="请输入用户名" size="large" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input
                  v-model="loginForm.password"
                  type="password"
                  show-password
                  placeholder="请输入密码"
                  size="large"
                  @keyup.enter="doLogin"
                />
              </el-form-item>
              <el-button type="primary" size="large" class="submit" :loading="loading" @click="doLogin">
                登录
              </el-button>
            </el-form>
            <div class="hint">
              演示账号：<code>demo</code> / <code>demo123456</code>
            </div>
          </el-tab-pane>

          <el-tab-pane label="注册" name="register">
            <el-form :model="registerForm" label-position="top">
              <el-form-item label="用户名">
                <el-input v-model="registerForm.username" placeholder="3-32 位字母或数字" size="large" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input
                  v-model="registerForm.password"
                  type="password"
                  show-password
                  placeholder="至少 6 位"
                  size="large"
                />
              </el-form-item>
              <el-form-item label="昵称（可选）">
                <el-input v-model="registerForm.display_name" size="large" />
              </el-form-item>
              <div class="two">
                <el-form-item label="年龄">
                  <el-input-number v-model="registerForm.age" :min="0" :max="120" controls-position="right" />
                </el-form-item>
                <el-form-item label="性别">
                  <el-select v-model="registerForm.gender" placeholder="选择" style="width: 100%">
                    <el-option label="男" value="male" />
                    <el-option label="女" value="female" />
                    <el-option label="其他" value="other" />
                  </el-select>
                </el-form-item>
              </div>
              <el-button type="primary" size="large" class="submit" :loading="loading" @click="doRegister">
                注册并登录
              </el-button>
            </el-form>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { apiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const tab = ref<'login' | 'register'>('login')
const loading = ref(false)

const loginForm = reactive({ username: '', password: '' })
const registerForm = reactive({
  username: '',
  password: '',
  display_name: '',
  age: undefined as number | undefined,
  gender: '',
})

function go() {
  const redirect = (route.query.redirect as string) || '/'
  router.push(redirect)
}

async function doLogin() {
  if (!loginForm.username || !loginForm.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await auth.login(loginForm.username, loginForm.password)
    ElMessage.success('登录成功')
    go()
  } catch (e) {
    ElMessage.error(apiError(e))
  } finally {
    loading.value = false
  }
}

async function doRegister() {
  if (!registerForm.username || registerForm.password.length < 6) {
    ElMessage.warning('用户名必填，密码至少 6 位')
    return
  }
  loading.value = true
  try {
    await auth.register({
      username: registerForm.username,
      password: registerForm.password,
      display_name: registerForm.display_name || undefined,
      age: registerForm.age,
      gender: registerForm.gender || undefined,
    })
    ElMessage.success('注册成功')
    go()
  } catch (e) {
    ElMessage.error(apiError(e))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  min-height: 100vh;
  background: #f4f7f9;
}

.left {
  flex: 1.15;
  padding: 64px 72px;
  background: linear-gradient(150deg, #102a26 0%, #1f8a70 100%);
  color: #fff;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
}

.logo {
  font-size: 44px;
}

.brand h1 {
  margin: 0;
  font-size: 30px;
  letter-spacing: 4px;
}

.sub {
  margin: 2px 0 0;
  opacity: 0.65;
  font-size: 13px;
}

.slogan {
  font-size: 26px;
  line-height: 1.5;
  font-weight: 500;
  margin: 0 0 28px;
}

.features {
  list-style: none;
  padding: 0;
  margin: 0 0 36px;
  line-height: 2.2;
  font-size: 14px;
  opacity: 0.88;
}

.features li::before {
  content: '✓';
  margin-right: 8px;
  color: #7fe0bf;
}

.disclaimer {
  font-size: 12px;
  opacity: 0.55;
  line-height: 1.8;
}

.right {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
}

.box {
  width: 400px;
  border-radius: 16px;
  padding: 8px 12px 20px;
}

.submit {
  width: 100%;
  margin-top: 8px;
}

.hint {
  margin-top: 16px;
  font-size: 12px;
  color: var(--ac-muted);
  text-align: center;
}

.hint code {
  background: #f2f4f7;
  padding: 1px 5px;
  border-radius: 4px;
}

.two {
  display: flex;
  gap: 12px;
}

.two > * {
  flex: 1;
}
</style>
