# 代理等级、价格和商品权限

## 已完成的业务范围

管理后台「代理管理」分为代理列表与等级定价。用户角色仍为user/agent/admin，代理业务等级独立配置，不把每种等级变成一个鉴权角色。仍是单级分销关系，不计算多级佣金或线下销售利润。

- 管理员可创建、改名、排序、停用等级；旧版每个不同的agents.level文字都迁移为独立等级。
- 用户管理可授予agent角色，默认分配ID=1的等级；已有代理档案重新授予角色时保留原配置，不删除历史关系/卡密。
- 在代理列表分配启用的等级，为该等级配置商品价；可针对单个代理覆盖价格或禁止采购指定商品。
- 价格支持0元；空专属价表示继承，不是0。清除等级价继承默认代理价，清除个人规则同时恢复默认采购权限。
- 停用等级阻止其代理的新钱包采购，禁止单商品仅影响相应代理。已有订单、钱包、卡密及公开兑换不被取消。
- 定价、授权与等级变更全部记录管理员审计。

## 定价顺序

1. 指定代理+商品的非空专属价。
2. 代理所在等级+商品的等级价。
3. 原product_prices中的role=agent默认价。
4. 商品零售价。

商品已下架、等级停用、代理档案缺失或个人商品规则allowed=false均拒绝新采购，价格覆盖不能绕过权限。管理员自行购买按零售价；普通用户看不到其他代理价格。代理只能查询自己的报价，没有修改配置接口权限。

## 确认金额和幂等

`POST /api/orders`现要求：

```json
{"product_id":1,"expected_amount":1000}
```

expected_amount是页面确认时的整数分金额，必须与后端实时生效价一致。变化时返回409和`X-Error-Code: PRICE_CHANGED`，不扣库存、不生成订单、不扣钱包。前端刷新报价，让用户重新确认。**旧API客户端必须升级以提交该字段；缺失返回422，刷新旧页面即可加载新版。**

客户端不能用expected_amount指定低价。服务端重新计算价格与权限。相同幂等键对应的已创建订单必须匹配原商品、原金额与来源，否则409；如果新价格/权限后来变化，原请求用原金额与原键重试仍返回原订单，不二次收费。

浏览器将未确认完成的购买请求键与原确认金额一起保存在sessionStorage。超时后重试保持原参数；明确的价格变化拒单会清理未成交请求并刷新价格。余额不足/权限等错误不会偷偷生成新键。历史旧版请求键没有保存金额时，遇到幂等冲突应核对「我的订单」，不能盲目重复购买。

## 数据结构

本次代理迁移新增三张表，迁移时共19张业务表；后续邮箱验证迁移后共20张：

| 表 | 约束与用途 |
|---|---|
| agent_levels | id PK、name UNIQUE、active、sort、时间戳；默认ID=1为旧一级代理 |
| agent_level_prices | level/product FK、整数非负price、UNIQUE(level_id,product_id)、时间戳 |
| agent_product_rules | agent/product FK、nullable整数非负price、allowed、UNIQUE(agent_id,product_id)、时间戳 |

agents删除原level文本列，新增非空level_id外键与索引。ID=1保留为新代理默认等级；不提供删除等级接口，停用不会破坏外键和历史记录。

## 事务并发

采购锁账号并刷新当前状态/令牌版本，随后锁代理档案、共享锁等级、锁商品，读取个人/等级/默认报价并确认金额，之后原子扣库存、创建订单/履约任务和钱包流水，一次提交。

个人规则变更与等级分配也锁账号→代理档案，等级价/等级状态变更锁等级行，与采购保持一致的锁顺序。PostgreSQL使用NO KEY UPDATE允许审计与订单的外键引用，避免把非主键配置锁与外键插入锁交叉成死锁。SQLite本地模式仍采用BEGIN IMMEDIATE串行事务。

因此并发改价要么在采购前生效、旧金额请求被拒绝，要么在本笔采购后生效；不能把用户确认的800分变成600或900分后继续扣款。

## 管理接口

| 方法/路径（/api前缀） | 内容 |
|---|---|
| GET/POST /admin/agent-levels | 等级列表（最多1000）/创建 |
| PUT /admin/agent-levels/{id} | name/active/sort |
| GET /admin/agents | q/level_id/page/page_size，附等级名与状态 |
| PUT /admin/agents/{user_id}/level | level_id，只可分配启用等级 |
| GET /admin/agent-levels/{id}/prices | 商品分页及nullable level_price |
| PUT/DELETE /admin/agent-levels/{id}/prices/{product_id} | 设置price/恢复默认价 |
| GET /admin/agents/{id}/products | 商品分页、override_price、allowed与实时有效价 |
| PUT/DELETE /admin/agents/{id}/products/{product_id} | 设置{price:null或整数,allowed:bool}/恢复全部继承 |
| GET /agent/prices | 本人effective_price/price_source/can_purchase/restriction |
| GET /agent/overview | 本人level/level_id/level_active及采购统计 |

所有/admin接口仅管理员可用。列表不返回密码哈希、登录版本或其他代理的内部凭据。

## 迁移和验收

新增revision `b1f3a92d074e`，先创建等级、按旧文本回填，再替换agents列，最后创建价表/规则表。PostgreSQL重置回填后的等级ID序列，避免新建等级与历史ID冲突。SQLite批量重建时暂停迁移连接的FK检查，结束后立即执行foreign_key_check并恢复；运行应用的连接仍强制开启FK。迁移必须在停止应用写入时执行。

`scripts/check_agent_migration.py`使用专用临时库验证upgrade→downgrade→upgrade、旧自定义等级名称、钱包及agent_relations已有子外键完整。默认新建临时SQLite；PostgreSQL需MIGRATION_TEST_DATABASE_URL指向专用_test库，该脚本会清空测试schema。

回退会删除新增的等级价格与个人规则配置，代理等级名回填为旧文本。不能把迁移回退当作配置备份；生产回退应先备份。
