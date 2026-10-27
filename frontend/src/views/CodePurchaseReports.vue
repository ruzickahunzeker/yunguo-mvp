<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api/client'
import { money } from '../utils/format'
import RecordTable from '../components/RecordTable.vue'
const today=new Date(),earlier=new Date(today);earlier.setUTCDate(earlier.getUTCDate()-29)
const filters=reactive({start:earlier.toISOString().slice(0,10),end:today.toISOString().slice(0,10),agent_id:'',product_id:''})
const applied=ref<Record<string,string>>({}),data=ref<any>(),loading=ref(false),exporting=ref(false),error=ref('')
const invalid=computed(()=>!filters.start||!filters.end||filters.start>filters.end||(Date.parse(filters.end)-Date.parse(filters.start))/86400000>=366)
const columns=[{key:'batches',label:'采购批次',width:120},{key:'quantity',label:'采购张数',width:120},{key:'amount',label:'扣款金额',type:'money',width:150}]
async function search(){
 if(invalid.value || loading.value)return
 loading.value=true;error.value='';data.value=undefined
 const params={start:filters.start,end:filters.end,...(filters.agent_id?{agent_id:filters.agent_id}:{}),...(filters.product_id?{product_id:filters.product_id}:{})}
 try{const response=await api.get('/admin/reports/code-purchases',{params});data.value=response.data;applied.value=params}
 catch(e:any){error.value=typeof e.response?.data?.detail==='string'?e.response.data.detail:'采购报表加载失败，请重试。'}finally{loading.value=false}
}
async function exportCSV(){
 if(exporting.value || !applied.value.start)return
 const params={...applied.value}
 exporting.value=true
 try{const result=await api.get('/admin/reports/code-purchases/export',{params,responseType:'blob'});const url=URL.createObjectURL(result.data);const link=document.createElement('a');link.href=url;link.download=`code-purchases-${params.start}-${params.end}.csv`;link.click();URL.revokeObjectURL(url)}finally{exporting.value=false}
}
onMounted(search)
</script>
<template>
<div class="section-heading"><div><p class="eyebrow">YUNGUO / PROCUREMENT</p><h1>卡密采购报表</h1><p class="muted">按发卡采购流水统计，金额单位为人民币，包含演示资金。</p></div><el-button :loading="exporting" :disabled="!data||loading" @click="exportCSV">导出采购 CSV</el-button></div>
<section class="panel"><form class="procurement-filters" @submit.prevent="search">
<label>开始日期（UTC）<input v-model="filters.start" type="date" required /></label><label>结束日期（UTC）<input v-model="filters.end" type="date" required /></label>
<label>代理 ID<input v-model="filters.agent_id" type="number" min="1" max="2147483647" step="1" placeholder="全部代理" /></label>
<label>商品 ID<input v-model="filters.product_id" type="number" min="1" max="2147483647" step="1" placeholder="全部商品" /></label>
<el-button type="primary" native-type="submit" :disabled="invalid" :loading="loading">查询采购报表</el-button>
</form><p v-if="invalid" role="alert">请选择开始不晚于结束、最多366天的日期范围。</p></section>
<el-alert class="spaced" title="仅统计代理余额发卡扣费，不包含管理员免费分配或钱包商品订单。兑换不重复计费；作废、到期不自动退款，人工钱包调整不冲减本报表。此金额不是实际收款、代理销售额或利润。" type="info" :closable="false" />
<el-alert v-if="error" :title="error" type="error" :closable="false" role="alert" />
<template v-if="data">
<p role="status">已查询：{{data.start}} 至 {{data.end}}（UTC） · {{data.agent_id?`代理 #${data.agent_id}`:'全部代理'}} · {{data.product_id?`商品 #${data.product_id}`:'全部商品'}}</p>
<div class="stats-grid"><div class="stat-card"><span>采购批次</span><strong>{{data.summary.batches}}</strong><small>重复提交不新增批次</small></div><div class="stat-card"><span>采购张数</span><strong>{{data.summary.quantity}}</strong><small>含已使用、过期或作废卡密</small></div><div class="stat-card"><span>采购扣款</span><strong>{{money(data.summary.amount)}}</strong><small>已记入钱包采购流水</small></div></div>
<section class="panel table-panel"><h3>每日采购</h3><div class="daily-scroll"><RecordTable :rows="data.daily" :columns="[{key:'date',label:'日期（UTC）',width:150},...columns]" /></div></section>
<section class="panel table-panel"><h3>代理汇总</h3><RecordTable :rows="data.agents" :columns="[{key:'agent_id',label:'代理ID',width:120},...columns]" /></section>
<section class="panel table-panel"><h3>商品汇总</h3><RecordTable :rows="data.products" :columns="[{key:'product_id',label:'商品ID',width:120},...columns]" /></section>
</template>
</template>
<style scoped>
.procurement-filters{display:flex;flex-wrap:wrap;gap:16px;align-items:end}.procurement-filters label{flex:1;min-width:150px;margin:0}.daily-scroll{max-height:480px;overflow:auto}
</style>
