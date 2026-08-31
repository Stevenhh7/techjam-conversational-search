# 8-31 后续工作汇总与实施计划

> 历史计划说明：本文第 4–7 节记录实施前的差距和设计。Personalized Context Distillation、内存 Profile Store、Adaptive Context Program、Strategy Outcome 闭环及当前主链 Qwen 完整配对现已实施；最新状态以 `docs/DYNAMIC_CONTEXT_PROGRAMMING_ZH.md` 和 `docs/COMPETITION_REQUIREMENTS_STATUS_ZH.md` 为准。当前测试基线为 49/49。

## 1. 文档目的

本文综合以下三份阶段报告及第三阶段 Self-Evolution 代码审计结果，统一说明项目当前状态、剩余差距、后续实施顺序、测试门槛和暂不应执行的事项。

- [Core Architecture：Intent Routing 与 Hybrid Pipeline 改造审核](CORE_ARCHITECTURE_DUAL_TRACK_REVIEW_ZH.md)
- [Dialog Strategy：Multi-Turn Scenario Evolution 改造审核与交接](DIALOG_STRATEGY_MULTI_TURN_REVIEW_ZH.md)
- [RTX 3060 全量 BGE GPU 实现与 dev 150 配对评测报告](BGE_RTX3060_GPU_IMPLEMENTATION_AND_DEV150_REPORT_ZH.md)

三份报告存在时间先后关系：

- Core Architecture 报告中的“BGE 尚未验证”已经由最新 BGE 报告更新。
- Dialog Strategy 报告中的“Qwen/BGE 待合并”目前只剩 Qwen；BGE 已在本机完成全量构建和配对评测。
- 当前完整测试基线为 36/36，而不是早期报告中的 25/25 或 35/35。
- 最新性能和准确率基线以 BGE RTX 3060 报告为准。

## 2. 当前总体状态

| 模块 | 当前状态 | 后续重点 |
|---|---|---|
| I. Intent Routing & Hybrid Pipeline | 主体完成 | 将 BGE 从实验 Agent 纳入正式部署配置；Qwen 尚未实测 |
| II. Multi-Turn Scenario Evolution | 主体完成 | 补真实 Over-General 数据、自由语言解析和缓存生命周期 |
| III. Dynamic Context Programming | 仅部分完成 | 下一阶段的主要开发任务 |
| 全量 BGE/GPU | RTX 3060 本机验证完成 | 统一 artifact、部署入口、性能与最终集验证 |
| Qwen3.5 9B | 接口完成、模型未启用 | 先 shadow，再受控启用 |

当前系统已经具备：

- Buying/Precision 与 Browsing/Discovery 双轨路由；
- Keyword、Category、Metadata、Dense 多路召回；
- 高置信硬约束过滤和安全放宽；
- Browsing 跨类别多样化；
- 多轮 Slot 累积；
- Full、Attribute、Category 三类 Intent Override；
- 显式对话状态阶段和迁移历史；
- Over-Generality 检测；
- 特殊轮次跳过 Dense/LLM 的 provisional Top 10；
- 候选信息增益驱动的主动澄清；
- Ollama Qwen3.5 9B 候选语义重排接口及安全回退；
- RTX 3060 上的 50,000 商品全量 BGE 索引；
- 精确向量搜索 `float16` 磁盘、`float32` 内存优化。

当前尚未完整具备：

- 对话历史到个性化上下文的统一蒸馏；
- 长期用户画像的学习、置信度、撤销和跨会话存储；
- 根据历史策略效果生成每轮工作流计划；
- `历史 → 蒸馏 → 编排 → 结果 → 策略修订` 的闭环；
- Qwen3.5 9B 真实模型运行和准确率、延迟、显存验证。

## 3. 需要冻结的当前基线

后续修改都应与以下同 split 结果配对比较。

| Dense 后端 | HR@10 | MRR | MTTC ↓ | Efficiency | 技术分 | 耗时 |
|---|---:|---:|---:|---:|---:|---:|
| Hashing | 0.913333 | 0.597302 | 4.406667 | 0.659333 | 0.767724 | 295.450s |
| BGE/CUDA | 0.913333 | 0.603272 | 4.373333 | 0.662667 | 0.770181 | 332.911s |

