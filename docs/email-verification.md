# 注册邮箱所有权验证

注册成功后，启用功能时在同一事务创建邮件投递任务；注册仍会登录，不等待SMTP。未验证用户可在「个人资料」补发邮件。验证页需点击确认按钮，不会因邮件扫描器只访问链接而验证；公开验证不登录、不切换账号、不改变角色、不撤销当前JWT。

## 配置

默认关闭，编辑本地`backend/.env`，Compose编辑根`.env`：

```dotenv
EMAIL_VERIFICATION_ENABLED=true
REQUIRE_VERIFIED_EMAIL_FOR_PURCHASE=false
EMAIL_VERIFICATION_MINUTES=60
PUBLIC_BASE_URL=https://your-domain.example
SMTP_HOST=your-smtp-host
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your-smtp-account
SMTP_PASSWORD=your-app-password
SMTP_FROM=noreply@your-domain.example
```

SMTP与[密码找回](password-recovery.md)共用配置，可独立开启任一功能。origin不允许路径/查询/片段/用户密码；生产必须HTTPS及SMTP TLS，校验证书。购买门槛开启时必须同时开启邮箱验证。有效期允许5–1440分钟。实际发件域名、SPF/DKIM/DMARC和外部投递由部署方验收；本次测试仅使用本地SMTP接收器，未发送外部邮件。

升级并启动：

```bash
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/python -m app.tasks.mail_worker
```

Compose已有mail-worker；修改配置后重新创建API和mail-worker，确保数据库和密钥一致。

## 凭证与限流

链接`/verify-email#token=...`的片段不传给HTTP服务器。页面读取后移除地址栏和路由历史中的凭证，只留组件内存；同页打开新邮件会重新读取并清除新片段，刷新后需从邮件重新打开。

数据库只存凭证哈希与必要任务元数据。HMAC用途域与密码重置隔离，绑定随机ID、用户ID、账号版本及当前邮箱哈希，不能交叉消费。补发立即使旧链接失效；过期、已消费、账号停用/版本改变或邮箱改变都不可验证。事务锁用户并条件更新一次性凭证，同时写验证时间与审计。

补发需登录，按IP每5分钟5次、按账号跨IP每15分钟3次；公开消费按IP每5分钟10次。生产使用共享Redis，故障关闭。worker持久投递，失败30/60秒退避，共最多3次，仅记录固定错误类别。进程崩溃可能重复发送同一链接，消费仍只有一次有效；SMTP发送期间持有任务行锁，SQLite写请求可能等待，生产使用PostgreSQL。

过期超过7天的记录可每日清理：

```bash
docker compose exec -T api python -m app.cli cleanup-verifications
```

## 购买策略与旧用户

迁移`177d4c2b1376`增加第20张表及可空`users.email_verified_at`。旧用户全部保留NULL；验证开关和购买门槛默认false，升级不自动阻止旧账号购买。开启验证后，旧用户可登录并补发。

开启购买门槛后，所有未验证角色的新钱包购买返回403，并在扣库存、扣余额、创建订单之前中止。前端同步禁用购买按钮并显示提示。已有订单和同键同金额的幂等重放、历史流水和预付卡密公开兑换仍可使用。没有邮箱变更流程；未来实现时必须同步清空验证状态并更新账号版本。

## 验收

12项后端用例在SQLite和PostgreSQL执行，覆盖默认关闭、注册排队、补发/过期/单次与并发、账号和邮箱绑定、可选购买门槛与幂等保留、邮件用途隔离和重试、限流/错误脱敏及生产配置。Chromium桌面/手机验证真实本地SMTP收信→补发使旧链接失效→新链接验证→当前会话保留→完成购买。结果见[验证记录](verification.md)。
