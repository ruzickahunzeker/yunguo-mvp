import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../stores/auth'
const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/', component: () => import('../views/Store.vue') },
  { path: '/products', component: () => import('../views/Store.vue') },
  { path: '/products/:id', component: () => import('../views/Store.vue') },
  { path: '/login', component: () => import('../views/Auth.vue') },
  { path: '/verify-email', component: () => import('../views/VerifyEmail.vue') },
  { path: '/forgot-password', component: () => import('../views/PasswordRecovery.vue') },
  { path: '/reset-password', component: () => import('../views/PasswordRecovery.vue') },
  { path: '/register', component: () => import('../views/Auth.vue') },
  { path: '/redeem', component: () => import('../views/Redeem.vue') },
  { path: '/lookup', component: () => import('../views/Redeem.vue') },
  { path: '/me/:section', component: () => import('../views/Member.vue'), meta: { auth: true } },
  { path: '/agent/:section', component: () => import('../views/Agent.vue'), meta: { auth: true, role: 'agent' } },
  { path: '/admin/monitoring', component: () => import('../views/Monitoring.vue'), meta: { auth: true, role: 'admin' } },
  { path: '/admin/operations', component: () => import('../views/Operations.vue'), meta: { auth: true, role: 'admin' } },
  { path: '/admin/audit-logs', component: () => import('../views/AuditLogs.vue'), meta: { auth: true, role: 'admin' } },
  { path: '/admin/code-purchase-reports', component: () => import('../views/CodePurchaseReports.vue'), meta: { auth: true, role: 'admin' } },
  { path: '/admin/reports', component: () => import('../views/Reports.vue'), meta: { auth: true, role: 'admin' } },
  { path: '/admin/agents', component: () => import('../views/AgentManagement.vue'), meta: { auth: true, role: 'admin' } },
  { path: '/admin/:section', component: () => import('../views/Admin.vue'), meta: { auth: true, role: 'admin' } },
  { path: '/:pathMatch(.*)*', redirect: '/' }
] })
router.beforeEach(async to => {
  const auth = useAuth()
  if (!auth.ready) await auth.load()
  if (to.meta.auth && !auth.user) return { path: '/login', query: { redirect: to.fullPath } }
  if (to.meta.role === 'admin' && auth.user?.role !== 'admin') return '/'
  if (to.meta.role === 'agent' && auth.user?.role !== 'agent') return '/'
})
export default router