BGE 当前结论：

- 总体 HR@10 与 Hashing 持平；
- MRR、MTTC、Efficiency 和技术分有净提升；
- Intent Override 提升明显；
- Browsing HR 少命中一个 dev 样本；
- Buying MRR 略有下降；
- 不应针对少量翻转样本硬编码规则。

### 3.1 数据使用边界

- `data/splits/dev.jsonl`：150 条，唯一调优集合。
- `data/splits/holdout.jsonl`：50 条，只用于最终验证。
- `data/public_set.jsonl`：官方公开 200，不在开发过程中反复运行。
- `dev 150` 是从官方 public 200 按固定 seed 分层生成的冻结调优子集。
- 不使用中断、部分或 checkpoint 结果作为准确率结论。
- 不针对 `public_0076`、`public_0198` 等样本 ID 或目标商品写特殊逻辑。

## 4. 第三阶段需求差距

### 4.1 Runtime Adaptation

现有短期状态能力基本完善：

- `SessionState` 保存当前意图、槽位、预算、排除项、消息历史、槽位变更历史、状态迁移历史和上一轮推荐；
- `update_state()` 每轮支持增量信息、属性覆盖、类目覆盖、完整 Override 和待澄清回答解释；
- 查询和排序会弱使用外部传入的 `user_profile`。

主要差距：

1. `message_history`、`previous_recommendations`、`slot_history`、`transition_history`、`last_routing` 多数只写入，不参与下一轮策略决策。
2. 没有独立、类型化、长度受限的 `DistilledContext`。
3. 没有区分已确认偏好、暂定偏好、负偏好、临时偏好和长期稳定偏好。
4. `user_profile` 只在 `reset()` 时注入，之后不学习、不合并、不衰减、不撤销。
5. 没有 Profile Store，也没有可靠的跨会话用户标识。

### 4.2 Adaptive Orchestration

现有动态能力包括：

- Buying/Browsing 双轨选择；
- over-general 时 provisional/full pipeline 切换；
- 候选驱动的澄清属性选择；
- Dense/LLM 的特殊轮次跳过与恢复。

主要差距：

1. Agent 中的执行顺序仍然固定。
2. `RoutingDecision` 只是从两组静态配置中选择参数。
3. 不会根据推荐重复、用户否定、候选不足、约束放松、澄清效果或模型延迟重新规划。
4. 没有每轮生成的类型化 Context Program。
5. 没有 Strategy Outcome，也没有策略反馈闭环。
6. 当前属于“动态状态机 + 静态启发式分支”，还不是完整的 Dynamic Context Programming。

## 5. 目标架构

```text
当前用户消息
    ↓
State Update
    ↓
Context Distillation
    ├─ Short-Term Context
    ├─ Long-Term Profile Snapshot
    └─ Strategy/Outcome Memory
    ↓
Pre-Retrieval Context Program
    ↓
Sparse Probe
    ↓
Post-Probe Program Revision
    ↓
Dynamic Pipeline Execution
    ↓
Ranking / Guidance
    ↓
Outcome Recording
    ↓
更新短期上下文和符合条件的长期偏好
```

目标是实现受约束、可审计、可回退的运行时策略适配，而不是让模型自行修改源代码或全局配置。

## 6. 后续实施计划

### 阶段 0：冻结现有 I、II 和 BGE 成果

目标：在第三阶段改造前建立稳定参照，避免破坏已有能力。

工作内容：

1. 固定当前 Hashing/BGE 配置、dev SHA 和 catalog SHA。
2. 为全量 BGE 建立标准 artifact manifest，记录：
   - 模型名称；
   - catalog SHA；
   - 50,000 行；
   - 384 维；
   - parent_asin 顺序；
   - metadata SHA；
   - 标准 matrix SHA 或数值容差规则。
3. 增加正式 BGE 部署配置，不再只依赖 `StrictBgeAgent` 实验入口。
4. 保留三级降级：

