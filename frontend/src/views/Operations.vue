<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import { date } from '../utils/format'
import RecordTable from '../components/RecordTable.vue'
const loading=ref(false),error=ref(''),data=ref<any>(null),rows=ref<any[]>([]),total=ref(0),page=ref(1)
const minutes=ref(30),appliedMinutes=ref(30),kind=ref('attention')
const kinds=[{value:'attention',label:'失败或取消待处理'},{value:'stale',label:'超过等待阈值'},{value:'exhausted',label:'重试次数耗尽'},{value:'refundable',label:'钱包订单待退款审核'},{value:'queued',label:'全部等待履约'}]
const columns=[{key:'order_id',label:'订单编号',width:270},{key:'product_name',label:'商品',width:180},{key:'amount',label:'订单金额',type:'money',width:130},{key:'fulfillment_status',label:'履约状态',type:'status',width:120},{key:'attempts',label:'已执行次数',width:120},{key:'updated_at',label:'任务更新时间',type:'date',width:190}]
const alertText:Record<string,string>={FULFILLMENT_STALE:'等待履约超过阈值',ORDER_ATTENTION:'失败或取消订单待处理',RETRY_EXHAUSTED:'失败任务已耗尽执行次数',MAIL_FAILED:'有效邮件任务投递失败',MAIL_PAUSED:'邮件功能已关闭，仍有到期待发送记录'}
const purposeText:Record<string,string>={password_reset:'密码找回',email_verification:'邮箱验证'}
const modeText:Record<string,string>={manual:'人工履约模式',mock:'模拟履约模式',authorized:'授权履约待接入'}
let sequence=0
async function load(){
 const current=++sequence;loading.value=true;error.value=''
 try{
  const [summary,orders]=await Promise.all([api.get('/admin/operations/summary',{params:{stale_minutes:appliedMinutes.value}}),api.get('/admin/operations/orders',{params:{kind:kind.value,stale_minutes:appliedMinutes.value,page:page.value}})])
  if(current!==sequence)return
  data.value=summary.data;rows.value=orders.data.items;total.value=orders.data.total
 }catch{if(current===sequence){data.value=null;rows.value=[];total.value=0;error.value='运行状态加载失败，请重新查询。'}}
 finally{if(current===sequence)loading.value=false}
}
async function search(){if(!Number.isInteger(Number(minutes.value))||minutes.value<1||minutes.value>10080)return;appliedMinutes.value=Number(minutes.value);page.value=1;await load()}
onMounted(load)
</script>
<template>
<div class="section-heading"><div><p class="eyebrow">YUNGUO / OPERATIONS</p><h1>运行状态</h1><p class="muted">查看履约和邮件队列，定位需要人工处理的订单。</p></div><el-button :loading="loading" @click="load">刷新状态</el-button></div>
<el-alert class="spaced" title="队列摘要不代表worker进程存活，也不执行自动重试、退款或通知。人工模式下的等待由管理员处理；邮件计数未逐一校验账号及凭证有效性。" type="info" :closable="false" />
<el-alert v-if="error" :title="error" type="error" :closable="false" role="alert" />
<section class="panel ops-controls"><form @submit.prevent="search"><label>等待阈值（分钟）<input v-model.number="minutes" type="number" min="1" max="10080" step="1" required /></label><el-button native-type="submit" type="primary" :loading="loading">应用阈值</el-button></form></section>
<template v-if="data"><p class="muted" role="status">采样时间：{{date(data.observed_at)}} · {{modeText[data.fulfillment_mode] || '未知履约模式'}} · 等待阈值 {{data.stale_minutes}} 分钟</p>
<div class="stats-grid" v-loading="loading"><div class="stat-card"><span>等待履约</span><strong>{{data.fulfillment.queued}}</strong><small>最早任务更新 {{date(data.fulfillment.oldest_queued_at)}}</small></div><div class="stat-card"><span>超过等待阈值</span><strong>{{data.fulfillment.stale}}</strong><small>{{data.fulfillment_mode==='mock'?'检查积压及worker日志':'检查人工处理进度'}}</small></div><div class="stat-card"><span>失败或取消待处理</span><strong>{{data.fulfillment.attention}}</strong><small>含卡密订单，需核实交付</small></div><div class="stat-card"><span>钱包订单待退款审核</span><strong>{{data.fulfillment.refundable}}</strong><small>已退款订单不重复计入</small></div></div>
<section class="panel"><h3>排查提示</h3><p v-if="!data.alerts.length" class="muted">当前摘要未触发排查规则；不代表服务或账务已全面正常。</p><el-alert v-for="(alert,i) in data.alerts" :key="i" class="ops-alert" :title="`${alertText[alert.code]}${alert.purpose?' · '+purposeText[alert.purpose]:''}：${alert.count} 条`" :type="alert.severity" :closable="false" /></section>
<section class="panel table-panel"><h3>邮件投递摘要</h3><p class="muted">到期待发送不等于必定可投递；worker会进一步检查账号、版本及凭证。失败仅统计尚未过期且未消费的任务。</p><div class="ops-mail"><article v-for="(stats,purpose) in data.mail" :key="purpose"><h4>{{purposeText[String(purpose)]}} · {{stats.enabled?'已启用':'已关闭'}}</h4><p>队列记录 {{stats.queued}} · 到期待发送 {{stats.due}} · 延后重试 {{stats.waiting}}</p><p>有效投递失败 {{stats.failed}} · 过期待清理 {{stats.expired_queued}}</p></article></div></section>
<section class="panel table-panel"><div class="section-heading compact"><h3>订单排查</h3><label>排查类别<select v-model="kind" :disabled="loading" @change="page=1;load()"><option v-for="item in kinds" :key="item.value" :value="item.value">{{item.label}}</option></select></label></div><RecordTable :rows="rows" :columns="columns" :loading="loading"><el-table-column label="处理" width="120"><template #default="{row}"><router-link :to="{path:'/admin/orders',query:{q:row.order_id}}">处理订单 →</router-link></template></el-table-column></RecordTable><el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="total,prev,pager,next" :disabled="loading" @current-change="load" /></section>
</template>
</template>
<style scoped>
.ops-controls{margin-top:22px}.ops-controls form{display:flex;gap:16px;align-items:end;flex-wrap:wrap}.ops-controls label{max-width:250px;margin:0}.ops-alert{margin-bottom:12px}.ops-mail{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.ops-mail article{padding:18px;background:#f5f7f6;border-radius:8px}.ops-mail p{line-height:1.8;font-size:12px}select{max-width:100%;padding:10px;border:1px solid var(--el-border-color);border-radius:7px;background:white;font:inherit;color:inherit}@media(max-width:760px){.ops-mail{grid-template-columns:1fr}}
</style>
