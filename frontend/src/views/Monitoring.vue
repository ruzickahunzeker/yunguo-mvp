<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import { date } from '../utils/format'
import RecordTable from '../components/RecordTable.vue'
const loading=ref(false),error=ref(''),data=ref<any>(null),rows=ref<any[]>([]),total=ref(0),page=ref(1),status=ref('active'),busy=ref<number|null>(null)
const history=ref<any[]>([]),historyId=ref<number|null>(null),historyPage=ref(1),historyTotal=ref(0)
const serviceNames:Record<string,string>={fulfillment:'履约worker',mail:'邮件worker',monitor:'监控进程'}
const workerNames:Record<string,string>={RECENT:'近期有心跳',STALE:'心跳超时',MISSING:'未收到心跳',STARTING:'启动宽限期',UNKNOWN:'尚未建立监控基线',NOT_REQUIRED:'当前配置不要求运行'}
const names:Record<string,string>={FULFILLMENT_STALE:'履约等待超过阈值',ORDER_ATTENTION:'失败或取消订单',RETRY_EXHAUSTED:'执行次数耗尽',MAIL_FAILED:'邮件投递失败',MAIL_PAUSED:'邮件队列暂停',WORKER_STALE:'worker心跳异常'}
const scopeNames:Record<string,string>={platform:'平台',password_reset:'密码找回',email_verification:'邮箱验证',fulfillment:'履约worker',mail:'邮件worker'}
const states:Record<string,string>={OPEN:'待确认',ACKNOWLEDGED:'已确认',RESOLVED:'已恢复'}
const actions:Record<string,string>={OPENED:'首次触发',REOPENED:'再次触发',ACKNOWLEDGED:'人工确认',RESOLVED:'自动恢复'}
const columns=[{key:'title',label:'告警规则',width:200},{key:'scope_label',label:'范围',width:130},{key:'status_label',label:'状态',width:120},{key:'count',label:'当前数量',width:110},{key:'occurrences',label:'发生轮次',width:110},{key:'last_seen_at',label:'最近触发',type:'date',width:190},{key:'resolved_at',label:'恢复时间',type:'date',width:190}]
let generation=0
async function load(){
 const current=++generation;loading.value=true;error.value=''
 try{
  const [monitor,alerts]=await Promise.all([api.get('/admin/operations/monitor'),api.get('/admin/operations/alerts',{params:{status:status.value,page:page.value}})])
  if(current!==generation)return
  data.value=monitor.data;rows.value=alerts.data.items.map((item:any)=>({...item,title:names[item.code]||item.code,scope_label:scopeNames[item.scope]||item.scope,status_label:states[item.status]}));total.value=alerts.data.total
 }catch{if(current===generation){data.value=null;rows.value=[];error.value='监控数据加载失败，请刷新重试。'}}
 finally{if(current===generation)loading.value=false}
}
async function acknowledge(row:any){
 let note=''
 try{note=(await ElMessageBox.prompt('请填写核查或跟进说明。确认不会处理订单、资金或关闭异常。','确认告警',{inputValidator:v=>!!v&&v.trim().length>=3&&v.trim().length<=200||'请填写3–200个字符'})).value}catch{return}
 busy.value=row.id
 try{await api.post(`/admin/operations/alerts/${row.id}/acknowledge`,{note,expected_occurrences:row.occurrences});await load()}
 finally{busy.value=null}
}
async function loadHistory(){
 const{data}=await api.get(`/admin/operations/alerts/${historyId.value}/events`,{params:{page:historyPage.value}})
 history.value=data.items.map((e:any)=>({...e,action_label:actions[e.action]||e.action}));historyTotal.value=data.total
}
async function showHistory(row:any){historyId.value=row.id;historyPage.value=1;history.value=[];await loadHistory()}
onMounted(load)
</script>
<template>
<div class="section-heading"><div><p class="eyebrow">YUNGUO / MONITORING</p><h1>监控与告警</h1><p class="muted">查看进程近期心跳和持久化站内告警，记录跟进与恢复。</p></div><el-button :loading="loading" @click="load">刷新监控</el-button></div>
<el-alert title="心跳仅表示进程最近完成过循环，不代表SMTP、外部渠道或整个系统健康；监控进程停止后不会继续采样。本站不发送外部告警通知。" type="info" :closable="false" class="spaced" />
<el-alert v-if="error" :title="error" type="error" :closable="false" />
<template v-if="data"><p role="status" class="muted">监控{{data.enabled?'已启用':'已关闭'}} · 最近采样 {{date(data.last_checked_at)}} · 采样间隔 {{data.interval_seconds}} 秒 · 履约阈值 {{data.stale_minutes}} 分钟</p>
<section class="panel"><h3>worker 心跳</h3><div class="monitor-workers"><article v-for="worker in data.workers" :key="worker.service"><h4>{{serviceNames[worker.service]}}</h4><el-tag :type="worker.status==='RECENT'?'success':['STALE','MISSING'].includes(worker.status)?'danger':'info'">{{workerNames[worker.status]}}</el-tag><p>最近心跳：{{date(worker.last_seen_at)}}</p><small class="muted">超时阈值 {{worker.timeout_seconds}} 秒</small></article></div></section>
<section class="panel table-panel"><div class="section-heading compact"><h3>站内告警</h3><label>告警状态<select v-model="status" :disabled="loading" @change="page=1;load()"><option value="active">全部未恢复</option><option value="OPEN">待确认</option><option value="ACKNOWLEDGED">已确认</option><option value="RESOLVED">已恢复</option></select></label></div><p class="muted">同一规则持续异常只保留一条告警；恢复后再次发生会重新打开并增加轮次。确认不会阻止后续恢复或再次触发。</p><RecordTable :rows="rows" :columns="columns" :loading="loading"><el-table-column label="操作" width="160"><template #default="{row}"><el-button v-if="row.status==='OPEN'" link type="primary" :loading="busy===row.id" @click="acknowledge(row)">确认告警</el-button><el-button link @click="showHistory(row)">事件记录</el-button></template></el-table-column></RecordTable><el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="total,prev,pager,next" :disabled="loading" @current-change="load" /></section>
<router-link to="/admin/operations" class="solid-link">前往运行状态排查订单 →</router-link>
</template>
<el-dialog :model-value="historyId!==null" @close="historyId=null" title="告警事件记录" width="min(94vw,900px)"><RecordTable :rows="history" :columns="[{key:'action_label',label:'事件',width:130},{key:'actor_id',label:'操作人ID',width:100},{key:'note',label:'说明',width:230},{key:'created_at',label:'时间',type:'date',width:190}]"/><el-pagination v-model:current-page="historyPage" :total="historyTotal" :page-size="20" layout="total,prev,pager,next" @current-change="loadHistory" /></el-dialog>
</template>
<style scoped>
.monitor-workers{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.monitor-workers article{padding:18px;border-radius:8px;background:#f5f7f6}.monitor-workers p{font-size:12px;line-height:1.8;margin-top:16px}select{padding:10px;border:1px solid var(--el-border-color);border-radius:7px;background:white;font:inherit;color:inherit}@media(max-width:760px){.monitor-workers{grid-template-columns:1fr}}
</style>
