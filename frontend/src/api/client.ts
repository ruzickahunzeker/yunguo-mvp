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
  const status = e.response?.status
  const fallback = !e.response ? '网络连接失败，请检查服务是否启动后重试' :
    status === 403 ? '没有权限执行此操作' :
    status === 404 ? '记录不存在或链接已失效' :
    status === 409 ? '数据状态已变化，请刷新后重试' :
    status === 422 ? '请检查输入字段及格式' :
    status === 429 ? '操作过于频繁，请稍后重试' :
    status && status >= 500 ? '服务暂时不可用，请稍后重试' : '请求失败，请稍后重试'
  ElMessage.error(typeof detail === 'string' ? detail : fallback)
  return Promise.reject(e)
})
export const newKey = () => crypto.randomUUID()
export const headers = (key: string) => ({ headers: { 'Idempotency-Key': key } })
