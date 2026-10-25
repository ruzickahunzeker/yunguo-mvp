# 云果 · 卡密兑换与代理分销平台

本轮本机验收入口及步骤见[2026-10-17验收说明](docs/acceptance.md)。

可独立部署的第一阶段 MVP：Vue 3 + TypeScript + Element Plus + Pinia + FastAPI + SQLAlchemy + Alembic。支持 SQLite 本地运行及 PostgreSQL/Redis Docker 部署。当前没有真实支付或订阅开通。

## 已交付

- 邮箱注册登录、Argon2 密码、JWT、退出和改密使旧令牌失效、账号禁用、服务端角色授权。
- 商品列表/详情/搜索/分页、商品上下架、库存、分类、排序、代理采购价。
- 钱包购买、演示充值、资金流水、管理员调整/冻结/解冻、失败或取消订单退款。
- 批量卡密生成、TXT/CSV 一次性交付、哈希存储、预留库存、有效期、单独/批量作废、并发安全公开兑换。
- 用户订单、携独立凭证的公开订单查询、订单日志、人工处理/取消/退款/有限重试。
- 持久化数据库任务队列、独立模拟 worker、人工履约模式。
- 用户中心、可配置等级/专属价的单级代理中心、管理工作台、统计趋势、权限管理、业务开关与审计日志。
- 注册邮箱验证、登录后补发、一次性邮件链接、可选的验证后购买策略；邮件功能默认关闭。
- 管理员交易统计报表：UTC日期/来源/商品筛选、每日与商品汇总、成交/退款/净额、带审计的CSV导出。
- 操作日志日期/操作人/类型/目标筛选、完整详情、带ID上界的分页与CSV导出。
- 运行状态：履约积压/重试耗尽、邮件投递摘要、异常订单筛选与处理跳转。
- worker近期心跳、持久化站内告警、人工确认及自动恢复/再触发记录。
- 24 张表、显式 Alembic 迁移、管理员及种子 CLI、对账 CLI、测试、Docker Compose、Nginx 和 HTTPS 示例。

完整分析和交付清单见 [需求差距与任务](docs/requirements.md)、[架构/ER/一致性](docs/architecture.md)、[API 文档](docs/api.md)、[测试记录](docs/verification.md)、[部署运维](docs/deployment.md)。

下一阶段的上线判断、服务商接入闸门和优先级见[下一阶段建议](docs/next-steps.md)。

## 本地运行

要求 Python 3.11+（验证使用 3.12）和 Node **22+**（UI 依赖要求）。在项目根目录运行：

