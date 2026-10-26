# 验证记录

2026-10-26：创建并推送私有 GitHub 仓库 `ruzickahunzeker/yunguo-mvp`。推送前核对 Git 工作区、忽略规则、当前 161 个跟踪文件与历史 blob；未发现数据库、备份、私钥或令牌。远端 `main` 与本地提交 `64f40ab` 一致，首次 GitHub Actions [Checks 运行](https://github.com/ruzickahunzeker/yunguo-mvp/actions/runs/40339779746) 的 backend 和 browser 作业均成功。历史记录中“尚未设置远端”的描述反映当时状态，已由此条更新。

2026-10-26：新增稳定 SKU、订阅月数及订单下单权益快照。新订单保存下单时的名称、SKU、说明、订阅月数、金额；商品后续编辑不会改写历史订单。新增测试覆盖重复 SKU、不可变 SKU、旧客户端省略新字段，以及商品编辑后的快照稳定性。隔离测试完整后端 **171/171** 通过；Node 22 前端构建和空白 SQLite 迁移检查通过。部署前备份演示库，迁移并更新 8080 的 API/Web；部署后健康返回 `mock/demo`、钱包对账差异为空，PostgreSQL `alembic check` 无遗漏。详见[实现说明](product-sku-snapshots.md)。

2026-10-26：新增可按商品启用的逐项履约核验。订单快照“要求逐项核验”；Card 付款、订阅权益生效、停止续费、移除支付方式四步依次记录，未全部核验时后端拒绝人工完成；mock worker 跳过这类订单。隔离测试数据库中完整后端测试 **170/170** 通过；Node 22 前端构建通过；空白 SQLite 数据库迁移到最新版本后 `alembic check` 显示无遗漏操作。部署前已备份演示 PostgreSQL 数据库，随后迁移并更新 8080 的 API、worker、Web；宿主机健康接口返回 `{"status":"ok","mode":"mock","demo":true}`，所有 Compose 服务运行，钱包对账差异为空。功能边界和验收步骤见[逐项履约核验](fulfillment-checks.md)。

最新验证日期：2026-10-26（Asia/Shanghai）；此前迭代记录保留。项目为新建实现。

## 2026-10-26 12 小时巡检终态

- 新版独立只读巡检于北京时间 2026-10-25 14:53 至 2026-10-26 02:53 完成，`state=completed`，721 次采样全部通过、0 失败；最终履约和 monitor 心跳均为 `RECENT`。报告在源码外 `/root/yunguo-mvp-acceptance/soak-20261025.json`。
- 完成后复核 8080/8081 健康接口正常、8080 主要容器运行、`reconcile` 返回 `mismatched_user_ids=[]`。A 阶段演示闭环与稳定性验收完成；此结果只覆盖演示资金与 mock 履约，不代表真实支付或订阅开通。
- 公开兑换与订单查询页在健康接口报告 `mode=mock` 时明确提示「订单完成表示模拟履约，不代表真实订阅已开通」。Node 22 前端构建通过，隔离浏览器桌面/手机兑换场景 **2 passed**；新版 Web 已部署到 8080，兑换页 HTTP 200、健康接口正常，容器前端产物包含提示。此页面更新发生在 12 小时巡检完成后，巡检不覆盖新版页面。
- 登录后的用户、代理和管理工作台在 `mode=mock` 时显示演示资金/履约提示；桌面与手机的用户购买及代理采购场景 **4 passed**。运行状态页现区分 `manual`、`mock`、`authorized`，避免将授权模式误写成模拟模式；运行状态桌面/手机场景 **2 passed**。Node 22 构建通过，8080 Web 已更新且健康接口正常。本轮仅改前端展示，未新增业务交易。
- 根据原始 PRD 的商品、订单、钱包、代理和履约要求，新增首个真实商品决策单：明确 SKU 权益、两条销售路径、价格/退款、正式服务商回执及验收证据；待业务与渠道资料填写，不将演示套餐改为真实商品。此轮为文档更新，未改运行服务。

## 2026-10-25 复审与门禁修正

- 新增生产配置回归：`APP_ENV=production` 拒绝 `FULFILLMENT_MODE=mock`，避免模拟 worker 在生产把订单伪装成已完成；授权服务商地址必须为干净 HTTPS 地址，token 和 webhook secret 至少 32 个字符。
- 授权履约专项测试 **7 passed**；开发 Compose 继续使用 `FULFILLMENT_MODE=mock`，不影响本机演示。
- 代理余额不足时，卡密采购窗口提供「去我的钱包」入口；采购接口仍由后端强制限制为代理角色。
- 管理员不再显示或进入代理中心采购入口；代理账单将卡密采购流水转换为商品、数量、单价和批次说明。
- 修正代理账单读取采购单价的字段为 `contract.unit_price`，避免显示 `¥NaN/张`；说明列改称「交易说明」，无法解析的旧备注仍显示原文。
- Node 22 容器前端构建通过，8080 Web 已重新部署；`/agent/bills` 返回 HTTP 200，`/api/health` 返回 `status=ok`、`mode=mock`、`demo=true`。本轮未新增交易。
- 兑换和钱包购买首次成功回执现在直接返回商品、金额、创建时间，兑换页无需先刷新才能看完整订单信息；同一幂等键重试返回一致的 UTC 时间格式。订单与代理采购定向回归 **39 passed**，8080 API 已更新且健康接口正常。
- 8080/8081 健康检查均为 `status=ok`；8080 `reconcile` 返回 `mismatched_user_ids=[]`。新版独立只读巡检容器 `yunguo-soak-20261025` 已启动，首轮采样通过，12 小时最终结果须查看源码外 `/root/yunguo-mvp-acceptance/soak-20261025.json`，不可提前宣称全程通过。
- A 阶段继续执行：隔离临时数据库中的桌面/手机关键浏览器验收 **4 passed**，新增断言首次兑换回执立即显示商品与 ¥0.00，以及代理账单显示采购单价和「交易说明」；未改动 8080 业务数据。8080 `alembic check` 无待迁移操作，`reconcile` 无差异；无网络临时 PostgreSQL 恢复演练通过，24 张业务表与订单、卡密、钱包关联检查均无差异，临时容器已删除。恢复报告位于源码外 `/root/yunguo-restore-verification-20261025.json`。巡检进行中，最近核对为 328/328 采样通过，最终结果待完成。
- 最新隔离临时数据库的完整 Chromium 回归 **32 passed**（桌面与手机各 16 项），覆盖采购、兑换、账单、报表、账户、邮箱、监控等主路径；测试未向 8080 写入业务数据。源码已建立本地 Git 基线 `7318c5d`，忽略本机 `.env`、数据库、备份、密钥和测试产物；尚未设置远端仓库。
- 完整后端 SQLite 回归 **168 passed**（约 2 分 10 秒）；新增 `.github/workflows/checks.yml`，为后续私有 GitHub 仓库配置 Python 3.12 后端测试与 Node 22/Chromium 桌面、手机浏览器测试。工作流 YAML 解析和本地对应命令已验证；因当前尚无 GitHub 远端，尚未产生云端 CI 运行记录。巡检继续运行，最近核对为 370/370 通过。

## 2026-10-18 持续运行复核

- 8080 主入口已按既有 Compose 配置重新构建并启动，8081 对照环境保持运行；两套健康接口均返回 `status=ok`、`mode=mock`、`demo=true`。
- 8080 `alembic check` 无迁移差异，钱包对账返回 `mismatched_user_ids=[]`；本轮未修改业务数据。
- 当前仍为本机演示资金与模拟履约，真实服务商、Session、银行卡资料及第三方代操作均未接入。

## 2026-10-19 持续运行复核

- 8080 Web 容器短暂未响应，已重启 Web 容器后恢复；8080/8081 健康接口均通过。
- 宿主机服务商配置检查通过，当前 `FULFILLMENT_MODE=mock`，不进行任何外部服务商网络请求。

## 结果

| 检查 | 实际结果 |
|---|---|
| SQLite自动化 | **158 passed**完整回归；含卡密采购报表16项 |
| PostgreSQL 16自动化 | 最近全量141项通过；本轮新旧报表26项定向通过，临时专用库 |
| SQLite迁移 | upgrade head成功，alembic check无差异，seed和reconcile成功 |
| PostgreSQL迁移 | 在空测试schema中upgrade→check→downgrade base→upgrade全通过，seed和reconcile成功 |
| TypeScript/Vite | vue-tsc --noEmit 和 Vite 6.4.4 生产构建成功；使用Node22 |
| 依赖检查 | pip check无冲突；最终npm audit全部生产/开发依赖**0项已知漏洞** |
| Compose配置 | docker compose config --quiet通过 |
| Docker镜像 | Python3.12、Node22多阶段、Nginx镜像构建成功 |
| Compose完整启动 | PostgreSQL16/Redis7/API健康，migrate退出0，worker/web正常 |
| 真实HTTP闭环 | Nginx首页与SPA路由、CSP、健康检查、CLI管理员、注册/登录、演示充值、幂等购买、卡密生成/重复兑换、worker完成、权限隔离通过 |
| 容器账务校验 | CLI reconcile返回mismatched_user_ids空数组 |
| Chromium E2E | **32 passed**，桌面16项/手机16项，含卡密采购报表筛选及CSV |
| 新迁移数据保留 | 旧版→新版→旧版→新版，订单/库存/钱包流水哨兵数据与对账通过 |
| Python静态编译 | compileall成功 |

## 原交易25项用例范围

1. 注册、登录、改密与退出撤销旧令牌。
2. 后端管理员/代理权限、本人订单隔离、敏感字段不返回。
3. 禁用账号阻断旧令牌和再次登录。
4. 登录失败限流与严格整数金额校验（拒绝bool/浮点）。
5. 注册不能指定角色，管理员不能停用/降级自己。
6. 缺失或非法幂等键拒绝。
7. 重复购买仅一订单一次扣款，模拟worker消费一次。
8. 余额不足回滚库存、订单、任务与流水。
9. 卡密哈希存储、重复请求返回原凭证、其他请求拒绝、查询凭证保护。
10. 6个并发请求兑换同一卡密，仅1个成功。
11. 过期/作废/商品下架卡密拒绝且无错误订单。
12. 演示充值相同键不重复记账，改变金额冲突。
13. 失败订单重复退款只入账一次，已退款不可重试。
14. 冻结/解冻影响可用余额，流水汇总与余额一致。
15. 代理采购价和生成卡密预留库存正确。
16. 并发购买不能透支钱包。
17. 业务开关在后端生效。
18. 重试3次上限，已完成订单禁止自动退款。
19. 并发同一购买幂等键仅一个订单、一次扣款。
20. 最后一份库存的购买/铸卡竞争仅一方成功。
21. 并发退款仅一笔退款流水。
22. manual模式worker不消费，管理员可完成。
23. 卡密列表和审计不暴露完整卡密/哈希/请求键。
24. production配置拒绝SQLite/缺失Redis/演示充值。
25. 管理员旧商品表单不能恢复并发扣减的库存，刷新版本后可编辑。

`backend/tests/conftest.py` 默认创建临时SQLite文件，PostgreSQL测试必须显式提供以`_test`结尾的专用库。每例重建业务表；不要指向任何需要保留的数据。

## 可复现容器验收

在全新的、开启演示充值且mock履约的Compose栈中：

```bash
.venv/bin/python scripts/smoke_compose.py
```

脚本会创建随机QA账号和少量演示交易；仅用于一次性测试环境，不会打印或保存密码/Token/完整卡密。最终交付时停止了本次验证容器，保留Compose数据卷；QA账号已禁用并撤销令牌。专用PostgreSQL16临时容器已删除。源码无默认管理员，使用CLI自行创建。

## 验证限制与待办

- 已增加Chromium桌面/手机尺寸的真实浏览器自动化；未进行真实Android/iOS设备、Safari/Firefox和完整屏幕阅读器验收。
- Element Plus已按需引入；入口JS从1116.21KB降至237.54KB（约79%），gzip从370.82KB降至91.48KB。该数值是入口包，不是所有页面资源总量。当前构建无大包警告。
- Starlette TestClient使用httpx有一条弃用提示，未影响当前113项测试；未来迁移httpx2后调整测试依赖。
- 没有为真实支付/外部授权履约做任何成功声明；这些渠道不存在于第一阶段实现中。
- 未进行生产高负载、跨可用区故障、外部支付对账、真实服务商邮件投递、证书部署或完整生产灾备切换；已完成本机PostgreSQL逻辑备份隔离恢复演练。
- npm审计仅反映检查时的漏洞库，不代表后端或产品完成全面安全审计。

## 密码找回迭代（历史记录）

- **12/12 Chromium端到端通过**，在1440×1000桌面与Pixel 7手机尺寸各执行6个场景，最终整套约41秒。使用生产构建、临时SQLite、真实本地SMTP收件器；没有外部邮件发送。
- 场景：公开首页与键盘进入登录；注册→充值→确认购买→订单日志→流水；管理员生成→TXT导出→关闭确认→公开兑换→刷新后幂等重放→凭证查询；商品编辑及全部管理页；代理价与管理员页面隔离；SMTP找回→片段/路由历史清除→密码一致性检查→重置→旧会话失效→新密码登录→同链接不可复用。
- 每个浏览器场景断言无JavaScript页面异常；重点页面断言整页无横向溢出。手机号型为Chromium模拟，不代表真实手机系统验收。
- 截图已人工查看：首页[桌面](screenshots/home-desktop.png)/[手机](screenshots/home-mobile.png)，管理后台[桌面](screenshots/dashboard-desktop.png)/[手机](screenshots/dashboard-mobile.png)。手机首页浮层层级已修正，截图禁用过渡动画避免误判。
- 新增13项后端用例覆盖：开关关闭；未知/停用邮箱中性响应；哈希令牌与持久队列；一次性消费/审计/旧JWT撤销；重发废旧/过期错误一致；账号版本变化；并发单赢家；投递一次；失败脱敏、退避和3次上限；过期/版本无效不投递；邮箱跨IP限流；生产TLS/origin约束；错误不回显token；独立长短限流窗口。部分用例同时覆盖多项不变量。
- PostgreSQL16从旧revision `67a520308412` 升到 `6cdb7ffa6ccd`，再回退旧revision并升级，新建的凭证表可回退，原有用户、订单、商品库存与钱包流水保持一致，内部对账通过。
- 新版Compose升级现有数据卷成功；mail-worker默认关闭邮件功能，页面路由/API开关/503关闭响应通过；交易烟测与对账再次通过。`alembic current`为新head，`alembic check`无模型差异。
- 增量文件：`services/password_reset.py`、`services/mailer.py`、`tasks/mail_worker.py`、`PasswordResetToken`及迁移、`views/PasswordRecovery.vue`、`tests/test_password_reset.py`、`frontend/e2e/`、`playwright.config.ts`、`scripts/e2e_server.py`、`scripts/package_source.py`与邮件配置文档；更新认证、限流、CLI、路由、构建配置和Compose。

复现浏览器测试：安装Python依赖及Node22/npm依赖后，在frontend运行`npx playwright install --with-deps chromium`和`npm run test:e2e`。8800–8803仅供临时夹具，若已有服务占用则失败，不复用/改动其他服务。固定测试密码仅存在于临时测试数据，生产种子不会创建这些账号。Playwright不记录trace/video或失败页面截图，避免重置凭证进入长期产物；源码打包排除test-results。

## 代理配置迭代（历史记录）

- SQLite与PostgreSQL16完整套件均 **51 passed**。新增13项涵盖：管理员权限；等级创建/更新/唯一性；默认价→等级价→个人价优先级与恢复；0元有效价；禁止采购无资金/库存副作用；停用等级与分配校验；旧确认金额拒单及原请求幂等重放；金额严格类型；不同代理隔离；无效目标/负数拒绝；分页与审计；停用等级后已有卡密仍能兑换；个人价格和等级价的并发修改不改变已确认订单金额。
- Chromium桌面/手机完整套件均通过，共 **14 passed**，最终整套约72秒。新增场景实际通过管理页面创建等级、设置650分等级价、给指定代理设置500分专属价、购买后钱包从10000分变9500分；后台禁止该商品后按钮不可用，直接POST购买也返回403。等级选择和采购开关同时验证原生键盘操作。
- 新增页面截图：[代理定价桌面](screenshots/agent-pricing-desktop.png)、[代理定价手机](screenshots/agent-pricing-mobile.png)。重点页面无整页横向溢出，宽表格在容器内滚动。
- 两种数据库完成旧版→新版→旧版→新版迁移，保留自定义旧等级名、钱包及agent_relations已有子外键；PostgreSQL回填后的等级序列可继续正常新建等级；alembic check无差异。
- 实际Compose已升级到head `b1f3a92d074e`，Nginx/API/worker正常；购买、幂等、卡密生成兑换、履约与钱包对账再次通过；最终镜像成功构建。
- 新增代码：`services/pricing.py`、`api/agents_admin.py`、3个模型及迁移、`views/AgentManagement.vue`、`tests/test_agent_pricing.py`、`scripts/check_agent_migration.py`。更新采购金额契约、报价/概览、路由、角色展示、事务锁及API文档。
- 不包含真实渠道支付、真实订阅履约、线下转售价/利润或多级佣金。配置等级属于单级代理的价格分组，不代表已实现多级分销。

截图复查后的手机表格修正：代理列表和定价表在宽度≤760px时取消固定操作列，避免覆盖价格输入与权限开关；桌面继续固定操作栏。最终生产构建和对应浏览器套件再次验收，最终截图已更新。

## 邮箱所有权验证迭代（历史记录）

- SQLite **63 passed**（约61秒），PostgreSQL16 **63 passed**（约105秒）；新增12项验证开关、哈希与一次性/并发凭证、邮箱/账号版本绑定、补发/过期、购买门槛与无副作用、原订单幂等保留、历史/预付兑换、SMTP队列重试和用途隔离、限流/脱敏、配置约束。
- 最终Chromium完整套件 **16 passed**（约78秒），桌面和手机各8项。新场景使用本地SMTP收到注册邮件、补发、旧链接拒绝、新链接验证、URL及路由历史清除、当前会话保留、已验证状态、购买成功和钱包90元断言。桌面/手机截图已复查：[桌面](screenshots/email-verification-desktop.png)、[手机](screenshots/email-verification-mobile.png)。没有外部邮件发送。
- 浏览器回归发现同页打开新的邮件片段会复用组件，现验证页与密码重置页均监听新片段并重置页面状态，移除地址中的凭证，同时保留内存凭证用于显式确认；最终16项包含该场景。
- SQLite/PostgreSQL均完成`6cdb7ffa6ccd→head→6cdb7ffa6ccd→head`，保留旧用户、代理等级、500分钱包/流水及agent_relations子外键，旧用户验证时间为NULL；alembic check无模型差异。历史订单/库存的保留测试记录见上轮，不将本轮新增哨兵夸大为全量数据迁移演练。
- 实际Compose已升至`177d4c2b1376`，共20张业务表；Nginx SPA、默认三项邮件/购买开关false、验证API关闭时503通过。完整交易烟测、worker履约和账务对账通过，最终生产镜像构建成功。
- 生产构建入口JS约240.50KB（gzip92.47KB），无大包警告；Python编译和依赖一致性检查通过。邮箱验证和强制验证购买默认关闭，旧用户升级不会自动被限制。
- 新增`services/email_verification.py`、`EmailVerificationToken`及迁移、`views/VerifyEmail.vue`、`tests/test_email_verification.py`与[配置说明](email-verification.md)；更新共享邮件队列、认证、采购前置检查、个人资料、邮件提示、CLI清理和部署环境变量。

真实支付/服务商履约、多级佣金以及外部SMTP服务商投递仍需后续接入和验收。

## 交易统计报表迭代（历史记录）

- 最终Chromium完整套件 **18 passed**（约84秒），桌面/手机各9项；真实137分购买→失败→退款→报表按日期/来源/商品筛选→CSV下载并校验总计通过，未应用筛选不影响导出、非法日期范围禁查及整页无横向溢出均通过。截图已人工复查：[桌面](screenshots/reports-desktop.png)、[手机](screenshots/reports-mobile.png)。宽表在容器内横向滚动。

- SQLite与PostgreSQL16完整后端套件均 **73 passed**，新增10项覆盖报表/导出服务端权限、退款/0元订单及履约计数、UTC首尾日期、非UTC数据库连接、来源/商品筛选、补零/默认范围/366天上限、商品分页与全局合计、CSV整数金额/筛选元数据/敏感字段隔离、导出审计及账号共享限流。CSV筛选元数据确定后，两种数据库的10项报表测试再次通过。
- 最终生产构建通过，入口JS约241.89KB（gzip92.91KB），报表页面独立加载约6.64KB；无新增依赖。Python静态编译、pip check通过。API静态合同已重新导出。
- SQLite及实际Compose PostgreSQL均`alembic check`无差异，head仍为`177d4c2b1376`，20张表；本轮不新增迁移。
- 实际Compose全镜像构建启动成功；增强烟测核对报表UTC/每日/总计、CSV合计、no-store、普通用户不能访问报表及导出；原有充值/幂等购买/卡密兑换/worker履约/权限隔离/钱包对账通过。测试QA账号已禁用并撤销会话。
- 容器升级时单独重建API后旧Nginx上游地址曾导致健康检查失败；重新启动web后HTTP烟测通过，部署文档补充同步重建/重启web要求。
- 新增`api/reports.py`、`services/reports.py`、`views/Reports.vue`、`tests/test_reports.py`和[报表说明](reports.md)；更新路由/管理导航/API合同/浏览器和容器烟测。
- 浏览器测试新增商品后，原代理定价场景存在多个同名保存按钮，已按目标商品行定位，避免用全局按钮假定只有一个商品。报表场景使用原生下拉框角色定位并先进入管理员工作台。

报表采用UTC订单创建日和当前支付/履约状态，退款归回原订单创建日。卡密不重复计收入，金额含演示资金，订单净额不代表利润。未进行生产大数据量、实际支付渠道对账或外部服务商投递验收。

## 操作日志筛选与导出（历史记录）

- 最终SQLite完整套件 **84 passed**（约61秒），PostgreSQL16完整套件 **84 passed**（约79秒）。新增11项覆盖后端权限、兼容分页/排序、UTC日期边界、操作人/精确类型/目标字面包含、0和固定ID上界、新日志与导出审计隔离、CSV多行/中文/引号及Unicode空白/控制字符公式处理、单次上限拒绝和账号跨IP限流。

- 最终Chromium完整套件 **20 passed**（约198秒），桌面/手机各10项。新增场景验证真实创建商品→按日期/操作人/类型/目标筛选→详情弹窗→同目标新增操作→旧上界导出只有原记录→重新查询出现两条→查看导出审计。未应用控件不会改变导出条件，重点页面无整页横向溢出。截图已复查：[桌面](screenshots/audit-logs-desktop.png)、[手机](screenshots/audit-logs-mobile.png)。

- 新增独立日志页面、UTC日期/操作人/精确操作类型/目标字面包含筛选、详情弹窗、ID上界分页及导出。旧GET路径及分页字段兼容，不新增表/迁移，head仍为`177d4c2b1376`。
- CSV使用UTF-8 BOM、全字段引号、UTC时间，支持中文/逗号/引号/多行；处理前置空白、Unicode空白、BOM/控制字符下的公式起始符，原文只在页面文本详情查看。每次最多10000条，超出413而不静默截断；每账号每分钟5次，成功导出追加审计且不进入自身文件。
- ID上界只排除更大ID的新增记录，不承诺跨请求MVCC历史冻结。日志没有应用更新/删除接口；数据库管理员仍可能修改数据库，不等同于外部不可篡改证据系统。
- 本地TypeScript/Vite及Compose全镜像生产构建成功，入口JS约242.26KB（gzip93.04KB），日志页独立约6.00KB；无新增依赖。Python静态编译与pip check通过，OpenAPI静态合同已更新。
- SQLite和实际Compose PostgreSQL均`alembic check`无差异；实际容器日志筛选/ID上界/CSV行数/no-store/管理员权限、原有报表和全交易烟测、钱包对账通过。
- 新增`api/audit_logs.py`、`services/audit_logs.py`、`views/AuditLogs.vue`、`tests/test_audit_logs.py`及[日志说明](audit-logs.md)；更新原日志路由注册、前端路由、浏览器/容器测试、README与API/部署文档。

最终验收容器已停止、Compose数据卷保留，本轮4个QA账号已禁用并撤销会话，一次性PostgreSQL16测试容器已删除；未向任何外部邮箱投递。

## 运行状态与异常订单排查（历史记录）

- SQLite完整后端套件 **94 passed**（约104秒），PostgreSQL16完整套件 **94 passed**（约123秒）；Chromium完整套件 **22 passed**（约132秒），桌面/手机各11项，含人工异常→阈值/分类→带订单ID跳转→实际退款→移出异常列表，既有邮件/代理/报表/审计全部回归通过。截图初次包含短暂加载遮罩，增加等待加载结束后重做对应场景截图。

- 新增只读履约/邮件队列摘要、等待阈值与模式提示、失败/取消/重试耗尽/退款审核列表；异常列表可跳转已有订单管理并初始化订单ID搜索。无新增表、环境变量或迁移，head仍为`177d4c2b1376`。
- 10项新增后端用例初验通过，覆盖管理员权限、空状态、阈值边界、人工/模拟提示、卡密和钱包/退款分类、排序分页、邮件退避/过期/功能开关、敏感字段隔离、只读不变量和退款后移出。桌面/手机定向浏览器场景均通过。
- 前端TypeScript/Vite生产构建成功，入口JS约242.51KB（gzip93.12KB），运行状态页面独立约6.80KB；无新增依赖。静态API合同已更新，Python编译与pip check通过。
- 队列摘要不等于worker进程心跳，页面未执行外部SMTP探测、通知、自动重试或退款；邮件计数为记录状态，不逐个判断账号/版本/邮箱有效性。摘要与明细为实时独立查询，可能短暂不一致。
- 新增`services/operations.py`、`api/operations.py`、`views/Operations.vue`、`tests/test_operations.py`和[运行状态文档](operations.md)，更新路由/导航、订单搜索初始化、浏览器/容器测试和API/部署文档。

运行状态对应桌面/手机场景在等待加载结束后再次通过，更新截图已复查：[桌面](screenshots/operations-desktop.png)、[手机](screenshots/operations-mobile.png)。实际Compose运行状态分类/默认模式/权限/no-store、既有交易/报表/审计烟测及钱包对账通过；本轮2个QA账号已禁用并撤销会话，Compose验收服务停止且数据卷保留。

最终PostgreSQL94项通过后，一次性测试容器已删除；源码包排除密钥、数据库、依赖缓存和浏览器测试运行数据。

## worker心跳与持久化站内告警（前一轮，2026-10-17）

- 迁移`32fb2f23c757`增加worker_heartbeats/monitor_state/operational_alerts/alert_events，24张表。SQLite实际upgrade/alembic check通过；专用SQLite迁移往返验证旧等级、500分钱包/流水、子外键保留，新监控单行初始化且新表为空。
- SQLite完整套件 **105 passed**（约103秒），新增11项心跳时间不倒退/并发upsert、UNKNOWN/宽限/失联边界、可选服务、单监控/多副本并发去重、确认幂等与审计、恢复/复发轮次、旧页面轮次冲突、事件分页/隔离、权限/敏感字段及配置约束。PostgreSQL新增11项定向测试通过。
- 桌面/手机监控定向浏览器场景通过：人工异常→心跳/持久告警展示→填写原因确认→事件记录→实际退款后恢复→新异常再次触发→再次确认入口。生产构建TypeScript/Vite通过，入口约242.79KB（gzip93.21KB），监控页面独立约6.9KB，无新增依赖。
- 新增`services/monitoring.py`、`tasks/monitor.py`、模型/迁移、监控API、`Monitoring.vue`、`tests/test_monitoring.py`与[监控说明](monitoring.md)；更新两种worker心跳、Compose/环境模板、确认输入/轮次校验、CLI种子、迁移哨兵、浏览器/容器测试、API合同/部署文档。

PostgreSQL16完整套件 **105 passed**（约199秒）。实际Compose升级到`32fb2f23c757`并通过alembic check；启用`SMOKE_MONITOR_RECOVERY=true`的烟测实际停止履约worker，观察STALE及WORKER_STALE持久告警，再重启worker，观察RECENT及同条告警自动恢复。交易/报表/审计/运行状态和内部钱包对账均通过。

最终Chromium完整回归 **24 passed**（约108秒），桌面/手机各12项。首次并行构建/数据库测试期间，邮箱验证流程最后的钱包页面未在5秒内出现；资源竞争结束后的整套24项全部通过，无业务代码放宽或测试重试掩盖。监控截图已复查：[桌面](screenshots/monitoring-desktop.png)、[手机](screenshots/monitoring-mobile.png)。

SQLite/PostgreSQL均完成旧版→新head→旧版→新head；旧代理标签、钱包/流水与agent_relations子外键保留，monitor_state初始化正确。最终保留Compose本机验收站点运行，QA账号已禁用；专用验收管理员随机密码位于源码目录外0600文件，已验证登录、管理员接口与退出，凭据不进入归档。详见[验收入口](acceptance.md)。

新增`scripts/overnight_check.py`先执行一次短时真实采样（通过站点和心跳），再启动8小时/60秒间隔的只读连续验收。报告及日志位于源码目录外，首轮通过不代表尚未完成的整夜检查通过，次日应查看实际samples/passed/failed与终态。

工具会话结束后的独立Popen巡检未能持续存活，已放弃该方式，改为可选acceptance profile中的独立巡检容器。实际报告以`/root/yunguo-mvp-acceptance/overnight-check.json`为准，不能使用早先Popen报告判断整夜结果。

独立acceptance-check容器实际启动成功，跨工具会话检查仍为running，日志Sample 1: PASS，报告mode=container且履约/监控心跳RECENT。巡检预计本地时间00:20–08:20，尚未宣称整夜通过。源码外旧Popen报告和日志已删除，避免混淆。巡检profile配置校验通过；源码父目录报告权限限制，容器不挂载Docker socket。

## 账户安全增量（2026-10-17）

- 05:50读取实际巡检报告：331次采样全部通过、0失败，原8080业务及acceptance-check容器保持运行。本轮使用独立Compose项目yunguo-account-verify与8081端口测试，避免主动打断8小时巡检。
- 新增accounts.locked_account，在资料修改/改密/退出前重验active与token_version，拒绝鉴权后账号状态变化的旧请求；并发改密单赢家。登录增加邮箱HMAC跨IP共享尝试窗口，改密增加IP/账号双限流；资料/改密/退出在业务事务内生成固定说明审计，不记录密码或昵称原文。
- 新增8项账户安全测试，SQLite与PostgreSQL定向均通过；完整套件最终均为113 passed。新增桌面/手机资料保存、改密撤销旧会话、新密码登录、退出和审计核查浏览器场景。无新增表/迁移，head保持32fb2f23c757。
- 新增services/accounts.py、tests/test_account_security.py及[说明](account-security.md)，更新认证路由、浏览器测试和可配置本机烟测/验收脚本。

账户安全最终补充验证：PostgreSQL16完整113项通过（179.50秒），Chromium完整26项通过（桌面/手机各13项，约3.2分钟）；8081独立Compose交易/报表/审计/监控烟测与钱包对账通过，另经真实HTTP检查资料修改→改密→旧JWT失效→旧密码拒绝→新密码登录→退出撤销。迁移head保持32fb2f23c757，alembic check无差异。Python编译、pip check和Compose配置检查通过，OpenAPI已重新导出。两套本机验收环境均保留运行，新版凭据见acceptance.md。

05:57（Asia/Shanghai）巡检报告为running，338 samples / 338 passed / 0 failed；履约与monitor心跳RECENT，邮件NOT_REQUIRED。该记录只表示当时覆盖，8小时终态仍需读取实际报告。

## 备份恢复演练（2026-10-17）

- 原8080 Compose PostgreSQL逻辑备份恢复到隔离临时容器通过；迁移`32fb2f23c757`、24张业务表、19用户、18订单、18条流水和9张卡密均恢复，钱包对账、购买/退款关联、卡密/订单关联、履约任务和约束检查均为0差异。
- 8081账户安全隔离Compose同样通过；6用户、4订单、4条流水和2张卡密恢复，所有一致性检查为0差异。
- 临时容器、临时备份和恢复数据卷均已清理。新增[scripts/verify_restore.py](../scripts/verify_restore.py)，供部署方在独立环境重复演练；恢复报告不纳入源码包。

07:07（Asia/Shanghai）连续巡检仍为running，408次采样全部通过、0失败；演练期间未中断原8080站点。SQLite完整回归最终113 passed（92.44秒）。

## 代理扣余额自助发卡（2026-10-17）

- SQLite完整133 passed（179.17秒）、PostgreSQL16完整133 passed（307.82秒）；新增20项覆盖一次性交付/哈希/归属、同键重放/变更冲突、非代理拒绝、余额/库存/价格/权限/等级/开关/邮箱/下架拒绝及事务回滚、0元采购、权限改变后核对原批次、并发同键单扣款/单次明文交付、并发不同键不透支、严格输入和禁止指定其他所有者。
- Chromium完整28 passed（约2.9分钟），桌面与手机各14项；新场景通过代理注册升级→演示充值→选择套餐和数量→确认1600分扣款→导出TXT→关闭提醒→公开兑换→余额仍为8400分→账单卡密采购扣款展示，两个尺寸均无整页横向溢出。
- 初次浏览器运行缺少库路径，修正为已有browser-libs后运行；新下拉框测试最初点击Element Plus输入被占位元素拦截，改用真实键盘ArrowDown选择。最终完整28项通过，无强制点击或测试重试。
- 8081独立Compose已更新，真实HTTP采购2张、原键重放不再次交付/扣款、兑换1张不再次扣款、库存和账单核对通过。验收代理账号及剩余1张待兑换卡密保存在源码外0600文件，不打印或归档凭据。
- 新版Compose交易/报表/审计/运行状态/监控烟测与钱包全量对账通过；alembic check无差异，head仍32fb2f23c757。TypeScript/Vite、Python编译、pip check和Compose配置检查通过。新增API合同已导出。
- 原8080未部署新功能，保留其独立巡检。发卡扣费是code_purchase钱包流水，不计入当前按订单汇总的交易报表；现有订单净额不可当作全部业务收入。

07:53（Asia/Shanghai）原8080巡检报告running，454次采样全部通过、0失败；8080和8081健康接口均返回ok，均为mock履约和演示余额环境。

## 直属代理团队（2026-10-17）

- 新增services/agent_team.py、双角色team接口及管理员parent配置；沿用agent_relations表，无迁移变化，head32fb2f23c757/24表。Role行NO KEY UPDATE锁串行化图修改，expected_parent_id拒绝旧表单覆盖；一层直属归属、防自身/循环/多层、变更审计。
- 代理仅看自己的直属成员汇总，无下级邮箱、余额、完整卡密、订单凭证或账号修改权限。订单创建日采购/退款、发卡扣款按UTC日期分列，当前卡密累计数量另列；分页和全部筛选成员总计同一语句快照。非代理成员不显示，转移关系按当前归属显示选定日期历史，不提供归属历史分成。
- SQLite完整141 passed（349.78秒）；最终团队定向9 passed（18.53秒）。全量运行之后新增1项竞争改属测试，并将2项并发用例加强为两个不同管理员竞争；SQLite/PostgreSQL最终9项定向均通过，PostgreSQL17.12秒。当前源码套件共142例，不将尚未整套执行的142例标为一次全量运行结果。
- Chromium完整30 passed（约5分钟），桌面/手机各15项。新增真实管理页面分配上级→总代团队看到直属成员→订单净额800分和卡密采购额1600分→其他团队不可见→非管理员不能改归属→管理员解除后页面成员消失。新团队页面无整页横向溢出。
- 8081实际Compose升级，已使用HTTP创建演示直属与隔离代理，钱包购买及卡密采购汇总、非管理员拒绝、跨团队隔离、解除后不可见/恢复后可见均通过；既有代理验收账号名下保留「团队验收直属代理」供用户查看。原交易/卡密/报表/审计/监控烟测通过，全量钱包对账无差异，alembic check无差异。
- 生产构建、Python编译、依赖检查、Compose配置检查通过。浏览器完整通过后隐藏了团队页无效的父级刷新按钮，由查询业绩按钮刷新；最终web已重新构建部署，两站健康接口ok。

原8080的8小时巡检最终state=completed，2026-10-17 00:20:01–08:20:01（Asia/Shanghai），481次采样全部通过、0失败，容器退出0。此报告只覆盖原8080版本，不作为随后8081团队功能的8小时运行证明。

PostgreSQL16最终完整回归141 passed（387.85秒），测试容器已清理；新增并发竞争场景和不同管理员的最终团队9项已另行通过。

## 卡密采购报表（2026-10-17）

- 新增services/code_reports.py、管理员采购报表查询/CSV接口及CodePurchaseReports.vue。按UTC日期/代理ID/商品ID筛选，统计批次、张数、扣款，提供每日补零、代理/商品汇总和批次CSV。沿用采购流水合同快照，不增加表/迁移。head仍32fb2f23c757。
- 只统计code_purchase扣款，客户兑换、普通钱包订单、充值和管理员免费分配不重复计入；零元批次保留，账号角色变化不丢失历史。批次合同缺失/非法或金额不符时拒绝报表409；单次最多10000条原始采购流水，超限413；CSV固定格式与校验后的批次ID/整数，不输出任意名称/邮箱或卡密。导出审计和跨IP共享限流。
- SQLite完整161 passed（234.84秒），新增16项涵盖真实发卡/重放/兑换/免费分配不重复计算，0价/UTC边界/补零，代理商品筛选，历史角色变化，CSV/敏感字段/审计，权限、日期/ID校验，损坏JSON/数量/金额/批次拒绝，上限与跨IP导出限流。PostgreSQL新旧报表定向26 passed（54.40秒），未将本轮26项描述为全量158项。
- 8081实际HTTP按验收代理查询，将采购批次/数量/金额与独立PostgreSQL SQL聚合逐项核对一致；CSV明细加TOTAL合计相等，no-store与代理拒绝访问通过。既有交易/报表/审计/监控烟测及钱包全量对账再次通过。alembic check无差异，Python编译、pip check、Compose配置通过，OpenAPI已重新导出。

最终Chromium完整32 passed（约2.2分钟），桌面/手机各16项。新场景验证两张卡1600分采购→兑换后报表不增额→按代理和商品筛选→CSV批次/张数/金额TOTAL→未应用筛选不影响导出→无匹配条件为0→代理访问403，并核查两个尺寸无横向溢出。首轮31通过、1个旧团队页面加载超时（具体原因未确认），该轮不计全部通过；停止并行构建/数据库测试后重新完整32项通过，未修改业务代码、放宽超时或启用自动重试。

用户确认后完成8080统一切换：双环境备份、镜像重建、迁移head/alembic check、钱包对账、健康检查及核心HTTP烟测均通过；8081保留对照，未合并数据卷。

切换后的8080主数据卷重新创建独立管理员/代理验收账号，完成1张卡密采购与公开兑换；8080采购报表和CSV读取到1批/1张/3900分，健康接口正常。8081账号仍只对应8081数据库。

新增模拟直充3项定向测试通过：测试开关关闭返回503、Session形态输入被422拒绝、测试模式追加模拟事件并扣款审计，生产Settings拒绝启用。

模拟直充最终收尾：8080镜像重建后容器确认`mock_direct_topup_enabled=false`、fulfillment仍为现有mock演示配置；生产Settings启用该开关返回ValidationError。SQLite完整回归最终161 passed，健康接口正常。

授权履约准备新增8项定向测试通过：authorized适配器保持QUEUED失败闭锁、生产配置要求HTTPS地址/三项密钥、mock和模拟直充生产门禁有效。未宣称真实服务商已接入。

新增provider contract check脚本：manual/mock模式不做外呼，authorized模式只校验HTTPS地址和密钥长度；有效配置检查通过，HTTP/短密钥配置拒绝。
