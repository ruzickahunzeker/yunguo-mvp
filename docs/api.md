# API 设计

根路径 `/api`，JSON请求响应，金额均为整数分，所有时间输出UTC时区。启动后 `/docs` Swagger 和 `/redoc` 提供参数、类型和约束；`openapi.json` 是生成的静态合同。

`Authorization: Bearer <JWT>` 由后端校验。资金/订单修改接口还需 `Idempotency-Key`：16–80位ASCII字母数字/下划线/短横线，建议浏览器 `crypto.randomUUID()`。网络超时必须用原键重试，不应生成新键。

| 方法/路径 | 权限 | 用途 |
|---|---|---|
| GET /health | 公开 | 数据库健康和演示/履约模式 |
| POST /auth/register | 公开/限流 | email,password(10–128),name；禁止传role |
| GET /auth/features | 公开 | password_reset_enabled/email_verification_enabled/require_verified_email_for_purchase三项能力开关 |
| POST /auth/forgot-password | 公开/双限流 | email；已配置时始终202中性提示，创建持久化投递任务 |
| POST /auth/reset-password | 公开/限流 | token,new_password；一次性消费并撤销旧会话 |
| POST /auth/verification/request | 登录/双限流 | 无请求体；202补发验证邮件，已验证时不重复投递 |
| POST /auth/verify-email | 公开/限流 | token（64位十六进制）；一次性验证邮箱，不登录或切换账号 |
| POST /auth/login | 公开/限流 | 返回access_token/token_type/user |
| GET/PATCH /auth/me | 登录 | 当前用户/只改name |
| POST /auth/password | 登录 | current_password,new_password；撤销全部旧会话 |
| POST /auth/logout | 登录 | 撤销全部会话 |
| GET /products | 公开 | q/category/page/page_size |
| GET /products/{id} | 公开 | 有效商品详情 |
| POST /redeem | 公开/限流/幂等 | code；返回order_id/lookup_token/两组状态 |
| POST /orders/lookup | 公开/限流 | order_id+lookup_token，错误统一404，不暴露用户和请求键 |
| POST /orders | 登录/幂等/限流 | product_id + expected_amount整数分；可选要求已验证邮箱；实时价必须等于确认金额，再从钱包扣费 |
| GET /me/orders | 登录 | 仅本人；status/q/page/page_size |
| GET /me/orders/{id}/events | 登录 | 仅本人；跨用户404 |
| GET /me/wallet | 登录 | balance,frozen,demo_recharge_enabled |
| GET /me/transactions | 登录 | 本人流水分页 |
| POST /me/wallet/demo-recharge | 登录/幂等/限流 | amount 1..1000000；需开启demo |
| GET /agent/overview | 代理/管理员 | level/order_count/purchase_amount/code_count/wallet |
| GET /agent/prices | 代理/管理员 | effective_price 后端专属价格 |
| GET /agent/codes | 代理/管理员 | 仅本人分配卡密的元数据，无完整卡密 |
| GET /admin/reports/sales | 管理员 | start/end UTC日期（含首尾，默认30天，最多366天）、source=wallet/code、product_id、page/page_size；返回summary/daily/products |
| GET /admin/reports/sales/export | 管理员/账号限流 | 相同筛选，UTF-8 BOM每日CSV和TOTAL合计、整数分、导出记审计 |
| GET /admin/operations/summary | 管理员 | stale_minutes=1..10080，默认30；返回履约/邮件队列计数及页面排查提示 |
| GET /admin/operations/orders | 管理员 | kind=queued/stale/attention/exhausted/refundable、stale_minutes、page/page_size；只读订单排查列表 |
| GET /admin/dashboard | 管理员 | 用户/订单/净交易额/有效卡密/最近订单/趋势 |
| GET /admin/users | 管理员 | q/role/page/page_size |
| PATCH /admin/users/{id} | 管理员 | active/role；撤销旧会话；禁止自降级/停用 |
| GET/POST /admin/products | 管理员 | 分页/创建；含agent_price |
| PUT /admin/products/{id} | 管理员 | 完整编辑+expected_updated_at，防止旧表单覆盖库存，金额整数分 |
| POST /admin/codes/generate | 管理员 | product_id,quantity(1..500),valid_days(1..365),owner_id?；一次性返回codes |
| GET /admin/codes | 管理员 | status/product_id/page，EXPIRED为派生状态 |
| POST /admin/codes/void | 管理员 | ids[1..500]；仅作废UNUSED，返回changed |
| GET /admin/orders | 管理员 | status/q/product_id/start/end/page |
| GET /admin/orders/{id}/events | 管理员 | 处理日志 |
| POST /admin/orders/{id}/action | 管理员 | action=complete/fail/retry/refund/cancel，note至少3字符 |
| GET /admin/wallets | 管理员 | 钱包分页 |
| GET /admin/wallets/{id}/transactions | 管理员 | 指定用户流水分页 |
| POST /admin/wallets/{id}/adjust | 管理员/幂等 | amount,note,operation=adjust/freeze/unfreeze |
| GET /admin/audit-logs | 管理员 | start/end UTC日期、actor_id、action精确、target字面包含、snapshot_id上界、page/page_size |
| GET /admin/audit-logs/export | 管理员/账号限流 | 相同筛选及上界，最多10000条，超出413；UTF-8 BOM CSV，导出记审计 |
| GET/PUT /admin/settings | 管理员 | sales_enabled/redemption_enabled布尔开关 |

