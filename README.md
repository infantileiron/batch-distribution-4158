# 绮川印染 · 批次色差分布迁移辨识

保留两批模拟L*a*b*原始读数，以多元Energy V和无偏RBF MMD U共享随机排列，形成可追溯的统计、口径与人工复核稿。

绮川印染色材研究组是一个模拟的16人团队。上游交付 `qichuan_lab_batches_20261112.json` 的两批各90条三维色度读数。过去只比较批次均值：方差与多峰变化被漏掉，核宽随结果游移，有限置换p被误读成迁移概率。本项目替代从读数校验到统计复核的一段；下游由研究员解释、负责人批准CSV，不作颜色合格、工艺因果或真实生产控制结论。

## 09:00—09:40的复核

1. 09:00 导入两批90条模拟色样，检查三维完整性与跨两批唯一的样本ID。
2. 09:05 观察原始二维投影；种子两批均值同为L*=68、a*=12、b*=18，B批有更大方差和多峰。
3. 09:10 锁定合并总体SD缩放、合并距离中位核宽、B=199和seed=2407。
4. 09:15 冻结原始批次与口径快照，提交Redis worker。
5. 09:20 核对Energy V与MMD U原始值，不将负U截0。
6. 09:25 查看两条共享排列分布、极端次数、B+1分母与三维边际。
7. 09:30 分别解释两个未经多重校正的p，写明独立可交换假设，提交接受或待补充复核版本。
8. 09:40 负责人批准最新接受版本，下载绑定运行、口径、复核版本与校验和的CSV。

## 快速启动

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 180
# 启动自动seed，也可显式复跑，不覆盖用户编辑
docker compose exec backend python -m scripts.seed_demo
```

前端 `http://localhost:18236`，API文档 `http://localhost:19236/docs`，PostgreSQL `localhost:17736`。

| 角色 | 演示账号 | 权限与动作 |
|---|---|---|
| analyst | analyst@qichuan.demo | 导入批次、保存口径、冻结研究、运行、提审 |
| admin | admin@qichuan.demo | 所有分析功能，批准最新接受版本归档 |
| viewer | viewer@qichuan.demo | 读取结果/审计，下载已批准CSV，不能写入或批准 |

密码均为 `Color2026!`。演示JWT密钥和凭据只用于本地模拟环境。角色由服务端JWT校验；所有写请求及拒绝状态进入审计，输入异常与全局错误返回可恢复信息。

## 统计口径

`backend/src/services/energy.py::energy(a,b)` 使用所有维的欧氏距离：`2 mean(d(A,B)) − mean(d(A,A)) − mean(d(B,B))`。组内均值包含对角，是Energy V统计。`mmd.py::mmd(a,b,sigma)` 使用 `exp(−||x−y||²/(2sigma²))`，两组内排除对角并分别除以n(n−1)、m(m−1)，再减2倍跨组核均值。对角核值为1，因此实现从完整组内和减去样本数。无偏MMD U可为负，原始值不截0。

`services/permutation.py::permutation_test(...)` 一次计算合并坐标、距离与核矩阵，再固定seed生成共享排列。每次重新从0..N−1的索引列表shuffle，前n个分到A、余下m个分到B；两个统计使用同一排列，保存完整索引与各自全部置换值。上尾比较 `stat_perm >= stat_obs`，`p=(1+extreme_count)/(B+1)`，公开B、seed、极端次数、分母与原始统计。Float64矩阵，math.fsum累加，计算时按合并索引排序以稳定组内顺序。

缩放有原始坐标none、合并总体SD pooled_std两种。后者只用全部样本估计一次均值/总体SD，不按标签分别估计；零SD维显式采用scale=1，中心化后为0，并记录维度。自动sigma是合并样本全部非对角欧氏距离的中位数，包含零距离；中位数0明确失败，要求改用固定正sigma，不跳过零值、不静默加epsilon。用户固定sigma同样在置换前锁定。置换期间不重估任何标签依赖参数。

## 按缸分层（by_vat）

同缸色样彼此相关，跨缸打乱会把缸间差异误判成批次迁移。口径新增 `stratification`：`pooled`（历史默认，全部样本跨缸打乱）与 `by_vat`（按缸分层，仅缸内交换批次归属）。by_vat 下每次排列在每个缸内部 shuffle，保持该缸 A/B 两批样本数不变，样本不跨缸移动；Energy V 与无偏 MMD U 共用同一批缸内排列。

数据集每条读数新增可选 `vat_id`。选择 by_vat 口径冻结研究时强制校验：任一读数缺缸号、或某缸只有一批样本（缸内无法交换归属）、或缸数少于2，研究冻结接口直接 422 拒绝，任务不进队列；worker 内保留同一校验作为防线。pooled 历史口径不要求缸号，旧数据集与旧研究快照（无 `stratification` 字段）一律按原口径逐位复现。

