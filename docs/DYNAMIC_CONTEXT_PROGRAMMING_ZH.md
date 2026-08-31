# Dynamic Context Programming 实施与验证说明

> 历史说明：本报告中的“starter 未修改”描述对应当轮实验。最终提交阶段仅将
> `starter/agent.py` 改为 `solution.agent.Agent` 的入口适配器，原弱基线保存在
> `starter/baseline_agent.py`；官方 evaluator 未修改。

## 1. 本轮完成范围

本轮只补齐此前未完成和部分完成的能力，没有重新设计已经充分验证的双轨检索、硬约束、Over-Generality、官方指标或冻结数据流程。

已完成：

1. 有界、类型化 Personalized Context Distillation；
2. 需要显式 `profile_id` 的纯内存长期画像学习；
3. Pre-Retrieval / Post-Probe 两阶段 Context Program；
4. Strategy Outcome 记录和下一轮反馈闭环；
5. Qwen Session 熔断、错误分类、成功率、Token、平均/P50/P95 延迟观测；
6. 当前主链的默认关闭与 Qwen 开启完整 dev150 配对验证。

## 2. 当前执行链

```text
User Turn
  → update_state
  → profile mutation（仅显式 profile_id）
  → ContextDistiller
  → Pre-Retrieval ContextProgram
  → Sparse Probe
  → Post-Probe Program Revision
  → Dynamic Hybrid Pipeline
  → Cross-Encoder / Semantic Ranker（按计划和熔断状态）
  → Novelty / Clarification
  → StrategyOutcome
  → 下一轮蒸馏与重编排
```

所有程序都是单轮不可变值，不修改共享 `SolutionConfig`，不同 Session 的状态、画像快照和熔断互不污染。

## 3. 文件说明

| 文件 | 用途 |
|---|---|
| `solution/context/schemas.py` | 定义 `PreferenceEvidence`、`LongTermProfile`、`ProfileMutation`、`DistilledContext` |
| `solution/context/distiller.py` | 把消息、槽位、Override、推荐、画像和 Strategy Outcome 压缩成有界上下文 |
| `solution/context/profile_store.py` | `ProfileStore` 协议与纯内存实现，支持跨 Session 提升、衰减、忘记和用户隔离 |
| `solution/context/policies.py` | 识别 remember、forget、no preference、gift/session-only 和推荐拒绝 |
| `solution/orchestration.py` | 定义 `ContextProgram`、`StrategyOutcome`、两阶段编排器和 novelty penalty |
| `solution/agent.py` | 将蒸馏、画像、编排、检索、排序和 Outcome 接成闭环，并输出完整诊断 trace |
| `solution/config.py` | 保存所有上下文长度、画像、路由上限、熔断和编排安全边界 |
| `solution/query_builder.py` | 只在无当前冲突时弱使用长期画像；显式当前请求优先 |
| `solution/state.py` | 记录 Override 轮次；`no preference` 撤销当前槽位；Override 清除失效拒绝候选 |
| `solution/pipeline.py` | 接受单轮动态 profile 权重和多样性强度，不修改全局配置 |
| `solution/llm/qwen.py` | 累计成功/回退/错误类型、Token、平均/P50/P95 延迟，保持严格候选排列校验 |
| `scripts/test_ollama_integration.py` | 即使某场景失败也继续并保存完整机器可读审核报告 |
| `tests/test_context_programming.py` | 覆盖上下文边界、画像隔离、提升/撤销、计划修订、反馈、熔断和 Qwen 观测 |

## 4. Personalized Context Distillation

`DistilledContext` 当前包含：

- 当前核心目标、意图和置信度；
- 已确认、暂定、负向、Session 临时和长期稳定偏好；
- 未解决属性；
- 最近 Override；
- 已推荐及被拒绝候选；
- 最近 Strategy Outcome；
- 最近消息的有界摘要；
- 当前画像冲突属性；
- 无进展轮数和连续 LLM 失败数；
- context revision。

默认上限为最近 4 条消息、10 个候选、16 条偏好、4 条 Outcome 和 800 字符摘要。相同输入、历史和画像快照产生相同结果。

冲突优先级固定为：

```text
当前轮显式要求
> 当前 Session 确认槽位
> 当前 Session 暂定偏好
> 长期画像
> 系统默认
```

若当前请求与长期画像在同一属性上冲突，本轮 `profile_weight` 自动变为 0，长期偏好不能覆盖当前任务。

## 5. 长期画像学习与隐私边界

