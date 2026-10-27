# 发布前收口清单

更新日期：2026-10-28（Asia/Shanghai）。当前版本仍为演示/MVP，清单通过前不得切换真实支付或真实订阅履约。

## 当前本地状态

- 分支：`main`
- 远端：`origin/main`
- 本地领先提交数量：以 `git status -sb` 为准；推送前不得改写远端历史。
- 当前模式：开发环境；`mock` 仅用于演示，`manual` 用于人工流程验证。

## 网络恢复后的执行顺序

```bash
cd /root/yunguo-mvp
git status --short
git diff --check
git push origin main
gh run list --limit 5
gh run watch <run-id>
```

CI 必须同时通过后再继续：后端测试、迁移检查、前端 Node 22 构建、桌面浏览器、移动浏览器和敏感字段检查。

## 演示环境更新

```bash
docker compose ps
docker compose up -d --build
curl -fsS http://127.0.0.1:8080/api/health
docker compose exec -T api python -m app.cli reconcile
docker compose exec -T api alembic check
```

健康响应必须明确 `status=ok`，同时记录 `mode` 和 `demo`；`reconcile` 必须返回空差异。更新前先执行逻辑备份，更新失败时按上一版本回滚并恢复备份。

## 人工验收顺序

1. 普通用户注册/登录、演示充值、购买、订单查询和账单。
2. 代理余额采购卡密、下载一次、库存尾号、账单扣款。
3. 公开兑换、重复提交、保存查询凭证、刷新进度。
4. 管理员失败/取消/重试/退款和逐项履约核验。
5. 价格调整后新旧订单金额、审计日志和报表。
6. 桌面与 Pixel 7 移动视口的横向溢出、键盘和错误提示。

## 必须阻断发布的条件

- GitHub CI 未通过或提交未推送。
- 无法完成备份恢复或 `reconcile` 有差异。
- 仍使用演示充值、mock 履约或未签约服务商。
- 缺少支付渠道验签、退款、拒付和对账资料。
- 缺少正式授权履约 API、Webhook 签名和沙盒证据。
- 需要接收客户 Session、Cookie、密码、CVV 或完整银行卡资料。

## 生产切换所需外部资料

商户主体与支付渠道、正式服务商合同/API/沙盒、商品权益与地区、价格和售后政策、HTTPS 域名、托管 PostgreSQL/Redis、密钥管理、备份存储、监控和值班安排。资料未齐时保持演示或人工模式。