分层与抽样依据随运行结果冻结并在页面与 CSV 留痕：先逐缸计算可行分组数 `C(n_v, n_vA)`，乘积为总体可行分组数。可行分组不超过预算（`EXACT_ENUMERATION_BUDGET=1000`）时全枚举全部缸内归属分配给**精确p**：观测分配本身是枚举之一、计入分母，`p=极端次数/分组数`，不做+1校正；超过预算则按口径锁定的 seed 做蒙特卡洛缸内抽样 B 次，沿用 `p=(1+extreme)/(B+1)` 加一口径。结果记录 `method`（exact_enumeration/monte_carlo）、`feasible_groups`、`evaluated_groups`、冻结缸序、各缸样本数与可行分组数、`sampling_basis` 文字依据；CSV 追加 `stratification,permutation_method,feasible_groups,sampling_basis` 四列，旧列顺序不变。

历史部署升级：`src/config/migration.py` 在 API、worker 与 seed 启动时幂等检查 `kernel_policies`，缺列则补 `stratification VARCHAR NOT NULL DEFAULT 'pooled'` 并回填 pooled；旧研究、旧运行、旧 CSV 仍按跨缸打乱口径复现，分层只对新口径/新研究生效。

真实API每批4至120条完整有限读数，算法函数支持每批至少2点的手算。允许不同样本读数相同，样本ID跨两批唯一。两个检验的p**未做多重校正**，分别人工复核，不合并成自动迁移结论。p不是迁移概率；有限随机排列有分辨率与抽样变动。pooled口径假设样本独立可交换；成对、时序或同缸相关读数可能不适用，此类数据应改用by_vat分层口径，其可交换前提为缸内批次标签条件可交换，缸级系统差异被分层隔离。原始三维欧氏坐标不是DeltaE00，缩放后的Energy单位也不同于原始读数口径。

## 实体与技术

六实体 ColorBatchDataset、KernelPolicy、DistributionStudy、DistributionRun、ShiftReview、Report，贯穿表/model/schema/service/route、前端API/store/page。研究冻结原始批次及口径；运行保存原始读数、变换参数、统计、完整排列与分布；每次复核新增不可变版本。归档绑定最新接受复核ID，后续新复核不改变旧CSV。KernelPolicy 带 stratification（pooled/by_vat），ColorBatchDataset 读数带可选 vat_id；旧行由启动迁移补默认值。

| 部分 | 技术 |
|---|---|
| 前端 | React18、TypeScript、Vite、真实SVG散点/边际/置换图 |
| API | Python3.11、FastAPI、SQLAlchemy、JWT |
| 算法 | NumPy Float64距离/核矩阵，标准库固定seed与fsum |
| 后台 | Redis真实队列、独立Python worker与心跳健康检查 |
| 数据库 | PostgreSQL16，sigma为DOUBLE，预算和seed为INTEGER |
| Docker | 恰好frontend/backend/worker/db/redis，五服务均真实健康检查 |

`frontend/src` 按api/stores/types/pages/components/common/hooks/router/utils/constants分工，六领域页加登录；散点、口径条、统计摘要跨页共享。`backend/src` 按models/schemas/services/controllers/routes/middlewares/config/utils/constants分工；`backend/scripts/seed_demo.py`仅插入缺少的自然键，`backend/migrations`说明初始schema。测试、截图、日志和验收报告单独存放批根 `test-artifacts/gb-2407`（历史口径基线）与 `test-artifacts/stratified-vat`（按缸分层验收：算法42项断言、旧库升级回填、HTTP端到端），不混入源码。配套package/lock仅JSON修改根包名，使用npm ci。

`.env.example`：COMPOSE_PROJECT_NAME=batch-distribution，FRONTEND_PORT=18236，BACKEND_PORT=19236，DB_PORT=17736，SEED_DEMO=true，JWT_SECRET；DATABASE_URL/REDIS_URL在compose注入。三个命名卷分别保存数据库、Redis和worker产物；Nginx `/api/`代理并SPA回落，健康检查用127.0.0.1，数值线程限制1。开发时前端 `npm ci && npm run dev`，API `uvicorn src.main:app --host 0.0.0.0`，worker `python -m src.worker`，配置可连接的数据库和Redis地址。

共享枚举role、scaling、bandwidth、stratification、run_status、review_decision在 `backend/src/constants/enums.py` 与 `frontend/src/constants/enums.ts`；schema Literal、状态服务和页面保持一致。

## 边界与清理

最多每批120条、API最多999次随机排列，不进行多重校正。读数仅JSON表单导入；新口径需新研究，不覆盖已冻结统计。分层全枚举预算固定为1000个可行分组，超出即转固定seed蒙特卡洛；全枚举精确p不做+1、蒙特卡洛沿用+1，两种口径都在结果与CSV标明。边际图共享每维合并范围分箱，只是观察视图，多元检验使用全部三维。单worker无生产级分布式租约，初始SQLAlchemy建表不含生产迁移回滚，无多租户隔离。模拟均值/方差/多峰不代表真实颜色质量或工艺变化原因。

```sh
docker compose down -v --remove-orphans
```

License: MIT。全部色样与批次均为模拟数据。

种子采样说明：为构造经验均值完全相同的可复现视觉反例，种子使用镜像成对合成结构，不能称为真实独立采集。示例p仅展示所声明置换口径，不声称该合成结构下的真实I类错误校准；真实应用需另行满足独立可交换前提。总览已移除“独立模拟色样”表述并明确合成性质。
