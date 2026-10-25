# 部署、密钥和运维

当前head：`32fb2f23c757`，24张表，包含独立monitor与站内告警；下文早期迭代的revision说明用于迁移历史参考。

## 生产前配置

1. Linux Docker + Compose，域名、合法证书和受控管理员账号。
2. `python3 scripts/init_env.py` 生成根 `.env`，妥善加密备份，权限600。`JWT_SECRET` 与 `CODE_PEPPER` 相互独立，不使用 `.env.example` 占位符。
3. 设置 `APP_ENV=production`、`DEMO_RECHARGE_ENABLED=false`、`FULFILLMENT_MODE=manual`。Compose已使用PostgreSQL/Redis。
   `MOCK_DIRECT_TOPUP_ENABLED` 在生产必须为 `false`；它只用于开发/测试演示，不接收客户 Session。
   若选择`FULFILLMENT_MODE=authorized`，还必须配置HTTPS供应商地址、令牌和Webhook密钥；当前适配器仍会失败闭锁等待正式实现，不能宣称真实充值。
   可先运行`python3 scripts/check_provider_contract.py`检查配置形状；该命令不会发送网络请求。正式接入前按[授权履约接入清单](provider-integration-checklist.md)完成沙盒验收。
4. `docker compose up --build -d`，检查 `docker compose ps`。migrate必须成功后API才启动。
5. `docker compose exec api python -m app.cli create-admin --email your-admin@example.com`，交互输入密码，不把密码写入命令行或镜像。无默认管理员。
6. 使用 `deploy/nginx-https.conf.example` 配置主机Nginx与证书；容器web仅监听127.0.0.1:8080。公网只开放443/重定向80，不公开PostgreSQL/Redis/API。
7. 下架演示套餐，校验真实商品权益、人工交付流程、资金收款规则后再营业。生产演示充值被强制禁止；真实充值/支付渠道尚未实现，资金由授权管理员核实后按带原因的调整接口记账。

正式投入真实资金前，仍需通道验签、渠道对账、退款政策、完整生产灾备切换、压力测试和真实设备验收；本机逻辑备份恢复与Chromium桌面/手机验收已完成。

## 代理/IP

Compose内API配置TRUST_PROXY=true，只能被可信Nginx访问。应用不信任任意X-Forwarded-For。Nginx总是覆盖X-Real-IP；默认按即时连接客户端IP限流，多层代理可能合并访客到一个IP，需要部署方仅对指定主机反代地址设置real_ip配置。不得设为信任0.0.0.0/0。独立运行API时默认false，不接受用户伪造限流地址。

Redis限流键有TTL，故障时敏感接口返回503；Redis持久卷保留计数，无外网端口。数据库/Redis网络只供本项目使用。服务最小配置未接入监控平台，建议采集错误率、队列积压、失败订单、对账差异、数据库容量和备份成功率；禁止在日志/监控tag中附带密码、Token、完整卡密或凭证。

## 内部资金对账

```bash
docker compose exec api python -m app.cli reconcile
```

返回 mismatched_user_ids 空数组且退出0。该命令比较全量流水与钱包余额/冻结金额，没有真实支付服务商账单核对能力。若异常先停止销售开关，调查账务，不直接SQL改余额。

## 备份与恢复

PostgreSQL（根目录，目标目录先设0700）：

```bash
mkdir -p backups
chmod 700 backups
docker compose exec -T db pg_dump -U yunguo -d yunguo -Fc > backups/yunguo.dump
chmod 600 backups/yunguo.dump
```

备份应加密后异地保存，并与应用版本、Alembic revision、CODE_PEPPER配置关联。包含卡密哈希和密码哈希的数据库仍是敏感数据。定期在**独立恢复环境**恢复验证，切勿直接覆盖现网：

```bash
# 在准备好的独立实例中，事先创建空的yunguo_restore数据库
pg_restore --no-owner --dbname=yunguo_restore backups/yunguo.dump
```

恢复环境应使用备份对应的CODE_PEPPER和应用版本，关闭演示充值/外部履约后核对余额、订单、卡密、任务与表数量，再决定切换。

仓库提供只读恢复演练脚本，使用一次性、无网络、无持久卷的临时 PostgreSQL 容器，并在结束后自动删除：

```bash
python3 scripts/verify_restore.py
```

脚本会生成临时逻辑备份，检查 Alembic 版本、24 张业务表、钱包与流水、购买/退款流水、卡密/订单关联、履约任务和未验证约束；报告默认写在源码父目录`yunguo-restore-verification.json`且权限为0600。它不恢复到现网，也不会修改业务容器。账户安全隔离项目可用 `--project yunguo-account-verify` 验证。

SQLite开发备份应使用sqlite3 backup API，不在WAL写入时直接复制单个.db；停机复制时包含相关WAL并核对。Redis用于限流，履约任务源数据位于PostgreSQL，不以Redis消息作为唯一事实来源。

## 升级与回滚

变更前备份；在独立环境运行测试与 `alembic upgrade head`。生产migrate服务执行版本迁移，不能由多个API实例同时自动建表。迁移后执行 `alembic check` 和内部对账。初始迁移支持downgrade，但会删除表和数据，仅空测试库可用；生产回滚应结合应用兼容性与备份恢复计划。

