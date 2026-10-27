<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, headers, newKey } from '../api/client'
import { labels, money, date } from '../utils/format'
const route = useRoute()
const lookup = computed(() => route.path === '/lookup')
const form = reactive({ code:'', order_id:'', lookup_token:'' }), result = ref<any>(null), loading=ref(false), demoMode=ref(false)
onMounted(async () => {
  try {
    const response = await fetch('/api/health', { cache:'no-store' })
    if (response.ok) demoMode.value = (await response.json()).mode === 'mock'
  } catch { /* The order request will report an unavailable API when submitted. */ }
})

async function submit() {
  if (loading.value) return
  loading.value = true
  try {
    if (lookup.value) result.value = (await api.post('/orders/lookup',{order_id:form.order_id,lookup_token:form.lookup_token})).data
    else {
      const fingerprint = [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(form.code.trim().toUpperCase())))].map(b=>b.toString(16).padStart(2,'0')).join('')
      const storageKey = `redeem-key:${fingerprint}`
      const pendingKey = sessionStorage.getItem(storageKey) || newKey()
      sessionStorage.setItem(storageKey,pendingKey)
      result.value = (await api.post('/redeem',{code:form.code},headers(pendingKey))).data
      form.order_id=result.value.order_id; form.lookup_token=result.value.lookup_token
    }
  } finally { loading.value=false }
}
async function refresh() { if (loading.value || !form.order_id || !form.lookup_token) return; loading.value=true; try { result.value={...result.value,...(await api.post('/orders/lookup',{order_id:form.order_id,lookup_token:form.lookup_token})).data} } finally { loading.value=false } }
function saveReceipt() { const url=URL.createObjectURL(new Blob([`订单编号: ${form.order_id}\n查询凭证: ${form.lookup_token}\n请妥善保管，请勿公开。`],{type:'text/plain;charset=utf-8'})); const a=document.createElement('a');a.href=url;a.download='云果订单凭证.txt';a.click();URL.revokeObjectURL(url) }
</script>
<template><div class="narrow-page"><p class="eyebrow">{{ lookup ? 'TRACK YOUR ORDER' : 'REDEEM YOUR SERVICE' }}</p><h1>{{ lookup ? '每一步进度，都清晰可见。' : '一枚卡密，开启你的服务。' }}</h1><p class="muted">{{ lookup ? '填写订单编号与兑换时获得的查询凭证。' : '提交有效卡密，系统将创建订单并进入履约队列。' }}</p><el-alert v-if="demoMode" class="spaced" title="当前为演示环境：订单完成表示模拟履约，不代表真实订阅已开通。" type="warning" :closable="false" show-icon /><section class="panel"><form @submit.prevent="submit"><template v-if="lookup"><label>订单编号<input v-model="form.order_id" required placeholder="YG 开头的订单编号" /></label><label>查询凭证<input v-model="form.lookup_token" required placeholder="兑换成功后获得的查询凭证" /></label></template><label v-else>兑换卡密<input v-model="form.code" required minlength="16" maxlength="100" autocomplete="off" placeholder="YG-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" class="mono" /></label><el-button type="primary" size="large" native-type="submit" :loading="loading" class="full">{{ lookup ? '查询订单' : '确认兑换' }} →</el-button></form><p class="hint">{{ lookup ? '已登录用户也可前往「我的订单」查看钱包购买记录。' : '完整卡密仅在交付时展示。兑换成功后请保存订单凭证。' }}</p></section><section v-if="result" class="panel result-panel"><el-tag type="success">{{ labels[result.fulfillment_status] || result.fulfillment_status }}</el-tag><h3>{{ lookup ? '订单详情' : '兑换成功' }}</h3><dl><dt>订单编号</dt><dd class="mono">{{ result.order_id || result.id }}</dd><template v-if="result.lookup_token"><dt>查询凭证（请保存）</dt><dd class="mono">{{ result.lookup_token }}</dd></template><dt>支付状态</dt><dd>{{ labels[result.payment_status] }}</dd><template v-if="result.product_name"><dt>商品</dt><dd>{{ result.product_name }}</dd><dt>支付金额</dt><dd>{{ money(result.amount) }}</dd><dt>创建时间</dt><dd>{{ date(result.created_at) }}</dd></template><template v-if="result.failure_reason"><dt>处理说明</dt><dd>{{ result.failure_reason }}</dd></template></dl><el-button @click="refresh" :loading="loading">刷新进度</el-button><el-button v-if="result.lookup_token" type="primary" @click="saveReceipt">下载查询凭证</el-button></section></div></template>
