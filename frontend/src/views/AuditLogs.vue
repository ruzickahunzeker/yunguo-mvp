<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api/client'
import { date } from '../utils/format'
import RecordTable from '../components/RecordTable.vue'
const today=new Date(),earlier=new Date(today)
earlier.setUTCDate(earlier.getUTCDate()-29)
const filters=reactive({start:earlier.toISOString().slice(0,10),end:today.toISOString().slice(0,10),actor_id:'',action:'',target:''})
const applied=ref<Record<string,string>>({}),snapshot=ref<number|null>(null),rows=ref<any[]>([]),total=ref(0),page=ref(1)
const loading=ref(false),exporting=ref(false),ready=ref(false),error=ref(''),exportError=ref(''),detail=ref<any>(null)
let requestId=0
const invalid=computed(()=>!filters.start||!filters.end||filters.start>filters.end||(Date.parse(filters.end)-Date.parse(filters.start))/86400000>=366)
const columns=[{key:'id',label:'日志ID',width:90},{key:'actor_id',label:'操作人ID',width:110},{key:'action',label:'操作类型',width:200},{key:'target',label:'目标',width:190},{key:'detail',label:'详情',width:240},{key:'created_at',label:'时间',type:'date',width:190}]
async function load(){
 const current=++requestId;loading.value=true;error.value='';ready.value=false
 try{
  const{data}=await api.get('/admin/audit-logs',{params:{...applied.value,page:page.value,...(snapshot.value!==null?{snapshot_id:snapshot.value}:{})}})
  if(current!==requestId)return
  rows.value=data.items;total.value=data.total;snapshot.value=data.snapshot_id;ready.value=true
 }catch{if(current===requestId){rows.value=[];total.value=0;error.value='日志加载失败，请重新查询。'}}
 finally{if(current===requestId)loading.value=false}
}
async function search(){
 if(invalid.value)return
 applied.value={start:filters.start,end:filters.end,...(filters.actor_id?{actor_id:filters.actor_id}:{}),...(filters.action?{action:filters.action}:{}),...(filters.target?{target:filters.target}:{})}
 snapshot.value=null;page.value=1;exportError.value='';await load()
}
async function exportCSV(){
 exporting.value=true;exportError.value=''
 const ceiling=snapshot.value
 try{
  const result=await api.get('/admin/audit-logs/export',{params:{...applied.value,snapshot_id:ceiling},responseType:'blob'})
  const url=URL.createObjectURL(result.data),link=document.createElement('a')
  link.href=url;link.download=`audit-logs-${ceiling}.csv`;link.click();URL.revokeObjectURL(url)
 }catch(e:any){exportError.value=e.response?.status===413?'日志超过10000条，请缩小范围后重新查询并导出。':'日志导出失败，请稍后重试。'}
 finally{exporting.value=false}
}
onMounted(search)
</script>
<template>
<div class="section-heading"><div><p class="eyebrow">YUNGUO / AUDIT</p><h1>操作日志</h1><p class="muted">筛选关键操作记录，核查操作人、目标与时间。</p></div><el-button :disabled="!ready||loading||total>10000" :loading="exporting" @click="exportCSV">导出日志 CSV</el-button></div>
<section class="panel audit-filters"><form @submit.prevent="search"><label>开始日期（UTC）<input v-model="filters.start" type="date" required /></label><label>结束日期（UTC）<input v-model="filters.end" type="date" required /></label><label>操作人 ID<input v-model="filters.actor_id" type="number" min="1" step="1" placeholder="全部操作人" /></label><label>操作类型（精确）<input v-model="filters.action" maxlength="60" placeholder="例如 products.save" /></label><label>目标包含<input v-model="filters.target" maxlength="100" placeholder="目标ID或文本" /></label><el-button type="primary" native-type="submit" :disabled="invalid" :loading="loading">查询日志</el-button></form><p v-if="invalid" class="form-error" role="alert">请选择开始不晚于结束、最多366天的日期范围。</p></section>
<el-alert class="spaced" title="导出当前已查询条件下的全部匹配日志，最多10000条；超出时请缩小范围。CSV包含操作详情，请妥善保管。新增记录请重新查询。" type="info" :closable="false" />
<el-alert v-if="error||exportError" :title="error||exportError" type="error" :closable="false" role="alert" />
<p v-if="ready" role="status" class="muted audit-period">查询范围：{{applied.start}} 至 {{applied.end}} · UTC · 日志 ID 上界 {{snapshot}} · 共 {{total}} 条</p>
<section class="panel table-panel"><RecordTable :rows="rows" :columns="columns" :loading="loading"><el-table-column label="查看" width="110"><template #default="{row}"><el-button link type="primary" @click="detail=row">查看详情</el-button></template></el-table-column></RecordTable><el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="total,prev,pager,next" :disabled="loading" @current-change="load" /></section>
<el-dialog :model-value="!!detail" @close="detail=null" title="操作日志详情" width="min(94vw,700px)"><template v-if="detail"><dl><dt>日志 ID / 操作人 ID</dt><dd>{{detail.id}} / {{detail.actor_id}}</dd><dt>操作类型</dt><dd>{{detail.action}}</dd><dt>目标</dt><dd>{{detail.target}}</dd><dt>时间</dt><dd>{{date(detail.created_at)}}</dd></dl><pre class="audit-detail">{{detail.detail||'无附加详情'}}</pre></template></el-dialog>
</template>
<style scoped>
.audit-filters form{display:flex;flex-wrap:wrap;align-items:end;gap:16px}.audit-filters label{flex:1;min-width:165px;margin:0}.audit-period{margin:22px 0}.audit-detail{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.8;background:#f5f7f6;padding:18px;border-radius:8px}dd{margin:5px 0 18px;overflow-wrap:anywhere}dt{color:#6b827c;font-size:12px}
</style>
