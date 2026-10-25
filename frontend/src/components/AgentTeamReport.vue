<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import { money } from '../utils/format'
import RecordTable from './RecordTable.vue'
const props=defineProps<{parentId?:number}>()
const today=new Date(),first=new Date(today);first.setUTCDate(first.getUTCDate()-29)
const start=ref(first.toISOString().slice(0,10)),end=ref(today.toISOString().slice(0,10)),q=ref('')
const page=ref(1),loading=ref(false),data=ref<any>()
const columns=[{key:'id',label:'代理ID',width:90},{key:'name',label:'昵称',width:150},{key:'active',label:'账号状态',type:'boolean'},
{key:'level_name',label:'等级',width:130},{key:'order_count',label:'采购订单',width:110},{key:'net_amount',label:'订单净额',type:'money',width:130},
{key:'refund_amount',label:'退款额',type:'money',width:130},{key:'code_purchase_amount',label:'卡密采购额',type:'money',width:130},{key:'code_count',label:'持有卡密',width:110}]
async function load(){loading.value=true;try{data.value=(await api.get(props.parentId?`/admin/agents/${props.parentId}/team`:'/agent/team',{params:{start:start.value,end:end.value,q:q.value,page:page.value}})).data}finally{loading.value=false}}
onMounted(load)
</script>
<template>
 <el-alert title="仅显示当前直属代理的汇总，不开放账号、钱包或卡密明文操作。订单和发卡采购按UTC日期统计；持有卡密为当前累计数量。金额包含演示资金，不代表利润或佣金。" type="info" :closable="false" class="spaced" />
 <section class="panel table-panel">
 <form class="toolbar spaced" @submit.prevent="page=1;load()">
 <label>开始日期（UTC）<input v-model="start" type="date" required /></label>
 <label>结束日期（UTC）<input v-model="end" type="date" required /></label>
 <label>代理昵称<input v-model="q" maxlength="80" placeholder="搜索名下代理" /></label>
 <el-button native-type="submit" type="primary" :loading="loading">查询业绩</el-button>
 </form>
 <template v-if="data">
 <p class="muted">已查询：{{data.start}} 至 {{data.end}}（UTC）</p><p role="status">当前直属代理 {{data.total}} 位 · 订单净额 {{money(data.summary.net_amount)}} · 卡密采购额 {{money(data.summary.code_purchase_amount)}}</p>
 <RecordTable :rows="data.items" :columns="columns" :loading="loading" />
 <el-pagination v-model:current-page="page" :total="data.total" :page-size="20" layout="total,prev,pager,next" @current-change="load" />
 </template>
 </section>
</template>
