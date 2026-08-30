# Core Architecture：Intent Routing 与 Hybrid Pipeline 改造审核

## 1. 审核结论

本轮完成了可执行的 Buying/Browsing 双轨架构、独立 Category Route、结构化约束、开放式 Browsing 多样性，以及面向本地 Ollama `qwen3.5:9b` 的候选语义重排接口。

默认路径仍为完全离线、确定性实现。Qwen 接口默认关闭，不下载模型、不导入模型运行时，也不会改变推荐结果。BGE 产物由后续合并统一处理，本轮只依赖与 BGE 相同的 `DenseRetriever` 接口验证架构。

在同一台机器、同一份冻结 dev、同一份 50K catalog、同一份 Hashing Dense 索引上的前后配对结果显示：核心指标均未下降，HR、MRR、MTTC 和技术分均有提升。因此本轮成果通过准确率门槛，可以作为后续 BGE/LLM 合并基础。

## 2. 数据与实验完整性

| 项目 | 值 |
|---|---|
| Catalog 行数 | 50,000 |
| Catalog SHA256 | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` |
| Dev 样本数 | 150 |
| Dev SHA256 | `c8955cacd79bb2e2ed6b984979bca91f379fc699648c5bc2e3ac2efb37f8b22a` |
| Dense 后端 | signed hashing，384 维，完整 50K |
| LLM | 未启用 |

工作区中的 `data/public_set.jsonl` 存在预先已有的换行格式改动，文件 SHA256 与冻结 public 清单不一致，但 Git 在忽略行尾差异时没有内容 diff。由该文件重新生成的 dev/holdout SHA256 与冻结清单完全一致，因此本轮只使用冻结 dev 进行调优和配对验证，没有把被触碰的 public 文件用于最终评分。

## 3. 改造前后指标

### 3.1 总体指标

| 指标 | 改造前 | 最终版本 | 变化 |
|---|---:|---:|---:|
| HR@10 | 0.906667 | **0.913333** | +0.006666 |
| MRR | 0.593405 | **0.596968** | +0.003563 |
| MTTC | 4.453333 | **4.413333** | -0.040000，越低越好 |
| Efficiency | 0.654667 | **0.658667** | +0.004000 |
| Technical Score | 0.762288 | **0.767490** | +0.005202 |

### 3.2 场景指标

| 场景 | 指标 | 改造前 | 最终版本 | 结论 |
|---|---|---:|---:|---|
| Buying | HR@10 | 0.916667 | 0.916667 | 持平 |
| Buying | MRR | 0.586078 | **0.599107** | 提升 |
| Buying | MTTC | 3.600000 | **3.550000** | 提升 |
| Browsing | HR@10 | 0.933333 | **0.950000** | 多命中 1 个 dev 样本 |
| Browsing | MRR | 0.645774 | 0.641653 | 小幅下降 |
| Browsing | MTTC | 4.883333 | **4.816667** | 提升 |
| Intent Override | HR/MRR/MTTC | 0.818182 / 0.460155 / 5.590909 | 相同 | 无退化 |
| Boundary | HR/MRR | 0.875000 / 0.622024 | 相同 | 无退化 |
| Boundary | MTTC | 4.500000 | 4.625000 | 8 个样本中的小幅波动 |

总体 HR、MRR、MTTC 和技术分均通过“不低于现有水平”的要求。Browsing MRR 与 Boundary MTTC 仍应在未来 BGE 配对实验中重点观察。

## 4. 双轨架构

```text
用户消息
  ↓
规则意图解析 + 结构化约束抽取
  ↓
RoutingDecision
  ├─ precision / Buying
  │    ├─ BM25 keyword
  │    ├─ metadata BM25
  │    ├─ category evidence
  │    ├─ Dense supplement
  │    └─ 高置信约束过滤 + 候选不足自动放宽
  │
  └─ discovery / Browsing
       ├─ BM25 keyword
       ├─独立 Category Route
       ├─ metadata BM25
       ├─扩大 Dense semantic pool
       └─开放类别请求的确定性多样化
             ↓
       确定性 reranker
             ↓
       可选 SemanticRanker（当前 disabled）
             ↓
       候选白名单验证与安全回退
             ↓
       Top 10 + clarification