```text
BGE/CUDA → Hashing Dense → Sparse-only
```

5. BGE 是否启用由部署配置决定，不硬编码本机环境。
6. 保留当前 36 项测试和 Hashing/BGE dev 结果作为回归基线。

验收条件：

- 标准 Agent 能通过配置选择 BGE；
- 部分索引、错误 catalog、错误模型或无 CUDA 环境不能伪装成有效 BGE；
- Hashing 和 BGE 基线可以复现。

### 阶段 1：实现 Personalized Context Distillation

建议新增：

```text
solution/context/
├─ schemas.py
├─ distiller.py
├─ profile_store.py
└─ policies.py
```

`DistilledContext` 至少包含：

- 当前核心目标；
- 当前意图及置信度；
- 已确认偏好；
- 暂定偏好；
- 否定偏好；
- 当前会话临时偏好；
- 长期稳定偏好；
- 未解决属性；
- 最近 Override；
- 已推荐、被否定或失效候选；
- 最近策略及效果；
- 有限长度上下文摘要；
- context revision。

每条偏好证据应包含：

- attribute/value；
- 正向或负向；
- 显式或推断；
- confidence；
- source turn/session；
- session-only 或 durable；
- 更新时间和版本。

冲突优先级固定为：

```text
当前轮显式要求
> 当前 Session 已确认槽位
> 当前 Session 推断偏好
> 长期用户画像
> 系统默认策略
```

验收条件：

- 当前请求不会被长期画像覆盖；
- Override 后不再使用失效短期证据；
- 上下文长度有固定上限；
- 相同输入和历史产生相同蒸馏结果。

### 阶段 2：实现长期用户画像

先实现协议和纯内存版本：

```python
class ProfileStore(Protocol):
    def load(profile_id: str) -> LongTermProfile: ...
    def update(profile_id: str, mutations: ...) -> LongTermProfile: ...
    def delete(profile_id: str) -> None: ...
```

建议规则：

- 单轮普通偏好只进入短期状态；
- 用户明确要求记住时允许直接提升；
- 跨多个 Session 重复确认后允许提升；
- `forget`、`don't remember`、`no preference` 能删除或降权；
- Intent Override 默认只覆盖当前 Session；
- 不保存完整原始对话，只保存最小化结构化证据。

推荐上层画像格式：

```json
{
  "profile_id": "由外部系统提供的稳定匿名 ID",
  "summary": "...",
  "preference_tags": []
}
```

没有 `profile_id` 时：

- 允许使用传入画像；
- 允许当前 Session 内更新；
- 禁止跨 Session 写入，防止用户串档。

开始实现前需要确认：

1. `profile_id` 由哪个外部层提供；
2. 首版是否只使用内存存储；
3. 什么条件允许短期偏好提升为长期偏好。

推荐首版采用：显式 `profile_id`、纯内存、默认不持久化。

### 阶段 3：实现 Adaptive Context Program

建议新增：

- `solution/orchestration.py`
- `ContextProgram`
- `AdaptiveOrchestrator`

每轮生成不可变执行计划：

```text
ContextProgram
- track
- active_routes
- route_limits
- route_weights
- hard_filtering
- constraint_relaxation_policy
- profile_weight
- dense_mode
- diversity_strength
- semantic_ranker_enabled
- semantic_ranker_top_n
- clarification_mode
- novelty_penalty
- fallback_policy
- context_revision
- reasons
```

执行分为两次规划：

1. Pre-Retrieval Plan：根据蒸馏上下文选择初始路线。
2. Post-Probe Revision：根据候选数量、route saturation 和约束情况进行受限调整。

允许运行时调整：

- 开关 BM25、Category、Metadata、Dense；
- 调整各 route 候选数；
- 动态调整 profile 权重；
- 调整多样性和重复推荐惩罚；
- 选择硬过滤或软约束；
- 决定是否调用 SemanticRanker；
- 因过载提前截止；
- 因连续失败扩大召回；
- 因模型超时进行 Session 级熔断。

`SolutionConfig` 继续保存安全上下限，Context Program 只能在配置允许范围内选择参数，不能修改共享全局配置。

