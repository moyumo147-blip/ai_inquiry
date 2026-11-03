import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { authApi, type UserInfo } from '@/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('ac_token') || '')
  const user = ref<UserInfo | null>(safeParse(localStorage.getItem('ac_user')))

  const isLoggedIn = computed(() => Boolean(token.value))
  const displayName = computed(() => user.value?.display_name || user.value?.username || '未登录')

  function safeParse(raw: string | null): UserInfo | null {
    if (!raw) return null
    try {
      return JSON.parse(raw) as UserInfo
    } catch {
      return null
    }
  }

  function persist() {
    if (token.value) localStorage.setItem('ac_token', token.value)
    else localStorage.removeItem('ac_token')
    if (user.value) localStorage.setItem('ac_user', JSON.stringify(user.value))
    else localStorage.removeItem('ac_user')
  }

  function setAuth(accessToken: string, info: UserInfo) {
    token.value = accessToken
    user.value = info
    persist()
  }

  async function login(username: string, password: string) {
    const data = await authApi.login(username, password)
    setAuth(data.access_token, data.user)
    return data.user
  }

  async function register(payload: {
    username: string
    password: string
    display_name?: string
    age?: number
    gender?: string
  }) {
    const data = await authApi.register(payload)
    setAuth(data.access_token, data.user)
    return data.user
  }

  async function refreshMe() {
    if (!token.value) return null
    const me = await authApi.me()
    user.value = me
    persist()
    return me
  }

  function logout() {
    token.value = ''
    user.value = null
    persist()
  }

  return { token, user, isLoggedIn, displayName, login, register, refreshMe, logout }
})
