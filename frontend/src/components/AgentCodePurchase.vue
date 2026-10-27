<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { api, headers, newKey } from '../api/client'
import { downloadCodes, money } from '../utils/format'
const emit=defineEmits<{ purchased: [] }>()
const open=ref(false), busy=ref(false), products=ref<any[]>([]), balance=ref(0)
const productId=ref<number>(), quantity=ref(1), validDays=ref(30), result=ref<any>()
const pending=ref<{key:string,payload:any}>()
const selected=computed(()=>products.value.find(p=>p.id===productId.value))
const total=computed(()=>(selected.value?.effective_price||0)*quantity.value)
async function start(){
  if(busy.value)return
  busy.value=true
  try {
    const [prices,wallet]=await Promise.all([api.get('/agent/prices'),api.get('/me/wallet')])
    products.value=prices.data;balance.value=wallet.data.balance;open.value=true
  } finally {busy.value=false}
}
async function submit(){
  if(busy.value)return
  if(!pending.value){
    if(!selected.value?.can_purchase)return
    try{await ElMessageBox.confirm(`采购 ${quantity.value} 张，单价 ${money(selected.value.effective_price)}，合计扣款 ${money(total.value)}。生成后请立即下载保存。`,'确认采购卡密',{type:'warning'})}catch{return}
    pending.value={key:newKey(),payload:{product_id:productId.value,quantity:quantity.value,valid_days:validDays.value,expected_unit_price:selected.value.effective_price}}
  }
  busy.value=true
  try{
    result.value=(await api.post('/agent/codes/purchase',pending.value.payload,headers(pending.value.key))).data
    pending.value=undefined;emit('purchased')
  }catch(error:any){
    // A definitive rejection did not commit a purchase. Network/5xx failures retain the request key.
    if([400,401,403,409,422].includes(error.response?.status))pending.value=undefined
  }finally{busy.value=false}
}
async function close(done:()=>void){
  if(busy.value)return
  if(result.value?.codes?.length || pending.value){
    try{await ElMessageBox.confirm(result.value?.codes?.length?'关闭后无法再次查看完整卡密，请确认已下载保存。':'请求结果尚未确认。建议先重试核对同一批次；关闭后请到库存和账单核对，避免重复采购。','关闭采购窗口',{type:'warning'})}catch{return}
  }
  result.value=undefined;pending.value=undefined;done()
}
function beforeUnload(event:BeforeUnloadEvent){if(result.value?.codes?.length||pending.value){event.preventDefault();event.returnValue=''}}
window.addEventListener('beforeunload',beforeUnload)
onBeforeUnmount(()=>window.removeEventListener('beforeunload',beforeUnload))
async function guard(){
  if(busy.value)return false
  if(result.value?.codes?.length || pending.value){
    try{await ElMessageBox.confirm('离开前请下载完整卡密；若请求结果未确认，请先核对库存和账单。','确认离开',{type:'warning'})}catch{return false}
  }
  return true
}
onBeforeRouteLeave(guard)
onBeforeRouteUpdate(guard)
</script>
<template>
  <el-button type="primary" :loading="busy" :disabled="busy" @click="start">余额采购卡密</el-button>
  <el-dialog v-model="open" title="余额采购卡密" width="min(94vw,650px)" :before-close="close" :close-on-click-modal="false" :close-on-press-escape="false">
    <template v-if="result">
      <el-alert :title="result.notice" :type="result.replayed?'warning':'success'" :closable="false" />
      <p>批次 {{result.batch_id}} · {{result.quantity}} 张 · 已扣款 {{money(result.charged_amount)}}</p>
      <template v-if="result.codes?.length">
        <pre class="code-preview">{{result.codes.join('\n')}}</pre>
        <el-button type="primary" @click="downloadCodes(result.codes,result.batch_id)">导出 TXT</el-button>
        <el-button @click="downloadCodes(result.codes,result.batch_id,true)">导出 CSV</el-button>
      </template>
    </template>
    <form v-else @submit.prevent="submit">
      <el-alert title="按你的实际采购价扣款并预留库存。客户兑换时不会再次扣款；完整卡密只交付一次。" type="info" :closable="false" />
      <p>当前可用余额 {{money(balance)}}</p>
      <label>商品<el-select v-model="productId" :disabled="busy||!!pending" placeholder="选择套餐">
        <el-option v-for="p in products" :key="p.id" :value="p.id" :disabled="!p.can_purchase||p.stock<1" :label="`${p.name}（${money(p.effective_price)} / 张，库存 ${p.stock}）`" />
      </el-select></label>
      <label>采购数量<el-input-number v-model="quantity" :disabled="busy||!!pending" :min="1" :max="500" :precision="0" /></label>
      <label>有效天数<el-input-number v-model="validDays" :disabled="busy||!!pending" :min="1" :max="365" :precision="0" /></label>
      <p>合计 {{money(total)}} <span v-if="total>balance" class="muted">余额不足，请先充值</span><router-link v-if="total>balance" to="/me/wallet" class="inline-link">去我的钱包 →</router-link></p>
      <el-alert v-if="pending" title="请求结果尚未确认，重试将核对同一批次，不会重复扣款。" type="warning" :closable="false" />
      <el-button native-type="submit" type="primary" :loading="busy" :disabled="!pending&&(!selected?.can_purchase||quantity>selected.stock||total>balance)">{{pending?'重试并核对本次采购':'确认金额并采购'}}</el-button>
    </form>
  </el-dialog>
</template>