验收条件：

- Buying、Browsing、Over-General、Override 产生不同且可解释的计划；
- trace 保存计划和生成原因；
- 不同 Session 的计划互不污染；
- Context Program 不能突破候选数、延迟和模型调用上限。

### 阶段 4：建立 Strategy Outcome 反馈闭环

新增 `StrategyOutcome`：

```text
- context_program
- candidate_counts
- applied_constraints
- relaxed_constraints
- recommendation_repeat_rate
- clarification_attribute
- clarification_answered
- slot_acquired
- candidate_reduction
- user_rejection
- override_detected
- llm_latency
- llm_failure
- fallback_used
```

下一轮编排使用这些结果：

- 推荐高度重复：提高 novelty/diversity；
- 连续无候选：扩大 Dense 或放松 profile；
- 用户否定属性：记录负偏好并切换澄清维度；
- 用户连续不回答问题：停止重复追问，改为结构化选项；
- Ollama 连续失败：当前 Session 临时禁用 LLM；
- 长期画像与当前请求冲突：当前任务 profile 权重降为 0；
- 多轮不收敛：允许从 precision 退回 discovery 或改问场景问题。

该阶段完成后形成：

```text
历史 → 蒸馏 → 编排 → 结果 → 策略修订
```

### 阶段 5：补充专项测试集

现有 dev 不足以完整验证第三阶段，也不覆盖真正无类别 Over-General。

#### 5.1 Context Evolution 集

覆盖：

- 多轮偏好累积；
- 临时偏好与长期画像冲突；
- 为他人购买礼物，不污染本人画像；
- 用户撤销长期偏好；
- 同属性反复修正；
- 跨 Session 重复偏好提升；
- 不同用户画像隔离；
- 无 `profile_id` 时禁止持久化。

#### 5.2 Open Browsing / Orchestration 集

建议构造 100–200 条，覆盖：

- 完全无类别短查询；
- 候选池过载；
- 连续推荐重复；
- 用户不回答澄清；
- 用户连续否定；
- Dense 扩池和缩池；
- LLM 超时或异常；
- Sparse provisional 后恢复完整路径。

新增过程指标：

- profile precision；
- profile leakage；
- slot acquisition rate；
- clarification answer rate；
- candidate reduction；
- repeated recommendation rate；
- cutoff rate；
- cutoff recovery rate；
- Context Program 分支覆盖率；
- LLM fallback rate；
- P50/P95 延迟。

### 阶段 6：性能分析和 BGE 产品化

第三阶段稳定后再进行，不建议现在直接迁移 FAISS。

执行顺序：

1. Profile 当前端到端耗时。
2. 分解 BM25、Category、BGE query encode、矩阵点积、约束过滤、reranker、context distillation 和 orchestration 耗时。
3. 根据证据选择 query cache、route cache、批量编码、FAISS IndexFlatIP 或 ANN。

如果引入 FAISS：

- 先使用精确 `IndexFlatIP`；
- 每个测试查询对比当前 Top-120；
- 要求候选集合和顺序一致，或定义严格数值容差；
- 不以未经验证的准确率损失换取性能。

服务化时同时增加：

- Session TTL；
- Response Cache 容量；
- Retrieval Cache 容量；
- Profile Store TTL；
- 显式 close/cleanup；
- GPU/CPU 内存监控。

### 阶段 7：Qwen3.5 9B Shadow 接入

Qwen 不应首先直接控制正式推荐。

推荐顺序：

1. Turn/Intent/Slot shadow parser；
2. Context Distillation shadow；
3. Context Program shadow proposal；
4. 候选语义重排；
5. 通过门槛后，仅允许低风险策略受控生效。

Qwen 输出必须经过：

- JSON Schema；
- route 白名单；
- 参数范围；
- 当前状态版本；
- 硬约束保护；
- profile 冲突保护；
- 候选 ID 完整排列；
- 超时和错误回退。

禁止模型：

- 修改源代码；
- 修改全局配置；
- 写入未确认长期画像；
- 生成新商品 ID；
- 任意跳过硬约束；
- 自行决定跨用户持久化。

