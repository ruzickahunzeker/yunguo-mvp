# 邮件密码找回

## 行为

登录页「忘记密码」进入 `/forgot-password`。开启功能后，存在、未知和已停用邮箱都返回相同202与相同提示，不在请求内连接SMTP。真实有效账号创建数据库持久化投递任务；未配置功能时统一503，前端提示联系管理员。

链接默认20分钟过期，仅可使用一次；重新申请会作废旧链接。密码重置与凭证消费在同一事务，锁住账号并条件更新凭证，确保并发只有一方成功。重置增加token_version，撤销所有旧JWT，并记审计。禁用账号、CLI改密、退出/改密或权限变更后，原版本链接不可用。

数据库保存 `password_reset_tokens`（第16张表）：随机ID、user FK、auth_version、token_hash、expires/used、投递状态、次数、下次时间、固定错误类别。链接令牌由独立域HMAC从随机ID/用户/版本重建，库中不保存完整令牌或邮件正文；邮件worker可以重建同一凭证用于投递重试。CODE_PEPPER必须按敏感密钥备份。

链接格式 `/reset-password#token=...`，片段不传到HTTP服务器；页面读取后立即移除地址栏片段，再请求API。令牌仅保留内存，不保存localStorage/sessionStorage。刷新后需重新从邮件打开链接。邮件内容不收集第三方账号、Session或Cookie。

## 本地配置

编辑 `backend/.env`（Compose编辑根 `.env`），不要把SMTP凭据提交到仓库：

```dotenv
PASSWORD_RESET_ENABLED=true
PUBLIC_BASE_URL=http://localhost:5173
SMTP_HOST=your-smtp-host
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your-smtp-account
SMTP_PASSWORD=your-app-password
SMTP_FROM=noreply@your-domain.example
PASSWORD_RESET_MINUTES=20
```

PUBLIC_BASE_URL必须是受运维配置的完整站点origin，不能有路径、查询、片段或用户名密码，不根据请求Host拼链接。Compose默认站点端口8080，应将PUBLIC_BASE_URL设置为实际站点地址。账号密码必须同时配置或同时为空（后者仅适用于授权的中继/本地接收器）。

API和邮件进程都需加载相同配置与数据库：

```bash
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/python -m app.tasks.mail_worker
```

Compose内包含 `mail-worker` 服务；启用或更新SMTP配置后重建/重新创建API及mail-worker。默认关闭，不会自动连接外部邮箱。当前会话只测试本地SMTP接收器，没有实际发送外部邮件。

## 生产要求

`APP_ENV=production` 且开启功能时强制 PUBLIC_BASE_URL=https、SMTP_SECURITY=starttls/ssl；SMTP证书使用默认CA验证。`none`只允许开发环境的本地测试场景。

发件域名的SPF/DKIM/DMARC、服务商授权、限额与投递结果由部署方配置和验收。应用支持真实SMTP适配，但没有验证任何实际服务商的投递成功率。

## 限流、队列与维护

申请按IP每5分钟5次、按邮箱HMAC跨IP每15分钟3次限流；消费接口每IP每5分钟10次。生产依赖共享Redis，失败关闭。本地进程计数各自保留独立窗口，避免短窗口清理误删长窗口计数。

worker每次锁定一个到期任务（PostgreSQL SKIP LOCKED）；失败按30/60秒退避，总计最多3次，然后FAILED；过期/旧版本任务取消。只保存 `SMTP_DELIVERY_FAILED`，不保存异常正文，避免SMTP错误泄露邮箱、凭证和密码。SMTP发送最多等待10秒，MVP持有任务行锁期间发送；数据库崩溃可能导致重发同一个一次性链接，不会重复重置密码。SQLite该期间会暂时阻塞写请求，因此生产应使用PostgreSQL。

运维可只查询状态/数量排查队列，不输出token_hash、用户邮箱或完整令牌。失败后用户可在限流窗口后重新申请；没有无限自动重试。

每日至少运行一次过期记录清理（仅删除过期超过7天的重置记录，不影响审计日志）：

```bash
docker compose exec -T api python -m app.cli cleanup-resets
```

邮件恢复与[注册邮箱验证](email-verification.md)分别配置，使用用途隔离的令牌和独立持久表，共用mail-worker和SMTP。没有MFA和邮件变更工作流。生产规模扩大后可将任务认领和SMTP发送拆成带租约的短事务，并增加运营告警。
