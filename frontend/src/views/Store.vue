<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox, ElMessage } from 'element-plus'
import { api, headers, newKey } from '../api/client'
import { useAuth } from '../stores/auth'
import { money } from '../utils/format'
const route = useRoute(), router = useRouter(), auth = useAuth()
const items = ref<any[]>([]), loading = ref(false), buying = ref(false), q = ref(''), total = ref(0), page = ref(1)
const needsVerification=computed(()=>!!auth.user && auth.features.require_verified_email_for_purchase && !auth.user.email_verified_at)
const pendingStorage = (id:number) => `pending-buy:${auth.user?.id}:${id}`
async function load() {
  loading.value = true
  try {
    let list:any[]
    if (route.params.id) { list = [(await api.get(`/products/${route.params.id}`)).data]; total.value = 1 }
    else { const { data } = await api.get('/products', { params: { q:q.value, page:page.value, page_size:9 } }); list=data.items; total.value=data.total }
    if (auth.user && ['agent','admin'].includes(auth.user.role)) {
      const prices = (await api.get('/agent/prices')).data
      list = list.map(p => { const quote=prices.find((x:any)=>x.id===p.id); return {...p, effective_price:quote?.effective_price, can_purchase:quote?.can_purchase ?? false, restriction:quote?.restriction || ''} })
    }
    items.value = list
  } catch { items.value = [] } finally { loading.value = false }
}
async function buy(product:any) {
  if (!auth.user) return router.push({path:'/login',query:{redirect:route.fullPath}})
  if(needsVerification.value){ElMessage.warning('请先验证注册邮箱，再购买商品');return}
  if (product.can_purchase === false) { ElMessage.warning(product.restriction || '暂不可购买'); return }
  const storageKey = pendingStorage(product.id), stored=sessionStorage.getItem(storageKey)
  let pending:{key:string;amount:number}|null=null
  if(stored) { try { const value=JSON.parse(stored); if(typeof value.key==='string' && Number.isInteger(value.amount)) pending=value } catch { pending={key:stored,amount:product.effective_price??product.price} } }
  const amount=pending?.amount ?? product.effective_price ?? product.price
  await ElMessageBox.confirm(`${pending?'将核对或重试上次未确认的购买请求。':''}将从钱包扣除 ${money(amount)}，用于购买「${product.name}」。仅模拟履约。`, '确认购买', {type:'info'})
  buying.value=true
  try {
    pending=pending || {key:newKey(),amount}; sessionStorage.setItem(storageKey,JSON.stringify(pending))
    await api.post('/orders',{product_id:product.id,expected_amount:amount},headers(pending.key))
    sessionStorage.removeItem(storageKey); ElMessage.success('购买成功，订单已进入履约队列'); await router.push('/me/orders')
  } catch (error:any) {
    if(error.response?.headers?.['x-error-code']==='PRICE_CHANGED') {sessionStorage.removeItem(storageKey);await load()}
    throw error
  } finally {buying.value=false}
}
onMounted(load)
</script>
<template><section v-if="!route.params.id" class="hero"><div><div class="hero-badge"><span class="status-dot"></span> 让数字服务，更简单</div><h1>好服务，<br><span>即刻抵达。</span></h1><p>精选数字商品与订阅服务。<br>便捷购买，安全兑换，订单进度随时掌握。</p><div class="hero-actions"><a href="#products" class="solid-link">探索商品 ↗</a><router-link to="/redeem">已有卡密？立即兑换 →</router-link></div></div><div class="hero-art" aria-hidden="true"><div class="orb orb-one"></div><div class="orb orb-two"></div><div class="floating-card"><span class="mini-icon">✳</span><small>DIGITAL SERVICES</small><h3>连接你的<br>数字生活。</h3><div class="card-line"></div><span>YUNGUO / 2026 <b>↗</b></span></div><div class="art-label"><span class="status-dot"></span> 每一步，清晰可见</div></div></section>
<div id="products" class="section-heading"><div><p class="eyebrow">CURATED FOR YOU</p><h2>{{ route.params.id ? '套餐详情' : '探索精选服务' }} <small v-if="!route.params.id">{{ total }} 个精选套餐</small></h2></div><form v-if="!route.params.id" class="search-form" @submit.prevent="page=1;load()"><el-input v-model="q" placeholder="搜索商品或服务" clearable /><el-button native-type="submit">搜索</el-button></form></div>
<el-alert class="spaced" title="当前为 MVP 演示：钱包充值为模拟资金，所有套餐仅演示订单履约，不开通真实订阅。" type="info" :closable="false" show-icon />
<section class="product-grid" v-loading="loading"><article v-for="(product,i) in items" :key="product.id" class="product-card"><div class="product-card-top"><span class="product-mark">{{ ['✳','◈','⌘'][i%3] }}</span><span class="category">{{ product.category }}</span></div><h3>{{ product.name }}</h3><p>{{ product.description }}</p><div class="features"><span>✓ 订单状态可追踪</span><span>✓ 支持钱包与卡密</span></div><div class="price-row"><strong>{{ money(product.effective_price ?? product.price) }}</strong><s>{{ money(product.original_price) }}</s></div><div class="product-bottom"><small>可售库存 {{ product.stock }}</small><router-link v-if="!route.params.id" :to="`/products/${product.id}`">查看详情 ↗</router-link></div><p v-if="product.restriction" class="form-error" role="note">{{ product.restriction }}</p><el-button type="primary" class="full" size="large" :loading="buying" :disabled="product.stock <= 0 || product.can_purchase === false || needsVerification" @click="buy(product).catch(()=>{})">{{ needsVerification ? '请先验证邮箱' : product.can_purchase === false ? '暂不可购买' : product.stock > 0 ? '立即购买 →' : '暂时售罄' }}</el-button></article></section><el-empty v-if="!loading && !items.length" description="没有找到相关商品" /><el-pagination v-if="!route.params.id && total>9" v-model:current-page="page" :total="total" :page-size="9" layout="prev,pager,next" @current-change="load" /><section class="assurance"><div><b>01</b><h4>精选服务</h4><p>套餐内容与价格清晰展示</p></div><div><b>02</b><h4>便捷兑换</h4><p>输入卡密，获取专属订单凭证</p></div><div><b>03</b><h4>透明履约</h4><p>订单进度与交易记录随时可查</p></div></section></template>