RTX 3060 只有 6 GiB 显存，BGE 和 Qwen3.5 9B 同时常驻存在风险。部署前需要验证：

- 量化版本；
- GPU layers；
- CPU offload；
- BGE 与 Ollama 是否轮换驻留；
- P95 延迟；
- 峰值显存；
- 超时和熔断。

### 阶段 8：冻结与最终验证

第三阶段和 Qwen 调优结束后：

1. 冻结代码、配置、模型版本和 artifact。
2. 运行完整单元测试和专项测试。
3. 在 dev 150 做最后一次配对确认。
4. 只运行一次独立 holdout/final。
5. 查看最终结果后不再返回 dev 做针对性调参。
6. 输出最终合并报告，包含：
   - I、II、III 需求映射；
   - Hashing/BGE/Qwen ablation；
   - 总体和场景指标；
   - 性能、显存和延迟；
   - fallback 情况；
   - artifact SHA；
   - 已知风险。

## 7. 统一测试与准入门槛

### 7.1 功能门槛

- 当前显式要求始终高于长期画像；
- Intent Override 不保留失效短期条件；
- 无稳定 `profile_id` 时不发生跨 Session 写入；
- 不同用户之间 profile leakage 为 0；
- Context Program 有版本、原因和 trace；
- 非法 Context Program 回退到确定性计划；
- Qwen 不可用时保持合法候选和完整降级；
- 相同输入、上下文和 artifact 结果可复现。

### 7.2 准确率门槛

- 继续只用冻结 dev 150 调优；
- Hashing 模式 HR@10 不低于 0.913333；
- Hashing 模式技术分不低于 0.767724；
- BGE 模式 HR@10 不低于 0.913333；
- BGE 模式技术分不低于 0.770181；
- Intent Override 不应退化；
- 长期画像冲突场景不得低于关闭画像的对照；
- Qwen 启用后必须与同后端、同 split、同配置关闭 Qwen 的结果配对。

### 7.3 性能门槛

- 记录端到端 elapsed 和 P50/P95；
- 记录每个 route、distillation、orchestration 和 LLM 耗时；
- Context/Session/Profile Cache 必须有容量和 TTL；
- 新增自适应逻辑不得造成无上限内存增长；
- GPU OOM、Ollama 超时和 CUDA 不可用必须可安全降级。

## 8. 推荐执行优先级

```text
P0  冻结现有基线和 BGE 正式部署入口
 ↓
P1  Distilled Context
 ↓
P2  Profile Store
 ↓
P3  Context Program / Adaptive Orchestrator
 ↓
P4  Strategy Outcome 反馈闭环
 ↓
P5  Context/Open-Browsing 专项测试
 ↓
P6  性能优化和缓存生命周期
 ↓
P7  Qwen Shadow 与受控启用
 ↓
P8  独立 Final 验证
```

## 9. 暂时不要执行的事项

- 不针对 dev 中个别失败样本继续调权。
- 不重新使用 public 200 做开发调优。
- 不在没有稳定 `profile_id` 时实现跨用户长期画像。
- 不让 LLM 直接修改全局策略或写入长期画像。
- 不在 profiler 之前直接迁移 FAISS/ANN。
- 不默认打开 Qwen SemanticRanker。
- 不立即删除 legacy state；先兼容迁移并完成配对验证。
- 不用跨 GPU matrix SHA 不同直接判定索引错误。
- 不把专项合成数据替代官方最终评测。

## 10. 下一步建议

下一步最合理的具体任务是：

1. 确认 `profile_id` 来源和画像存储边界；
2. 确认短期偏好提升为长期偏好的业务规则；
3. 先实现不依赖 LLM 的：

```text
DistilledContext
+ InMemoryProfileStore
+ ContextProgram
+ AdaptiveOrchestrator 基础骨架
```

4. 为上述基础能力补单元测试和专项合成对话；
5. 在冻结 dev 150 上分别运行 Hashing/BGE 配对回归；
6. 指标通过后再进入 Strategy Outcome 和 Qwen Shadow 阶段。