- 只有外部画像包含非空 `profile_id` 时才允许跨 Session 写入；
- 无 `profile_id` 时可以使用传入画像和当前 Session 状态，但禁止持久化；
- 普通单轮偏好只保留在短期状态；
- 同一偏好在两个不同 Session 被确认后才提升为长期偏好；
- `remember ...` 可以显式直接提升；
- `forget ...`、`don't remember ...`、`no preference for ...` 可以撤销；
- 画像更新时执行置信度衰减；
- gift / for someone else 类请求不会写入长期画像；
- Store 只保存最小结构化证据，不保存完整原始对话；
- 首版为进程内存，符合比赛不使用外部重型数据库和单用户 Session 假设。

## 6. Adaptive Orchestration 与反馈

每轮 Context Program 保存：路线、route limits、硬过滤、Dense 模式、多样性、profile 权重、是否调用 Qwen、Top-N、澄清模式、novelty penalty、fallback policy、context revision 和原因。

已接入的自适应规则：

- Over-General：立即停止 Dense/LLM，切换主动澄清；
- 候选过少：在配置上限内扩大 Dense；
- 多轮真正无进展：扩大召回并提高多样性/新颖性；
- 已有效回答澄清但表示无偏好：不误计为无进展；
- 用户拒绝推荐：下一轮惩罚上一轮候选；
- 当前请求与长期画像冲突：profile 权重归零；
- Intent Override：保护当前 precision 计划，不让旧推荐反馈覆盖新意图；
- 同一 Session 连续两次 LLM 失败：打开 Session 熔断，恢复确定性排序；
- 所有动态候选数、Dense、Semantic Top-N 和多样性均不能突破 `SolutionConfig` 上限。

Strategy Outcome 保存 route candidate counts、唯一候选数、候选缩减量、约束应用/放松、推荐重复率、澄清是否回答、是否获得槽位、用户拒绝、Override、LLM 延迟/失败和 fallback。下一轮蒸馏会消费这些结果。

## 7. 默认主链 dev150 回归

比较对象为同一 catalog、同一冻结 dev SHA、同一 commit 的旧 Hashing 默认 Agent。Qwen 和 Cross-Encoder 均关闭。

| 指标 | 旧默认 Agent | Context Programming Agent | 变化 |
|---|---:|---:|---:|
| HR@10 | 0.913333 | 0.920000 | +0.006667 |
| MRR | 0.597302 | 0.607254 | +0.009952 |
| MTTC ↓ | 4.406667 | 4.360000 | 改善 0.046667 |
| Efficiency | 0.659333 | 0.664000 | +0.004667 |
| Technical Score | 0.767724 | 0.774976 | +0.007252 |
| 总耗时 | 202.41 秒 | 196.13 秒 | 未增加 |

分场景结果：Browsing HR/MRR/MTTC 改善；Buying MRR/MTTC 改善；Intent Override 和 Boundary 与旧基准完全一致，没有用总体收益掩盖关键场景回归。

## 8. 当前主链 Qwen 完整配对

| 指标 | Context-only | Context + Qwen | 变化 |
|---|---:|---:|---:|
| HR@10 | 0.920000 | 0.920000 | 持平 |
| MRR | 0.607254 | 0.620931 | +0.013677 |
| MTTC ↓ | 4.360000 | 4.380000 | 退化 0.020000 |
| Efficiency | 0.664000 | 0.662000 | -0.002000 |
| Technical Score | 0.774976 | 0.778679 | +0.003703 |
| 总耗时 | 196.13 秒 | 4,800.70 秒 | 约 24.48× |

Qwen 调用审核：

- 实际请求 623 次，成功应用 546 次；
- 77 次全部为 `invalid_candidate_permutation`，安全回退；
- 成功率 87.64%，回退率 12.36%；
- 平均延迟 7.40 秒，P50 7.77 秒，P95 8.28 秒；
- reported prompt tokens 1,737,271；completion tokens 212,169；总计 1,949,440；
- 逐会话 reciprocal rank：6 条改善、2 条退化、142 条不变；没有新增或丢失 Top-10 命中；2 条会话命中变慢。

因此 Qwen 的实现、真实连接、完整量化、安全回退、观测和 Session 熔断均已完成；但默认发布门槛没有通过，`semantic_ranker_enabled=false` 必须保持。功能完成不等于默认启用。

## 9. 验证与不变量

- 49 项测试全部通过；
- `compileall`、严格 `ResourceWarning`、`git diff --check` 通过；
- 冻结数据 SHA 和样本数通过；
- 官方 `evaluator/local_evaluator.py`、`starter/agent.py` 未修改；
- catalog SHA 未变化；
- 未运行 holdout、public 或 sealed final；
- 未修改默认检索权重；
- 默认 Qwen 仍关闭。
