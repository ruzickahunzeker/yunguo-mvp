<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'
const route=useRoute(),router=useRouter(),auth=useAuth()
const token=ref('')
const loading=ref(false),message=ref(''),invalid=ref(false)
// Same-page email links reuse this component. Capture each new fragment, then
// remove it without clearing the credential held only in component memory.
watch(()=>route.hash,hash=>{
 if(!hash)return
 token.value=new URLSearchParams(hash.slice(1)).get('token')||''
 message.value='';invalid.value=false
 void router.replace({path:route.path,hash:'',query:{}})
},{immediate:true})
async function verify(){
 if(loading.value || !token.value)return
 loading.value=true
 try{const{data}=await api.post('/auth/verify-email',{token:token.value});token.value='';message.value=data.message;if(auth.user)await auth.load()}
 catch(error:any){if(error.response?.status===400 || error.response?.status===422){token.value='';invalid.value=true}}
 finally{loading.value=false}
}
</script>
<template><div class="narrow-page recovery-page"><p class="eyebrow">VERIFY YOUR EMAIL</p><h1>确认你的注册邮箱</h1><p class="muted">验证只确认邮箱所有权，不会登录或切换账号。请确认这是你本人发起的操作。</p><section class="panel"><template v-if="message"><el-alert :title="message" type="success" :closable="false" show-icon role="status"/><router-link :to="auth.user?'/me/profile':'/login'" class="solid-link recovery-return">{{auth.user?'返回个人资料':'前往登录'}} →</router-link></template><template v-else-if="!auth.features.email_verification_enabled"><el-alert title="邮箱验证暂未开放，请联系管理员。" type="info" :closable="false"/><router-link to="/login" class="recovery-return">返回登录</router-link></template><template v-else-if="!token || invalid"><el-alert :title="invalid?'验证链接无效或已过期，请登录后重新申请':'链接缺少验证凭证，请从最新邮件打开完整链接。'" type="warning" :closable="false" role="alert"/><router-link to="/me/profile" class="solid-link recovery-return">登录并重新申请 →</router-link></template><template v-else><p class="muted">点击下方按钮完成验证。链接仅能使用一次；重新申请后，旧邮件中的链接会失效。</p><el-button type="primary" size="large" class="full" :loading="loading" @click="verify">确认验证邮箱 →</el-button><p class="hint">刷新本页后，请重新从邮件打开链接。请勿转发验证邮件。</p></template></section></div></template>
