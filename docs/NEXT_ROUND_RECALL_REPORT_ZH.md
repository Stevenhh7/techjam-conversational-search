# Project 4 下一轮召回增强与风险审核报告

> 历史说明：本报告记录当时的实验不变量。最终提交打包阶段已将
> `starter/agent.py` 改为 `solution.agent.Agent` 的薄适配器，以确保官方默认命令
> 运行正式方案；原始弱基线保存在 `starter/baseline_agent.py`。官方 evaluator
> 始终未修改。

## 1. 本轮结论

默认 Agent 已从“Dense 同时参与 RRF 与重排”改为“Dense 只补充候选，头部排序以稀疏检索和可解释特征为主”。随后在 dev 失败边界中加入小权重、对数归一化的评论量软特征，用于文本同质商品的确定性破平局。

| 方案 | 数据 | HR@10 | MRR | MTTC | 技术分 | 总耗时/秒 |
|---|---|---:|---:|---:|---:|---:|
| 旧 hashing hybrid | dev 150 | 0.880000 | 0.561011 | 4.560000 | 0.737103 | 见旧 run |
| Dense 仅补候选 | dev 150 | 0.880000 | 0.583780 | 4.640000 | 0.742334 | 170.08 |
| Dense 补候选 + 评论量软破平局（当前默认） | dev 150 | **0.906667** | **0.593405** | **4.453333** | **0.762288** | 229.47（加缓存前） |
| Top-30 cross-encoder | dev 150 | 0.880000 | 0.585672 | 4.626667 | 0.743168 | 396.35 |

当前默认方案同时提高 HR 与 MRR。Cross-encoder 只获得很小的 MRR 增益，却将耗时提高到 2.33 倍，因此不晋级默认路径。

## 2. 24 个旧失败会话审计

审计脚本对每一轮记录 BM25、metadata、Dense、稀疏 RRF、补充后候选和最终重排位置，并严格区分 intent override 生效前后的无效/有效轮次。

- 3 个：BM25、metadata、Dense 均未召回目标。
- 20 个：目标已进入最终重排列表，但稳定落在第 11 名之后。
- 1 个：目标进入融合候选，但被约束过滤移除。
- 7 个 override miss 中，6 个是覆盖生效后最终排名第 26–117，1 个被约束过滤。

详细数据：

- `experiments/analysis/legacy_24_failures.json`：完整逐轮机器可读记录。
- `experiments/analysis/legacy_24_failures.md`：摘要表。
- `experiments/analysis/dense_supplement_dev_failures.json`：Dense 补候选版剩余 dev miss。

因此，本轮没有盲目扩大 Dense 候选，而是优先修复头部排序。

## 3. 主要代码变更

### `solution/agent.py`

- Dense 默认只补充候选，不再对已有稀疏候选重复增加 RRF 分。
- 增加可关闭的逐轮诊断；默认关闭，不影响官方 evaluator 接口。
- 可选 Top-30 cross-encoder 在常规重排后运行；默认关闭。

### `solution/retrieval/fusion.py`

- 新增 `supplement_with_dense`。
- Dense 命中的已有稀疏候选只附加 Dense 证据，不改变稀疏 RRF 分。
- Dense-only 商品可以进入候选池，但初始分不高于稀疏候选尾部。

### `solution/ranking/reranker.py` 与 `solution/config.py`

- 所有重排权重集中到配置对象，便于严格 ablation。
- Dense 头部影响由 0.20 降到 0.04。
- 新增 0.04 权重的 `log1p(rating_number)` 软特征；不做硬过滤，缺失值按 0 处理。
- 并列结果仍以 ASIN 确定性收敛。

### `solution/retrieval/dense.py`

- 继续校验 catalog SHA256、模型、矩阵行数和 ID 数量。
- 新增完整 catalog 行数校验；部分 smoke-test 索引明确禁用。
- 新增确定性 LRU 查询缓存；返回新的 Candidate 对象，避免缓存对象被后续重排污染。

### `solution/ranking/cross_encoder.py`

- 使用 FlashRank ONNX cross-encoder，默认关闭。
- 仅允许 Top 30–50；当前 ablation 为 Top 30。
- 单次预算 2500 ms；超预算时丢弃该次结果并关闭该路由。
- 依赖、模型或推理失败时安全降级，不影响默认 Agent。

### `scripts/build_embeddings.py`

- hashing 与 BGE 使用不同默认文件名，避免实验混写。
- 分批写入 NumPy memmap，支持进度 checkpoint 与 `--resume`。
- 元数据新增 `catalog_row_count`、`indexed_row_count` 与 `complete_catalog`。
- 本机已完成 BGE 32 条和 1000 条 smoke test；1000 条约 162 秒，推算本机 CPU 全量 50K 约需 2 小时以上，因此本轮没有把部分 BGE 当成正式指标。

