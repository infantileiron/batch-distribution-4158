# 按缸分层置换检验 · 验收报告

日期：2026-11-12
范围：为同缸相关色样增加按缸分层（by_vat）置换检验，与历史跨缸打乱（pooled）口径并存，旧研究按原口径复现。

## 1. 需求与实现对应

| 需求 | 实现位置 |
|---|---|
| 仅缸内交换批次归属，保留各缸两批样本数 | `backend/src/services/permutation.py::stratified_permutation_test`（逐缸 shuffle，选 n_vA 个归 A） |
| Energy V 与 MMD U 共用同一批排列 | 同一分配循环同时计算两个统计；`stratification.shared_permutations=true` |
| 可行分组 ≤ 预算全枚举给精确 p | `EXACT_ENUMERATION_BUDGET=1000`；逐缸 `C(n_v,n_vA)` 笛卡尔积；观测分配计入分母，p=extreme/分组数，不做 +1 |
| 超预算随机抽样，沿用加一口径 | 固定 seed 的 `random.Random` 逐缸 shuffle；p=(1+extreme)/(B+1) |
| 缺缸号 / 缸内仅一批拒绝 | `services/validation.py::validate_vat_groups`；研究冻结 422（`services/studies.py`），worker 与引擎内二次防线 |
| 分层与抽样依据冻结、页面与 CSV 可追溯 | 结果 `stratification` 块（method/feasible_groups/evaluated_groups/缸序/各缸数/sampling_basis）；前端 `StratificationPanel`；CSV 追加 4 列 |
| 兼容历史数据，旧研究原口径复现 | policy 新增 `stratification` 默认 pooled；启动迁移 `config/migration.py` 补列回填；快照无该字段时 `analyze` 走 pooled，pooled 引擎逐行保持旧实现 |

## 2. 关键统计口径

- 可行分组数 = 各缸 `C(n_v_total, n_vA)` 的乘积；每次排列严格保持每缸 A/B 计数，样本不跨缸移动。
- 全枚举精确 p：观测分配本身属于枚举集合，分母为全部分组数（含观测），因此无 +1 校正；重跑结果完全确定。
- 蒙特卡洛：B 次抽样均为重新随机的缸内分配（不保证排除观测分配，与历史 pooled 抽样口径一致），+1 同时进入分子分母；同 snapshot 同 seed 可复现。
- 分层只改变标签的零分布；坐标缩放、核宽、距离/核矩阵仍在置换前按合并样本一次性估计，置换期不重估。

## 3. 验证证据（本机，numpy 1.26.4 / SQLAlchemy 2.0.41 / pydantic 2.14）

- `test_acceptance.py`：47 项断言全部 PASS。覆盖
  - pooled 新引擎与升级前逐行副本在两种缩放/核宽下排列索引与统计逐位一致；
  - 全枚举 36 分组不重不漏、分母无 +1、各缸计数守恒、观测分配在枚举内；预算边界 feasible=1000 仍枚举、8000 转抽样；
  - 蒙特卡洛 924³ 分组走抽样、+1 公式、seed 确定性与异 seed 发散；
  - 缺/空缸号、单批缸、单缸均拒绝；
  - 缸内点完全相同 → 精确 p=1（排列不变性）；缸间混淆构造下 pooled p 明显小于分层 p（分层隔离缸间差异）；缸内强效应 → MC 达到最小 p 1/(B+1)；
  - 旧快照无 stratification → pooled；schema 默认 pooled、拒绝非法枚举；研究冻结 422；CSV 新旧列；SQLite 内存库服务层全链路。
- `run_legacy_upgrade.py`：旧表（无 stratification 列）经启动迁移补列并回填 pooled，重复迁移幂等。
- `run_seed_check.py`：demo seed 两次执行计数一致（自然键幂等）；新增三缸数据集/by_vat 口径/分层研究-运行-复核-归档齐备，可行分组 924³=788,889,024 走蒙特卡洛；旧 demo-run 无 stratification 块。
- `run_http_e2e.py`：TestClient 全 HTTP 流程，含 422 拒绝报文、200 冻结、归档 CSV 含 `by_vat/monte_carlo/feasible_groups/sampling_basis`、viewer 403。
- 前端 `npm run build`（tsc --noEmit + vite）通过。

## 4. 复现命令

```sh
# 后端算法/服务层（依赖装在 user site，脚本内显式挂载；-I 隔离当前目录）
python3 -I test-artifacts/stratified-vat/test_acceptance.py
python3 -I test-artifacts/stratified-vat/run_legacy_upgrade.py
python3 -I test-artifacts/stratified-vat/run_seed_check.py
python3 -I test-artifacts/stratified-vat/run_http_e2e.py
# 前端
cd frontend && npm ci && npm run build
```

## 5. 边界与未决项

- 全枚举预算固定 1000，不通过 API 暴露；预算内数据量通常很小（如每缸 3+3、两缸），枚举耗时可接受。
- 精确 p 与 MC 的 +1 口径差异已在结果、页面、CSV、复核假设文案中显式标明，不混用。
- 分层要求至少两个缸且每缸两批齐备；缸内完全没有批次共现的数据无法识别缸内迁移，按要求拒绝而非静默退回 pooled。
- 未引入多重校正；两个 p 仍分别人工复核。