分页默认20，每页最大100，响应 `{items,total,page,page_size}`。代理商品价和订单事件列表是有界用途的数组响应。管理员生成卡密最多500，生成响应 `Cache-Control: no-store`，后续只能获取元数据和尾号，不能重新导出。

例如公开兑换：

```http
POST /api/redeem
Content-Type: application/json
Idempotency-Key: 814325ca-cc3d-43a6-8904-b84028692728

{"code":"YG-<交付时的卡密>"}
```

返回 `{"order_id":"YG...","lookup_token":"...","payment_status":"PAID","fulfillment_status":"QUEUED"}`。用户必须保存凭证。

错误码：401未登录/令牌失效；403权限或演示模式不允许；404资源不存在或无访问权；409库存/余额/状态/幂等冲突；422输入不合法；429限流（Retry-After）；503数据库或共享限流服务不可用。验证错误不回显原始敏感输入，SQL错误不返回堆栈。

没有真实支付webhook或外部履约callback端点；在签名与授权方案确定后才开放，避免出现无鉴权的假回调。

新增[代理等级/指定代理价格与权限API](agent-pricing.md)，均按服务端管理员角色授权；订单价格变化返回409及X-Error-Code: PRICE_CHANGED。

用户响应增加可空UTC时间`email_verified_at`；空值代表未验证。功能关闭返回503；过期、重复或失效验证凭证统一400，输入格式错误422。验证后不撤销当前JWT。详见[邮箱验证设计与部署](email-verification.md)。

审计查询兼容原有items/total/page/page_size并增加snapshot_id，翻页与导出可沿用上界；它不构成MVCC历史快照。CSV危险公式文本加单引号，详情保留原文，详见[日志导出说明](audit-logs.md)。

监控新增GET `/admin/operations/monitor`、GET `/admin/operations/alerts?status=active&page=1`、GET `/admin/operations/alerts/{id}/events`及POST `/admin/operations/alerts/{id}/acknowledge`（note、expected_occurrences）。全部管理员授权，旧轮次或已恢复确认409；详见[监控API与口径](monitoring.md)。

账户安全：登录同时受IP与邮箱HMAC共享尝试限制；改密增加IP/账号限流，资料/改密/退出锁内重验active与token_version，审计固定说明不保存密码/昵称。超限429，会话已变化401。见[说明](account-security.md)。

## 代理余额采购卡密

`POST /api/agent/codes/purchase`，代理JWT与Idempotency-Key；请求含product_id、quantity、valid_days和expected_unit_price整数分。首次201返回batch_id、codes、quantity、charged_amount、replayed=false；同合同同键返回原批次和空codes、replayed=true。同键更换合同409。详见[发卡采购合同](agent-code-purchase.md)。

## 直属代理团队

管理员`PUT /api/admin/agents/{id}/parent`设置/解除上级，提交parent_id和必填expected_parent_id；代理`GET /api/agent/team`按当前身份读取直属团队，管理员`GET /api/admin/agents/{id}/team`读取指定团队。查询支持UTC start/end、q昵称、page/page_size，返回成员列表、总数和全局summary。详见[团队口径与权限](agent-team.md)。

管理员卡密采购报表：`GET /api/admin/reports/code-purchases`和`GET /api/admin/reports/code-purchases/export`，支持UTC start/end、agent_id和product_id，口径、10000批次上限、CSV字段及限流见[采购报表说明](code-purchase-reports.md)。
