import axios from 'axios'
import { ElMessage } from 'element-plus'
export const api = axios.create({ baseURL: '/api', timeout: 15000 })
// Session-scoped token: never persist credentials or full card codes in localStorage.
api.interceptors.request.use(config => {
  const token = sessionStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
api.interceptors.response.use(r => r, e => {
  if (e.response?.status === 401) {
    sessionStorage.removeItem('access_token')
    window.dispatchEvent(new Event('auth-expired'))
  }
  const detail = e.response?.data?.detail
  ElMessage.error(typeof detail === 'string' ? detail : e.response?.status === 422 ? '请检查输入字段及格式' : '请求失败，请稍后重试')
  return Promise.reject(e)
})
export const newKey = () => crypto.randomUUID()
export const headers = (key: string) => ({ headers: { 'Idempotency-Key': key } })
