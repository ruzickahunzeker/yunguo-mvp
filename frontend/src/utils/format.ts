export const money = (v: number = 0) => new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' }).format(v / 100)
export const date = (v: string) => v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '—'
export const labels: Record<string,string> = { retail:'零售价',agent_default:'默认代理价',level:'等级价',agent_override:'专属价',unavailable:'未配置',QUEUED:'待履约', PROCESSING:'处理中', COMPLETED:'已完成', FAILED:'失败', CANCELED:'已取消', PAID:'已支付', REFUNDED:'已退款', UNUSED:'未使用', USED:'已使用', VOID:'已作废', EXPIRED:'已过期', user:'普通用户', agent:'代理商', admin:'管理员', code_purchase:'卡密采购扣款', purchase:'购买扣款', refund:'订单退款', demo_recharge:'演示充值', adjust:'人工调整', freeze:'冻结', unfreeze:'解冻' }
export function downloadCodes(codes: string[], batch: string, csv = false) {
  const content = csv ? '\uFEFFcode\r\n' + codes.join('\r\n') : codes.join('\n')
  const url = URL.createObjectURL(new Blob([content], { type: csv ? 'text/csv;charset=utf-8' : 'text/plain;charset=utf-8' }))
  const link = document.createElement('a'); link.href = url; link.download = `${batch}.${csv ? 'csv' : 'txt'}`; link.click(); URL.revokeObjectURL(url)
}
