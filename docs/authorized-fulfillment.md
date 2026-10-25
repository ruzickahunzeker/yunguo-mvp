# 授权服务商履约适配器

系统新增 `FULFILLMENT_MODE=authorized` 配置分支，但当前只提供**失败闭锁占位适配器**：它会让订单保持 `QUEUED`，不会调用任意 URL、不会假装充值成功，也不会接收 Session/Cookie/密码。

生产启用前必须同时提供 HTTPS `FULFILLMENT_PROVIDER_URL`、`FULFILLMENT_PROVIDER_TOKEN` 和 `FULFILLMENT_WEBHOOK_SECRET`，并完成供应商合同、接口、签名回调、幂等键、退款、重试、对账和数据保留评审。当前代码不会因为配置了 URL 就自动发送请求；必须在取得正式接口文档后实现独立 provider client、outbox、签名验证和 reconciliation。

未取得授权服务商资料时继续使用 `manual` 或 `mock`（仅演示）模式。`authorized` 不代表真实履约已接入。
