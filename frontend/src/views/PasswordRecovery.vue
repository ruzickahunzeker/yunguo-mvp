<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'
const route = useRoute(), router = useRouter(), auth = useAuth()
const reset = computed(() => route.path === '/reset-password')
// The fragment never reaches the HTTP server. Remove it before any API calls.
const token = ref('')
const email = ref(''), password = ref(''), confirm = ref(''), loading = ref(false), available = ref<boolean | null>(null), message = ref('')
watch(() => route.hash, hash => {
  if (!reset.value || !hash) return
  token.value = new URLSearchParams(hash.slice(1)).get('token') || ''
  password.value = ''; confirm.value = ''; message.value = ''
  void router.replace({ path: route.path, hash: '', query: {} })
}, { immediate: true })
const mismatch = computed(() => !!confirm.value && password.value !== confirm.value)
async function submit() {
  if (mismatch.value || loading.value || !available.value) return
  loading.value = true
  try {
    if (reset.value) {
      const { data } = await api.post('/auth/reset-password', { token: token.value, new_password: password.value })
      auth.clear(); token.value = ''; password.value = ''; confirm.value = ''; message.value = data.message
    } else {
      const { data } = await api.post('/auth/forgot-password', { email: email.value })
      message.value = data.message
    }
  } finally { loading.value = false }
}
onMounted(async () => { try { available.value = (await api.get('/auth/features')).data.password_reset_enabled } catch { available.value = false } })
</script>
<template><div class="narrow-page recovery-page"><p class="eyebrow">ACCOUNT RECOVERY</p><h1>{{ reset ? '设置新的登录密码' : '找回你的账号' }}</h1><p class="muted">{{ reset ? '重置完成后，所有已登录的设备都需要重新登录。' : '输入注册邮箱，我们会发送一次性的密码重置链接。' }}</p><section class="panel" v-loading="available === null"><template v-if="message"><el-alert :title="message" type="success" :closable="false" show-icon role="status" /><p class="hint" v-if="!reset">邮件可能稍有延迟，链接在有限时间内有效。请勿转发链接。</p><router-link to="/login" class="solid-link recovery-return">返回登录 →</router-link></template><template v-else-if="available === false"><el-alert title="邮件找回暂未开放，请联系管理员核验身份后重置密码。" type="info" :closable="false" /><router-link to="/login" class="recovery-return">返回登录</router-link></template><template v-else-if="reset && !token"><el-alert title="重置链接缺少凭证，请从最新的邮件中打开完整链接。" type="warning" :closable="false" /><router-link to="/forgot-password" class="recovery-return">重新申请重置链接 →</router-link></template><form v-else @submit.prevent="submit"><template v-if="reset"><label>新密码<input v-model="password" type="password" minlength="10" maxlength="128" required autocomplete="new-password" /></label><label>确认新密码<input v-model="confirm" type="password" minlength="10" maxlength="128" required autocomplete="new-password" :aria-invalid="mismatch" aria-describedby="password-match" /></label><p id="password-match" v-if="mismatch" class="form-error" role="alert">两次输入的密码不一致</p></template><label v-else>注册邮箱<input v-model="email" type="email" required maxlength="254" autocomplete="email" placeholder="you@example.com" /></label><el-button native-type="submit" type="primary" size="large" class="full" :loading="loading" :disabled="available !== true || mismatch">{{ reset ? '确认重置密码' : '发送重置链接' }} →</el-button><p v-if="reset" class="hint">仅最新邮件中的链接有效。刷新本页后，请重新从邮件打开链接。</p><router-link v-if="reset" to="/forgot-password" class="recovery-return">重新申请重置链接 →</router-link></form></section></div></template>