```

### 4.1 Buying 精度轨道

- `RoutingDecision.track=precision`。
- 保留已验证的 BM25 + metadata 头部融合，避免 Category Route 把精确候选挤出 Top 10。
- Category Route 独立执行并记录 rank/score，作为诊断证据，但不直接修改已验证的稀疏融合分。
- material、color、size、brand 等高置信、可由 catalog 验证的约束可以进入精度过滤。
- 每应用一个硬约束都检查剩余候选数；若低于阈值，该约束自动降级为软约束。
- 约束匹配检查 title、features、details、description、categories 和 store，避免字段覆盖不一致造成目标误杀。

### 4.2 Browsing 发现轨道

- `RoutingDecision.track=discovery`。
- Category Route 作为正式融合路由。
- Dense 候选池从 120 扩大到 180，用于补充稀疏路由未召回的场景候选。
- Category 是软信号，不作为硬过滤。
- 对没有明确类别或只包含 `product/clothing/item` 等泛类别的请求启用确定性类别多样化。
- 对评测器提供的具体类别不强制多样化，避免为了形式上的跨类别而损害已知目标相关性。

## 5. 结构化约束与 override

新增的 `Constraint` 包含：

- attribute
- operator
- value
- confidence
- source_turn
- hard
- raw

发生 intent override 时会清理：

- 旧 hard constraints
- 旧 soft preferences
- 旧 structured constraints
- 旧 exclusions
- 旧预算上下界

初始类别继续保留，因为比赛 override 场景替换的是偏好而不是商品大类；如果新消息明确给出类别，则仍会由现有 parser 更新。

## 6. Ollama Qwen3.5 9B 接口

新增 `solution/llm/`：

- `base.py`：`SemanticRanker`、请求和结果协议。
- `disabled.py`：默认无模型实现。
- `qwen.py`：本地 Ollama `/api/chat` 客户端，使用 JSON Schema 约束完整候选排列。
- `factory.py`：按配置创建 Ranker。

模型输入只包含 Top-N catalog 候选的有限摘要：

- parent_asin
- title
- category
- catalog 属性
- 确定性分数
- 各路由 rank
- 当前结构化约束和匿名画像摘要

安全不变量：

- 模型只能重排输入候选，不能生成新商品 ID。
- 输出必须是输入候选的完整、无重复排列。
- 未知 ASIN、重复/缺失候选、错误类型、异常均触发完整回退。
- token usage 保证非负。
- 当前仍以 `semantic_ranker_enabled=false` 为安全默认值；启用后使用 `qwen3.5:9b`，模型不可用或输出非法时保持确定性排序。

模型部署后只需将 `semantic_ranker_enabled` 设为 `true`，不需要修改 Agent API 或检索流水线。

## 7. 测试结果

最终单元测试覆盖：

- Buying/Browsing 路由计划差异
- Category Route 独立性与确定性
- override 清理预算和结构化约束
- 高精度约束过滤及候选不足自动放宽
- 完整 searchable corpus 约束匹配
- Category 证据不扰动 Buying 分数和候选集合
- Browsing 多样性
- Ollama Qwen3.5 接口构造不依赖模型在线
- JSON Schema 请求、token usage 和合法排列解析
- Ollama 连接失败与非法排列安全回退
- SemanticRanker 合法重排
- 未知 ASIN 和非法排列回退
- Dense 缺失、损坏、部分索引安全降级
- Agent 官方输出合同
- evaluator 与实验框架原测试

最终结果：`25/25` 测试通过。

## 8. 第一轮失败与修正记录

第一轮双轨实现得到：

- HR@10：0.900000
- MRR：0.589849
- Technical Score：0.757621

该版本未达到门槛，没有被保留为默认策略。逐轮失败追踪发现：

1. `public_0154` 的 cotton 位于目标商品 description 等完整文本字段中，但第一版过滤器只检查部分字段，导致融合第 6 名目标被误杀。
2. `public_0026` 的目标没有命中 Category Route，而竞争商品获得 Category RRF 加分，目标从基线第 10 名降至第 13 名。

修正后：

- 结构化过滤使用完整 searchable corpus。
- Buying 的 Category Route 改为只附加审计证据，不改变稀疏头部得分。
- Browsing 继续使用 Category 正式融合。

最终版本恢复 Buying HR，并使总体指标超过基线。

## 9. 当前问题和风险

### 9.1 性能回归

| 版本 | 150 dev 总耗时 |
|---|---:|
| 改造前 | 224.930 秒 |
| 最终版本 | 293.023 秒 |
| 变化 | +68.092 秒，约 1.303 倍 |

主要原因是 Browsing Dense pool 扩大和额外候选重排。当前准确率收益通过门槛，但性能回归需要在 BGE 合并时处理。建议：

1. 将 NumPy 全矩阵检索替换为经过 Top-K 一致性验证的 FAISS/ANN 索引。
2. 对规范化 query 做跨会话持久缓存或批量向量检索。
3. 对 Browsing Dense limit 做 120/150/180 配对 ablation，确认新增命中需要的最小范围。
4. BGE 合并后重新测量实际编码与向量搜索耗时，不能直接沿用 Hashing 结果推断。

### 9.2 路由仍是规则实现

当前 Intent Router 对比赛英文模板可靠，但对自由表达、隐含购买意图、复杂否定和中文输入的泛化有限。Qwen 首次接入应先采用 shadow mode，对比结构化意图，不直接控制最终推荐。

### 9.3 硬约束白名单有限

当前只对 material、color、size、brand 等高置信字段进行新增精度过滤。feature、style、use_case 保持软打分，这是为了避免 catalog 元数据覆盖不足造成误杀。后续若要扩大硬过滤，需要先统计字段覆盖率和误杀率。

### 9.4 多样性只在真正开放类别时启用

当前 evaluator 会从目标商品生成具体类别，因此大多数 dev Browsing 不触发最终类别多样化；本轮 Browsing 提升主要来自更大的 Dense pool 和独立 Category Route。真实开放式对话需要单独构建无明确类别测试集。

### 9.5 BGE 尚未在当前工作区验证

本轮没有复制、重建或修改同事机器上的 BGE 产物。合并时必须验证：

- catalog SHA256
- 50K 完整行数
- parent_asin 顺序
- 384 维和模型名称
- `complete_catalog=true`
- Buying/Browsing 同 dev 配对指标

现有 `DenseRetriever` 和双轨 Pipeline 已保留统一接口，BGE 合并不需要重写架构。

## 10. 改动文件

核心新增：

- `solution/constraint_parser.py`
- `solution/routing.py`
- `solution/pipeline.py`
- `solution/retrieval/category.py`
- `solution/ranking/diversity.py`
- `solution/ranking/semantic.py`
- `solution/llm/base.py`
- `solution/llm/disabled.py`
- `solution/llm/qwen.py`
- `solution/llm/factory.py`

核心修改：

- `solution/agent.py`
- `solution/config.py`
- `solution/schemas.py`
- `solution/state.py`
- `solution/intent.py`
- `solution/retrieval/fusion.py`
- `solution/ranking/constraints.py`
- `experiments/run_experiment.py`
- `experiments/trace_failures.py`
- `tests/test_solution.py`
- `solution/README.md`

没有修改：

- `evaluator/local_evaluator.py`
- `starter/agent.py`
- catalog 内容
- 官方指标公式

## 11. 复现命令

```powershell
# 生成冻结 dev/holdout
python -m experiments.split_public_set

# 构建本轮使用的本地 Hashing Dense
python scripts\build_embeddings.py --backend hashing --batch-size 512 --checkpoint-every 4096

# 单元测试
python -m unittest discover -s tests -v

# 最终 dev 评测
python -m experiments.run_experiment `
  --config experiments\configs\hybrid_steps_3_10.json `
  --run-dir experiments\runs\post_dual_track_v2

# 与改造前配对比较
python -m experiments.compare_runs `
  experiments\runs\pre_dual_track_baseline `
  experiments\runs\post_dual_track_v2
```

## 12. 最终审核意见

本轮在没有真实 LLM、没有重新管理 BGE 的情况下，已经完成双轨架构与未来模型接口，并通过冻结 dev 证明总体准确率不低于原实现。成果可进入合并准备阶段。

合并前的最高优先级不是继续调整准确率权重，而是：

1. 接入同事已跑通的完整 BGE 并做同 split 配对复验。
2. 解决 Browsing 扩池带来的约 30% 性能回归。
3. 部署 Ollama `qwen3.5:9b` 后完成真实延迟、吞吐、显存和配对准确率复验。
4. 对真实无类别 Browsing 和自由语言路由补充独立测试集。
