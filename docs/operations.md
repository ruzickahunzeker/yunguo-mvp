# 运行状态与异常订单排查

后台新增「运行状态」`/admin/operations`。只向管理员开放，无写接口，不自动重试、退款或发送通知。本轮无数据库结构变化，head仍为`177d4c2b1376`。此前订单、钱包和审计规则继续生效。

## 队列指标

履约聚合与列表以订单和履约任务的关联记录为基础，不承担缺失任务、状态不一致等数据库修复检查。等待阈值默认30分钟，可选择1–10080分钟，仅作用于本次查询，不修改系统配置或worker调度。

| 字段 | 定义 |
|---|---|
| queued | 当前已付款、订单与任务均为QUEUED的任务数 |
| stale | queued中，任务updated_at早于或等于采样时间减阈值的数量 |
| oldest_queued_at | queued中最早的任务更新时间，不等于订单创建时间；无记录为null |
| attention | 当前已付款、履约FAILED或CANCELED的订单数，包含钱包和卡密 |
| exhausted | 当前已付款、履约FAILED且任务attempts≥3的数量 |
| refundable | 当前已付款、来源wallet、履约FAILED或CANCELED的数量；仅供退款审核，不自动决定退款 |

已退款和已完成订单不进入待处理列表；卡密失败进入attention，但不进入钱包退款候选。完成退款后，重新查询才更新指标。任务更新后等待时长重新计算，包括管理员重试操作。重试仍受原有3次执行上限约束。

人工模式出现stale时仅给信息提示，因为任务本来等待人工处理；模拟模式下stale给警告，提醒检查积压与worker日志。失败待处理/重试耗尽给警告。没有触发规则只表示当前这些指标没有命中，不能认定整体服务或资金正常。

## 邮件计数

按password_reset与email_verification分别输出：

- enabled：对应邮件功能开关，不输出SMTP配置或任何凭据。
- queued：QUEUED且未消费的记录数，含已过期记录。
- due：QUEUED、未消费、尚未过期、attempts<3、next_attempt_at≤采样时间。
- waiting：相同条件，但next_attempt_at晚于采样时间，通常处于退避。
- expired_queued：QUEUED、未消费、expires_at≤采样时间，等待worker取消/维护清理。
- failed：FAILED、未消费且尚未过期的任务；已过期失败记录不计此项。

这些是**存储状态计数**，不逐个加入用户表校验账号禁用、版本变化、邮箱是否改变等条件。due不等于实际一定能投递，worker领取后仍会校验；failed不等于所有记录都应补发。功能开启且failed>0时提示投递失败，关闭且due>0时提示队列暂停。仅看摘要不会发邮件；当前没有批量重发/重置邮件任务状态的后台接口。用户可按原流程重新申请最新链接。

不返回邮箱、完整令牌、哈希、请求键、SMTP错误详情或其他秘密。不会为了显示运行状态连接外部SMTP，也不调用外部通知服务。

## API

```http
GET /api/admin/operations/summary?stale_minutes=30
Authorization: Bearer <管理员JWT>
```

返回`observed_at/stale_minutes/fulfillment_mode/fulfillment/mail/alerts`。告警是页面内按规则计算的排查提示，每项含固定code、severity、count，邮件项还有purpose。不是定时通知服务。

```http
GET /api/admin/operations/orders?kind=attention&stale_minutes=30&page=1&page_size=20
Authorization: Bearer <管理员JWT>
```

kind允许queued/stale/attention/exhausted/refundable，默认attention。默认20条，最多100，按任务更新时间、任务ID从旧到新排序；返回items/total/page/page_size。字段仅含订单ID/商品快照名称/来源/金额/支付与履约状态/任务状态/执行次数/更新时间；不返回内部错误原文、查询凭证或请求键。分页不提供历史快照。

操作人必须管理员（未登录401，普通用户/代理403），非法类别、阈值和分页422。数据库异常沿用503；敏感响应no-store。summary的履约聚合来自一条SELECT，邮件两种用途各自聚合；摘要和明细来自不同请求，实时任务变化可能产生暂时差异，刷新可更新，不宣称跨请求一致快照。

## 处理路径与限制

列表「处理订单」跳转`/admin/orders?q=<订单ID>`，订单管理初始化搜索条件并读取后端数据，管理员查看日志后按原有确认/原因流程重试、取消或退款。运行状态查询没有订单操作权的旁路，所有处理继续在订单API校验状态、事务、钱包与审计。

这是只读的运营排查入口，**本页不提供worker心跳/进程存活检测；新增独立[监控与告警](monitoring.md)页显示近期循环心跳和持久化站内告警。仍无定时邮件/短信/Webhook告警、SLO、跨机监控或自动修复**。人工模式允许等待超过阈值，实际处置优先级需运营判断。钱包一致性仍用CLI reconcile；真实支付对账、服务商履约和外部邮件投递验收仍待接入。数据规模扩大后需要执行计划/索引评估和压力验收。

后端测试覆盖空状态、角色权限、阈值首尾、模式提示差异、卡密/钱包/退款分类、排序分页、邮件退避/过期/开关、敏感字段隔离、只读不变量和真实退款后的移出。桌面/手机浏览器验证人工异常→调整阈值→退款候选→跳转带订单ID搜索→实际退款→刷新后移出异常列表。
