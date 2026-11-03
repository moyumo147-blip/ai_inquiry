import axios from 'axios'

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 180000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('ac_token')
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem('ac_token')
      localStorage.removeItem('ac_user')
      if (!location.pathname.startsWith('/login')) {
        location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export function apiError(error: unknown): string {
  const err = error as any
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  if (err?.message) return err.message
  return '请求失败，请稍后重试'
}