### `experiments/trace_failures.py`

- 从既有 `results.json` 提取 miss。
- 复现 evaluator 的初始消息、澄清回复和 override 时序。
- 输出逐轮路由 rank、查询、状态、提问与最终 Top 10。

### `experiments/frozen_datasets.json`、`experiments/frozen.py`

- 冻结 dev、holdout、public 的 SHA256 与样本数。
- tuning 配置在 holdout/public 上运行时必须显式传入 `--final-eval`。
- 运行前验证当前数据文件；不允许静默使用被改动的数据。

### `solution/ablations.py`

- `LegacyDoubleDenseAgent`：只用于复现旧双重 Dense 计分。
- `CrossEncoderTop30Agent`：只用于 cross-encoder dev 实验。
- `StrictBgeAgent`：BGE 文件不完整、不匹配或发生 fallback 时直接拒绝实验，避免把稀疏/哈希结果误标为 BGE。

## 4. 风险处理状态

| 风险 | 本轮处理 | 状态 |
|---|---|---|
| BGE 50K 未完成 | 后端独立文件、断点续跑、完整性强校验、严格 ablation；完成 1000 条 smoke | 已降低，仍需合适硬件全量构建 |
| public 200 可被过拟合 | 权重只在 dev 调整；holdout/public 加冻结哈希与 final 开关 | 已控制；私有 800 仍是最终依据 |
| 375 秒运行时间 | Dense/BM25 确定性 LRU 缓存；cross-encoder 因 2.33 倍耗时不晋级 | 部分解决；FAISS 仍可后续试验 |
| price 覆盖低 | 保留“有值才保守过滤、缺失不拒绝”；未新增价格硬规则 | 已控制 |
| 无 cross-encoder 证据 | 完成 Top-30 dev ablation、预算与关闭开关 | 已完成；当前不晋级 |
| holdout 泄漏 | 文件冻结；此后不再根据 holdout 结果调权 | 已落实 |

## 5. 复现命令

```powershell
# 验证冻结数据
.\.venv\Scripts\python -m experiments.verify_frozen_data

# 默认 hashing dense dev
.\.venv\Scripts\python -m experiments.run_experiment --config experiments\configs\hybrid_steps_3_10.json

# 失败会话逐轮审计
.\.venv\Scripts\python -m experiments.trace_failures `
  --results experiments\runs\<run>\results.json `
  --dataset data\splits\dev.jsonl `
  --output experiments\analysis\dev_failures.json

# 在合适硬件上构建完整 BGE；中断后加入 --resume
.\.venv\Scripts\python scripts\build_embeddings.py --backend fastembed --batch-size 256 --checkpoint-every 1000

# 严格 BGE 同 split ablation；部分索引会直接报错
.\.venv\Scripts\python -m experiments.run_experiment --config experiments\configs\bge_dense_dev.json

# 可选 cross-encoder Top-30 dev ablation
.\.venv\Scripts\python -m experiments.run_experiment --config experiments\configs\cross_encoder_top30_dev.json

# 只在候选完全冻结后进行最终评测
.\.venv\Scripts\python -m experiments.run_experiment --config experiments\configs\hybrid_steps_3_10.json `
  --dataset data\splits\holdout.jsonl --final-eval
```

## 6. 下一轮顺序

1. 当前默认权重冻结，不再读取 holdout 调参。
2. 在 GPU/高核 CPU 机器上用断点构建器完成 50K BGE，并运行 `StrictBgeAgent` 的同 dev split ablation。
3. 只有 BGE 在 dev 同时改善 HR/MRR 且耗时可接受，才生成一个全新的未使用 final split 进行一次确认。
4. cross-encoder 当前不晋级；只有更小模型、Top-N 更小或缓存后能把额外耗时压到预算内才重开实验。
5. 若继续提高 override，优先修复覆盖后低召回查询与约束状态，不再提高 Dense 头部权重。

## 7. 不变量复核

- `evaluator/local_evaluator.py` 和 `starter/agent.py` 未修改。
- catalog 只读，推荐 ID 只来自 catalog 文档与检索候选。
- Dense catalog SHA256/行数/模型不一致时禁用；严格 BGE 实验则直接失败。
- 默认 Agent 缺少 Dense 或 cross-encoder 依赖时安全降级。
- 默认检索、融合、重排、提问和 ASIN 破平局确定。
- 当前测试、`compileall`、ResourceWarning 严格模式与 `git diff --check` 均需在交付前再次执行。