```bash
python3 scripts/init_env.py
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/python -m app.cli seed
../.venv/bin/python -m app.cli create-admin --email admin@example.com
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

管理员密码通过隐藏交互输入，无默认账号密码。初始化脚本不会覆盖已有 `.env`，自动生成相互独立的随机密钥，配置文件不纳入版本控制。根 `.env` 用于 Compose；`backend/.env` 用于本地后端。运行后端命令时必须位于 `backend`。

另开终端运行持久化履约队列：

```bash
cd backend
../.venv/bin/python -m app.tasks.worker
```

如已启用邮件找回或邮箱验证，再开一个终端在 `backend` 执行 `../.venv/bin/python -m app.tasks.mail_worker`。

再开终端运行前端：

```bash
cd frontend
npm ci
npm run dev
```

访问 [本地前端](http://localhost:5173)；[Swagger API](http://127.0.0.1:8000/docs)、[ReDoc](http://127.0.0.1:8000/redoc)。Vite 将 `/api` 代理到后端。设置 `FULFILLMENT_MODE=manual` 后重启 worker/API，订单改由管理员处理。只有 `DEMO_RECHARGE_ENABLED=true` 才允许演示充值。

## Docker Compose

```bash
python3 scripts/init_env.py
# 检查根 .env；首次演示默认开发模式和模拟履约
# 使用未被占用的 WEB_PORT（默认8080），仅监听回环地址
docker compose up --build -d
# 不创建默认管理员；交互式输入密码
docker compose exec api python -m app.cli create-admin --email admin@example.com
```

打开 [本地容器前端](http://localhost:8080)。`migrate` 一次性执行迁移与种子，成功后 API/worker 启动；web 等待 API 健康。数据库、Redis、API 不发布主机端口。

Compose 会初始化演示商品；生产启用前请下架/改为真实授权商品，配置生产环境并按部署文档加 HTTPS。`APP_ENV=production` 会拒绝 SQLite、缺失 Redis 或演示充值开启的配置。

## 手动验收路径

1. 注册普通用户，在钱包演示充值至少 14900 分。
2. 浏览演示套餐，确认购买，在「我的订单」查看队列/完成记录及日志。
3. 管理员生成卡密，立即导出 TXT/CSV；退出登录后在公开兑换页兑换。
4. 保存订单编号与查询凭证，在「订单查询」刷新进度。订单号本身不能查询隐私数据。
5. 设置人工模式；创建订单，管理员标记失败，再退款，检查钱包流水和审计。
6. 管理员将用户设为代理，重新登录，检查专属价格与管理员分配的卡密库存。

## 自动化验证

```bash
cd backend
../.venv/bin/pytest -q
../.venv/bin/alembic check
../.venv/bin/python -m app.cli reconcile
cd ../frontend
npm run build
npm audit
```

PostgreSQL 测试可设置 `TEST_DATABASE_URL`。**仅使用专门测试库，数据库名必须以 `_test` 结尾；测试会删除并重建全部业务表。** 默认使用临时 SQLite，绝不读取生产库执行测试。

## 明确的阶段边界

尚未接入真实支付与回调对账、外部授权履约回调、多级代理、佣金结算、全面运营风控。注册邮箱验证可按[验证邮件配置](docs/email-verification.md)启用；验证后购买策略默认关闭。密码遗忘可按[邮件找回配置](docs/password-recovery.md)启用 SMTP，一次性重置链接由独立持久化邮件队列投递；未配置时由运维核验后运行 `python -m app.cli reset-password --email ...`，会失效全部旧令牌。单级代理报表展示平台采购数据，不虚构线下销售利润。

完整卡密只在生成时返回，之后无法重新导出；交付响应丢失应核对批次、作废并重新生成。卡密作废/退款/取消不会自动恢复可售库存，避免将可能已交付权益重复销售，由管理员核实后调整库存。`CODE_PEPPER` 必须随加密备份保管，丢失会使已有卡密和公开查询凭证无法校验。

本项目未抓取或复制参考站源码，也未使用用户第三方 Session/Cookie 或非公开订阅接口。

## 浏览器端到端测试

```bash
cd frontend
npm ci
npx playwright install --with-deps chromium
npm run test:e2e
```

测试先生产构建，再启动临时 SQLite、仅监听本机的 SMTP 接收器及预览服务，用 Chromium 的桌面和手机尺寸验证购买、兑换、后台、代理、完整邮件重置、邮箱验证后购买及报表退款、操作日志筛选/CSV导出及运行状态异常退款。需要本机 8800–8803 端口空闲；不使用现有业务库或真实邮箱。测试框架详见 [验收记录](docs/verification.md)。

## 代理等级与独立定价

后台「代理管理」可配置等级、等级商品价、指定代理专属价和单商品采购权限。新采购需提交确认金额，改价后旧确认请求不会扣款。默认等级与原代理价被保留，详见[代理配置与迁移说明](docs/agent-pricing.md)。API客户端升级时必须为`POST /api/orders`增加整数分`expected_amount`字段。

## 交易统计报表

后台「统计报表」按UTC订单创建日汇总，支持最多366天、来源与商品ID筛选、零值补齐、商品分页、每日CSV导出。成交/退款使用订单金额快照，卡密兑换不计收入，净额不代表利润；退款按当前状态归回原订单日期。详见[报表口径与API](docs/reports.md)。

操作日志已支持按条件查询和CSV导出，最多10000条，超限拒绝、导出记审计并处理电子表格公式字符；详见[操作日志说明](docs/audit-logs.md)。

后台「运行状态」提供只读的履约/邮件队列摘要与异常订单排查，区分人工等待和模拟模式积压；不代表worker进程存活、不自动通知或退款。详见[运行状态口径](docs/operations.md)。

## 心跳与站内告警

Compose新增monitor服务，本地需另开终端运行`python -m app.tasks.monitor`。按[监控部署与状态机](docs/monitoring.md)配置间隔和超时，后台「监控与告警」查看近期循环心跳、确认告警及恢复历史。仅站内告警，不会自动发送外部消息。迁移head为`32fb2f23c757`，共24张表。

账户操作增加跨IP账号登录限流、改密共享限流及会话变更的行锁重验，资料/改密/退出均记脱敏审计，见[账户安全说明](docs/account-security.md)。

账户安全新版在独立8081本机验收环境运行，原8080与整夜巡检保留；入口、凭据文件和服务操作见[验收说明](docs/acceptance.md)。

Step 3 的直充演示仅在开发/测试开关 `MOCK_DIRECT_TOPUP_ENABLED=true` 下接受模拟引用，不接收客户 Session；生产必须使用官方页面跳转或授权服务商 API，详见[模拟直充说明](docs/mock-direct-topup.md)。

授权服务商接入要求见[履约接入清单](docs/provider-integration-checklist.md)。

代理已支持在卡密库存按专属采购价扣余额发卡，完整卡密一次性交付，见[代理自助发卡](docs/agent-code-purchase.md)。

管理员可配置直属代理归属，总代在「名下代理」查看隔离的订单和卡密采购汇总，见[团队归属说明](docs/agent-team.md)。

管理员「卡密采购报表」单独汇总代理发卡扣款的批次、数量和金额，支持日期/代理/商品筛选及带审计CSV，见[统计说明](docs/code-purchase-reports.md)。
