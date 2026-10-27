<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../stores/auth'
const route = useRoute(), router = useRouter(), auth = useAuth()
const register = computed(() => route.path === '/register')
const form = reactive({ email: '', password: '', name: '' }), loading = ref(false)
async function submit() {
  if (loading.value) return
  loading.value = true
  try {
    await auth.login(register.value ? 'register' : 'login', register.value ? form : { email: form.email, password: form.password })
    const target = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') && !route.query.redirect.startsWith('//') ? route.query.redirect : '/me/orders'
    await router.push(target)
  } finally { loading.value = false }
}
</script>
<template><div class="auth-layout"><div class="auth-intro"><p class="eyebrow">YOUR DIGITAL WORKSPACE</p><h1>每一份服务，<br>都有清晰的交付。</h1><p>从选择套餐到订单完成，<br>在一个地方管理你的数字服务。</p><div class="intro-lines"><span>01 / 精选数字商品</span><span>02 / 安全卡密兑换</span><span>03 / 实时订单追踪</span></div></div><section class="panel auth-panel"><p class="eyebrow">WELCOME TO YUNGUO</p><h2>{{ register ? '创建你的账号' : '欢迎回来' }}</h2><p class="muted">{{ register ? '开启便捷的数字服务体验' : '登录后查看订单、钱包与专属价格' }}</p><form @submit.prevent="submit"><label v-if="register">昵称<input v-model="form.name" maxlength="80" autocomplete="nickname" placeholder="怎么称呼你" /></label><label>邮箱<input v-model="form.email" type="email" required maxlength="254" autocomplete="email" placeholder="you@example.com" /></label><label>密码<input v-model="form.password" type="password" :minlength="register ? 10 : 1" maxlength="128" required :autocomplete="register ? 'new-password' : 'current-password'" placeholder="注册密码至少 10 位" /></label><el-button native-type="submit" type="primary" size="large" :loading="loading" class="full">{{ register ? '注册账号' : '登录账号' }} →</el-button></form><p class="muted">{{ register ? '已有账号？' : '还没有账号？' }} <router-link :to="register ? '/login' : '/register'">{{ register ? '前往登录' : '立即注册' }}</router-link></p><router-link v-if="!register" to="/forgot-password" class="recovery-link">忘记密码？</router-link></section></div></template>
