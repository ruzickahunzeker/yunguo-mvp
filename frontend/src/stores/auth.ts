import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/client'
export interface User { id: number; email: string; name: string; role: 'user' | 'agent' | 'admin'; email_verified_at: string | null }
export const useAuth = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const ready = ref(false)
  const features = ref({ password_reset_enabled:false, email_verification_enabled:false, require_verified_email_for_purchase:false })
  function clear() { user.value = null; sessionStorage.removeItem('access_token') }
  window.addEventListener('auth-expired', clear)
  async function load() {
    try { features.value = (await api.get('/auth/features')).data } catch { /* Preserve last known feature policy on a transient error. */ }
    if (sessionStorage.getItem('access_token')) {
      try { user.value = (await api.get('/auth/me')).data } catch { clear() }
    }
    ready.value = true
  }
  async function login(mode: string, form: object) {
    const { data } = await api.post(`/auth/${mode}`, form)
    sessionStorage.setItem('access_token', data.access_token)
    user.value = data.user
  }
  async function logout() { await api.post('/auth/logout'); clear() }
  return { user, ready, features, load, login, logout, clear }
})
