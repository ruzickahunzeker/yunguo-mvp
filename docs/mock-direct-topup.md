# 模拟直充（仅开发/测试）

为了演示 Step 3 → 队列 → 结果的界面流程，系统提供 `POST /api/agent/direct/mock`。它只接受商品、确认金额和形如 `mock-customer-<hex>` 的模拟引用，不接受 Session、Cookie、密码、银行卡或任意客户凭据；服务端会复用代理购买事务并追加模拟直充事件。

该入口只有在 `APP_ENV=development/test` 且 `MOCK_DIRECT_TOPUP_ENABLED=true` 时开放。`APP_ENV=production` 强制拒绝，并且配置校验禁止生产启用此开关。生产配置不包含入口的前端导航，也不应把测试引用当作真实客户账号。

真实环境需要改为官方页面跳转或经授权的服务商 API/Webhook；不要把客户 Session 作为替代字段添加到这个接口。模拟引用和操作审计只用于本地测试，不代表真实充值或订阅开通。
