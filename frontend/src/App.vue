<script setup lang="ts">
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from './stores/auth'
const auth = useAuth(), route = useRoute(), router = useRouter()
const mockMode = ref(false)
onMounted(async () => {
  try {
    const response = await fetch('/api/health', { cache: 'no-store' })
    if (response.ok) mockMode.value = (await response.json()).mode === 'mock'
  } catch { /* The normal API requests report connection failures. */ }
})
const backoffice = computed(() => /^\/(admin|agent|me)\//.test(route.path))
const adminLinks = [['dashboard','数据概览'],['reports','统计报表'],['code-purchase-reports','卡密采购报表'],['operations','运行状态'],['monitoring','监控与告警'],['users','用户管理'],['products','商品套餐'],['codes','卡密管理'],['orders','订单管理'],['wallets','钱包管理'],['agents','代理管理'],['settings','系统设置'],['audit-logs','操作日志']]
const memberLinks = [['orders','我的订单'],['wallet','我的钱包'],['transactions','资金流水'],['profile','个人资料']]
const agentLinks = [['overview','代理概览'],['prices','商品价格'],['codes','卡密库存'],['orders','代理订单'],['bills','代理账单'],['team','名下代理']]
const zone = computed(() => route.path.split('/')[1])
const links = computed(() => zone.value === 'admin' ? adminLinks : zone.value === 'agent' ? agentLinks : memberLinks)
async function logout() { await auth.logout(); router.push('/') }
</script>
<template>
  <el-config-provider :locale="zhCn"><div class="app-shell">
    <header class="topbar"><router-link to="/" class="brand"><span class="brand-icon">云</span>云果 <small>DIGITAL SERVICES</small></router-link>
      <nav><router-link to="/products">商品中心</router-link><router-link to="/redeem">卡密兑换</router-link><router-link to="/lookup">订单查询</router-link></nav>
      <div class="account"><template v-if="auth.user"><router-link v-if="auth.user.role === 'admin'" to="/admin/dashboard">管理后台</router-link><router-link v-if="auth.user.role === 'agent'" to="/agent/overview">代理中心</router-link><router-link to="/me/orders">{{ auth.user.name || '用户中心' }}</router-link><button class="text-btn" @click="logout">退出</button></template><router-link v-else class="login-link" to="/login">登录 / 注册 ↗</router-link></div>
    </header>
    <div :class="{ 'workspace': backoffice }"><aside v-if="backoffice" class="sidebar"><p class="eyebrow">WORKSPACE</p><h3>{{ zone === 'admin' ? '管理工作台' : zone === 'agent' ? '代理中心' : '用户中心' }}</h3><router-link v-for="(link, i) in links" :key="link[0]" :to="`/${zone}/${link[0]}`"><span class="nav-number">{{ String(i + 1).padStart(2, '0') }}</span>{{ link[1] }}</router-link><div class="sidebar-note"><span class="status-dot"></span> 业务工作台<br><small>订单与资金全程留痕</small></div></aside>
    <main :class="backoffice ? 'workspace-main' : 'public-main'"><el-alert v-if="backoffice && mockMode" class="spaced" title="当前为演示环境：资金和订单履约均为模拟数据，不代表真实付款或订阅开通。" type="warning" :closable="false" show-icon /><div v-if="auth.user && !auth.user.email_verified_at && auth.features.email_verification_enabled && route.path!=='/verify-email'" class="verification-notice" role="note"><span>{{auth.features.require_verified_email_for_purchase?'购买前需完成注册邮箱验证。':'注册邮箱尚未验证，请检查验证邮件。'}}</span><router-link to="/me/profile">前往个人资料 →</router-link></div><router-view :key="route.path" /></main></div>
    <footer v-if="!backoffice">© {{ new Date().getFullYear() }} 云果数字服务 <span>安全交易 · 清晰交付 · 全程可查</span><small>演示套餐仅模拟履约，不开通真实订阅</small></footer>
  </div></el-config-provider>
</template>
