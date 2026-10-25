<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api/client'
import { money } from '../utils/format'
import RecordTable from '../components/RecordTable.vue'
const today=new Date(), earlier=new Date(today)
earlier.setUTCDate(earlier.getUTCDate()-29)
const filters=reactive({start:earlier.toISOString().slice(0,10),end:today.toISOString().slice(0,10),source:'',product_id:''})
const applied=ref<Record<string,string>>({}),data=ref<any>(null),loading=ref(false),exporting=ref(false),error=ref(''),page=ref(1)
const invalid=computed(()=>!filters.start || !filters.end || filters.start>filters.end || (Date.parse(filters.end)-Date.parse(filters.start))/86400000>=366)
const summary=computed(()=>data.value?.summary||{})
const columns=[{key:'orders',label:'订单数',width:100},{key:'wallet_orders',label:'钱包单数',width:110},{key:'code_orders',label:'卡密单数',width:110},{key:'gross_amount',label:'成交额',type:'money',width:140},{key:'refund_amount',label:'退款额',type:'money',width:140},{key:'net_amount',label:'净额',type:'money',width:140},{key:'completed_orders',label:'已完成',width:100},{key:'failed_orders',label:'失败',width:100}]
async function load(){
 loading.value=true;error.value=''
 try{data.value=(await api.get('/admin/reports/sales',{params:{...applied.value,page:page.value}})).data}
 catch{data.value=null;error.value='报表加载失败，请重试。'}
 finally{loading.value=false}
}
async function search(){
 if(invalid.value)return
 applied.value={start:filters.start,end:filters.end,...(filters.source?{source:filters.source}:{}),...(filters.product_id?{product_id:filters.product_id}:{})}
 page.value=1;await load()
}
async function exportCSV(){
 exporting.value=true
 try{
  const result=await api.get('/admin/reports/sales/export',{params:applied.value,responseType:'blob'})
  const url=URL.createObjectURL(result.data)
  const link=document.createElement('a');link.href=url;link.download=`sales-${applied.value.start}-${applied.value.end}.csv`;link.click();URL.revokeObjectURL(url)
 }finally{exporting.value=false}
}
onMounted(search)
</script>
<template>
<div class="section-heading"><div><p class="eyebrow">YUNGUO / REPORTS</p><h1>交易统计报表</h1><p class="muted">按订单创建日期统计，金额使用订单快照，含演示资金。</p></div><el-button :loading="exporting" :disabled="!data || loading" @click="exportCSV">导出每日 CSV</el-button></div>
<section class="panel report-filters"><form @submit.prevent="search"><label>开始日期（UTC）<input v-model="filters.start" type="date" required /></label><label>结束日期（UTC）<input v-model="filters.end" type="date" required /></label><label>订单来源<select v-model="filters.source"><option value="">全部来源</option><option value="wallet">钱包购买</option><option value="code">卡密兑换</option></select></label><label>商品 ID<input v-model="filters.product_id" type="number" min="1" step="1" placeholder="全部商品" /></label><el-button native-type="submit" type="primary" :disabled="invalid" :loading="loading">查询报表</el-button></form><p v-if="invalid" class="form-error" role="alert">请选择开始不晚于结束、最多366天的日期范围。</p></section>
<el-alert class="spaced" title="退款按当前状态归回原订单创建日；这是按创建日归集的订单统计，不是当日收支流水。卡密兑换不计成交额，净额不代表利润。日期均为 UTC。" type="info" :closable="false" />
<el-alert v-if="error" :title="error" type="error" :closable="false" role="alert" />
<template v-if="data"><p class="muted report-period" role="status">统计范围：{{data.start}} 至 {{data.end}} · {{data.source==='wallet'?'钱包购买':data.source==='code'?'卡密兑换':'全部来源'}}{{data.product_id?` · 商品 #${data.product_id}`:''}}</p>
<div class="stats-grid" v-loading="loading"><div class="stat-card"><span>订单总数</span><strong>{{summary.orders}}</strong><small>钱包 {{summary.wallet_orders}} / 卡密 {{summary.code_orders}}</small></div><div class="stat-card"><span>成交额</span><strong>{{money(summary.gross_amount)}}</strong><small>含已退款的钱包订单原额</small></div><div class="stat-card"><span>退款额</span><strong>{{money(summary.refund_amount)}}</strong><small>已退款 {{summary.refunded_orders}} 笔</small></div><div class="stat-card"><span>订单净额</span><strong>{{money(summary.net_amount)}}</strong><small>成交额减退款额</small></div></div>
<section class="panel report-states"><h3>当前履约状态</h3><p>待履约 {{summary.queued_orders}} · 处理中 {{summary.processing_orders}} · 已完成 {{summary.completed_orders}} · 失败 {{summary.failed_orders}} · 已取消 {{summary.canceled_orders}}</p></section>
<section class="panel table-panel"><h3>每日趋势</h3><p class="muted">无订单的日期补零，CSV 导出包含完整区间及合计，金额单位为整数分。</p><div class="report-daily"><RecordTable :rows="data.daily" :columns="[{key:'date',label:'日期（UTC）',width:150},...columns]" :loading="loading" /></div></section>
<section class="panel table-panel"><h3>商品汇总</h3><p class="muted">按净额从高到低排序，商品 ID 可用于订单页面核查。</p><RecordTable :rows="data.products.items" :columns="[{key:'product_id',label:'商品ID',width:100},...columns]" :loading="loading"/><el-pagination v-model:current-page="page" :total="data.products.total" :page-size="20" layout="total,prev,pager,next" @current-change="load" /></section>
</template>
</template>
<style scoped>
.report-filters form{display:flex;flex-wrap:wrap;align-items:end;gap:16px}.report-filters label{flex:1;min-width:160px;margin:0}.report-filters select{width:100%;padding:11px;border:1px solid var(--el-border-color);border-radius:6px;background:white;color:inherit;font:inherit}.report-daily{max-height:480px;overflow:auto}.report-states{margin-bottom:24px}.report-states p{line-height:1.9}.report-period{margin:24px 0 16px}
</style>
