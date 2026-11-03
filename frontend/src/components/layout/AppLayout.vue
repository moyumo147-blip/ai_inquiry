<template>
  <el-container class="layout">
    <el-aside width="216px" class="aside">
      <div class="brand">
        <span class="logo">🩺</span>
        <div>
          <div class="brand-name">安诊</div>
          <div class="brand-sub">AI 问诊系统</div>
        </div>
      </div>

      <el-menu :default-active="activePath" router class="menu">
        <el-menu-item index="/">
          <el-icon><DataBoard /></el-icon>
          <span>概览</span>
        </el-menu-item>
        <el-menu-item index="/consult">
          <el-icon><ChatDotRound /></el-icon>
          <span>智能问诊</span>
        </el-menu-item>
        <el-menu-item index="/records">
          <el-icon><Document /></el-icon>
          <span>我的病历</span>
        </el-menu-item>
        <el-menu-item index="/cases">
          <el-icon><Collection /></el-icon>
          <span>病例知识库</span>
        </el-menu-item>
      </el-menu>

      <div class="aside-foot">
        <div>AI 生成内容仅供参考</div>
        <div>急症请立即拨打 120</div>
      </div>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-title">{{ pageTitle }}</div>
        <el-dropdown @command="onCommand">
          <span class="user">
            <el-icon><User /></el-icon>
            {{ auth.displayName }}
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>{{ auth.user?.username }}</el-dropdown-item>
              <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const activePath = computed(() => {
  if (route.path.startsWith('/consult')) return '/consult'
  if (route.path.startsWith('/records')) return '/records'
  if (route.path.startsWith('/cases')) return '/cases'
  return '/'
})

const pageTitle = computed(() => {
  if (route.path.startsWith('/consult')) return '智能问诊'
  if (route.path.startsWith('/records')) return '我的病历'
  if (route.path.startsWith('/cases')) return '病例知识库'
  return '概览'
})

function onCommand(command: string) {
  if (command === 'logout') {
    auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout {
  height: 100vh;
}

.aside {
  background: #102a26;
  color: #fff;
  display: flex;
  flex-direction: column;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.logo {
  font-size: 26px;
}

.brand-name {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 1px;
}

.brand-sub {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.55);
}

.menu {
  flex: 1;
  border-right: none;
  background: transparent;
  --el-menu-bg-color: transparent;
  --el-menu-text-color: rgba(255, 255, 255, 0.72);
  --el-menu-active-color: #fff;
  --el-menu-hover-bg-color: rgba(255, 255, 255, 0.08);
  padding-top: 8px;
}

.menu :deep(.el-menu-item.is-active) {
  background: rgba(31, 138, 112, 0.85);
  border-radius: 8px;
  margin: 4px 10px;
}

.menu :deep(.el-menu-item) {
  margin: 4px 10px;
  border-radius: 8px;
  height: 42px;
}

.aside-foot {
  padding: 14px 16px;
  font-size: 11px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.4);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid var(--ac-border);
  height: 56px;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
}

.user {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--ac-text);
}

.main {
  padding: 0;
  background: var(--ac-bg);
  overflow: auto;
}
</style>