JWT_SECRET轮换使所有会话失效。CODE_PEPPER轮换会使旧卡密和公开查询凭证失效，不能当普通JWT密钥随意替换；正式运营应先实现密钥版本和迁移策略。

## 密码找回

邮件自助找回已实现；默认关闭，按[邮件配置](password-recovery.md)设置SMTP与站点origin并启动mail-worker。未配置或需要人工处理时，管理员通过可信渠道核验身份后在受控终端运行：

```bash
docker compose exec api python -m app.cli reset-password --email user@example.com
```

隐藏输入新密码，撤销旧会话并记审计。`ADMIN_PASSWORD`环境变量只为受控自动初始化预留；常规使用交互输入，不在进程参数、CI日志或仓库中保存密码。邮件找回使用短时、一次性、哈希令牌和中性响应；注册邮箱验证已实现，实际服务商投递验收仍需部署方完成。


## 代理等级版本升级

升级至 `b1f3a92d074e` 前停止应用写入并备份。该迁移将agents.level文本映射到agent_levels并设置外键，保留旧自定义等级名称和默认代理价，新增等级价/个人规则。SQLite会批量重建agents表并检查所有外键；PostgreSQL为事务式DDL。回退会移除新增价格/授权配置，应按备份恢复策略执行。

前端/API客户端需同步更新：新订单必须提交expected_amount整数分，金额不匹配409且不扣款。已有订单及幂等请求按原确认金额查询/重试。详见[代理配置说明](agent-pricing.md)。

## 邮箱验证版本升级

迁移head为`177d4c2b1376`，增加`email_verification_tokens`及`users.email_verified_at`，共20张表。旧用户验证时间保留NULL，不伪造历史验证。先备份、迁移并同步升级API/前端/mail-worker；默认两个验证开关均关闭，旧用户可继续购买。

按[邮箱验证配置](email-verification.md)提供SMTP和受控站点origin后启用`EMAIL_VERIFICATION_ENABLED=true`。只有需要限制所有未验证账号的新钱包购买时，才设置`REQUIRE_VERIFIED_EMAIL_FOR_PURCHASE=true`；包括原有管理员、代理和普通用户，需提前通知并完成补发验证。已有订单查询/原幂等请求和预付卡密兑换不受该购买门槛影响。

回退该revision会删除验证队列及验证时间，应先停写并按应用兼容性和备份策略处理。不得在生产运行测试用的升降级脚本。

## 统计报表升级

本轮只增加路由/聚合服务和前端页面，不改变表结构，head仍为`177d4c2b1376`。同步升级API和web镜像即可；Compose仍保留统一迁移步骤。API容器单独重建后，Nginx可能仍缓存旧容器地址，应同时重新创建或重启web，再确认`/api/health`返回200。只向管理员开放统计与导出；导出使用现有Redis共享限流，每账号每分钟5次。查询默认30天、最多366天，未来数据规模扩大后再依据执行计划增加专用索引/预聚合和压力验证。该报表不是支付渠道账单对账。

## 操作日志升级

同步升级API/web，无新增数据库迁移，head仍为`177d4c2b1376`。CSV导出沿用共享Redis限流，账号每分钟5次、每次最多10000条。日期和筛选越窄查询成本越低；生产大规模需按执行计划评估索引/归档。本轮未新增删除或保留期限策略，仍需自行制定日志备份与访问管理。详见[日志配置与边界](audit-logs.md)。

## 运行状态页面

API/web同步升级，无新增迁移或环境变量，head保持`177d4c2b1376`。页面等待阈值是查询参数，不持久化，不修改worker策略。仅查询业务数据库，不探测外部服务，不配置定时通知。生产仍需自行监控容器/进程存活、错误率和队列积压，见[运行状态限制](operations.md)。

## 心跳及持久告警版本

升级head`32fb2f23c757`增加4表，共24表；备份后同步部署API/web/worker/mail-worker/monitor，Compose新增monitor自动采样。根`.env.example`包含5项监控配置，默认启用站内监控，不发送外部消息。超时必须覆盖心跳/采样间隔，配置不合法拒绝启动。降级删除新增历史记录，先停写并备份。详见[升级与监控限制](monitoring.md)。

可选本机连续验收：`acceptance` profile提供acceptance-check独立容器，不默认随生产栈启动。先创建源码父目录的`yunguo-mvp-acceptance`目录并赋予容器appuser（当前UID1000）写权限，复用构建后的API镜像运行`docker compose --profile acceptance up -d --no-build acceptance-check`。脚本只读HTTP和数据库，报告写该目录；默认8小时/60秒，退出不自动重启，不挂载Docker socket。勿将报告目录挂到凭据目录。

恢复演练只验证逻辑备份可读取及当前版本的数据库一致性，不启动恢复站点、不验证CODE_PEPPER实际解密/校验能力，不替代加密异地备份、时间点恢复、生产容量和故障切换演练。运行时源库仍可正常写入，恢复后的行数代表备份一致快照，不等于演练结束时源库的新行数。
