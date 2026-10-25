import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-loading.css'
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-message-box.css'
import './style.css'
import App from './App.vue'
import router from './router'
// Register directives only. Template components and API styles are imported by Vite.
import { ElLoading } from 'element-plus'
createApp(App).use(createPinia()).use(router).use(ElLoading).mount('#app')
