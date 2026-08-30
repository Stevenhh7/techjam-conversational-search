# Dialog Strategy：Multi-Turn Scenario Evolution 改造审核与交接

## 1. 审核结论

本轮完成了显式动态对话状态机、可审计 Slot Store、增量信息累积、全局与属性级 Intent Override、候选过载检测、特殊轮次检索截止，以及结构化主动澄清。

正常且信息充分的请求仍执行第一阶段确定的完整链路：

```text
Keyword + Category + Metadata + Vector
→ Hybrid Fusion
→ Deterministic Ranking
→ SemanticRanker
→ Top 10
```

仅当请求处于 discovery track、类别开放、没有有效 slot、查询过于宽泛或稀疏候选过载，且仍有可询问属性时，才执行特殊截止：

```text
Sparse Probe
→ Over-Generality
→ 跳过 Dense/Cross Encoder/SemanticRanker
→ Sparse Provisional Top 10
→ Structured Proactive Clarification
```

用户补充 slot 后，下一轮自动恢复完整 Dense/LLM 路径。

最终冻结 dev 配对结果不低于上一阶段基线，HR 保持不变，MRR、MTTC 和技术分略有提升。因此本轮成果通过准确率门槛，可作为后续 Qwen/BGE 和真实对话流量测试的基础。

## 2. 需求完成情况

| 要求 | 状态 | 实现 |
|---|---|---|
| Dynamic State Machine | 已完成 | 显式 phase、转换原因、状态版本与历史 |
| Information Accumulation | 已完成 | 结构化 slot 增量加入、legacy 字段兼容同步 |
| Intent Override | 已完成 | full、attribute、category 三类重写 |
| Slot Erasure/Rewriting | 已完成 | reset/replace/add 审计记录 |
| Over-Generality Detection | 已完成 | 查询具体度、slot 数、候选数、route saturation |
| Immediate Retrieval Cutoff | 已完成 | 特殊轮次在 Sparse Probe 后停止 Dense/语义阶段 |
| Provisional Top 10 | 已完成 | 使用稀疏候选；为空时使用 catalog 合法热门回退 |
| Proactive Structured Guidance | 已完成 | 单属性、候选示例、已知条件摘要、避免重复 |
| Slot Reply Context | 已完成 | 使用 pending clarification 解释 Acme/shoes 等未知文本 |
| Normal LLM Pipeline | 保持 | 非 cutoff 轮次仍调用 SemanticRanker 边界 |

## 3. 数据与实验基线

| 项目 | 值 |
|---|---|
| Catalog 行数 | 50,000 |
| Catalog SHA256 | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` |
| Dev 样本数 | 150 |
| Dev SHA256 | `c8955cacd79bb2e2ed6b984979bca91f379fc699648c5bc2e3ac2efb37f8b22a` |
| Dense 后端 | signed hashing，50K × 384 |
| LLM | Deferred/disabled，正常路径保留接口调用 |
| 对照 run | `experiments/runs/post_dual_track_v2` |
| 最终 run | `experiments/runs/post_dialog_state_final` |

`data/public_set.jsonl` 仍保留工作区原有换行状态，没有由本轮修改。重新生成的 dev SHA256 与冻结清单一致，本轮只在冻结 dev 上进行配对调优和验证。

## 4. 最终准确率

### 4.1 总体指标

| 指标 | 第二阶段改造前 | 最终代码 | 变化 |
|---|---:|---:|---:|
| HR@10 | 0.913333 | **0.913333** | 持平 |
| MRR | 0.596968 | **0.597302** | +0.000334 |
| MTTC | 4.413333 | **4.406667** | -0.006666，越低越好 |
| Efficiency | 0.658667 | **0.659333** | +0.000666 |
| Technical Score | 0.767490 | **0.767724** | +0.000234 |

### 4.2 场景指标

| 场景 | HR@10 | MRR | MTTC | 与对照差异 |
|---|---:|---:|---:|---|
| Buying | 0.916667 | 0.599107 | 3.566667 | HR/MRR 相同，MTTC +0.016667 |
| Browsing | 0.950000 | 0.641653 | 4.816667 | 完全相同 |
| Intent Override | 0.818182 | **0.462428** | **5.500000** | MRR +0.002273，MTTC -0.090909 |
| Boundary | 0.875000 | 0.622024 | 4.625000 | 完全相同 |

总体准确率通过“不低于现有水平”的门槛。Buying MTTC 有一个样本级的小幅波动，但 Intent Override 改善使总体 MTTC 和技术分提高。

## 5. 动态状态机

新增阶段：

```text
new
discovery
clarifying
constrained
ready
overloaded
rewriting
```

典型转换：

```text
new
  └─ 空泛请求 → discovery → overloaded → clarifying
                                      ↓ 用户补充 slot
                                constrained → ready

constrained
  └─ full override → rewriting → constrained/ready

constrained
  └─ attribute rewrite → rewriting → constrained/ready
```

每次 phase 变化记录：

- turn
- from_phase
- to_phase
- reason

同一 phase 内的重复计算不会生成无意义的重复 transition。

## 6. Slot Store 与信息累积

`SessionState` 新增：

```text
slot_store
slot_history
dialogue_phase
transition_history
state_revision
last_processed_turn
last_processed_message
pending_clarification
over_generality
```

每个 active slot 继续复用 `Constraint`：

- attribute
- operator
- value
- confidence
- source_turn
- hard
- raw

每次变化用 `SlotMutation` 审计：

- add
- replace
- replace_value
- reset

记录旧值、新值、turn 和 reason。

### 6.1 增量信息

普通多轮回复会追加非重复 slot。例如：

```text
material=cotton
→ use_case=hiking
→ budget<=100
```

现有 `hard_constraints`、`soft_preferences` 和预算字段继续保留，用于兼容 QueryBuilder 和 Reranker；当前 `slot_store` 是新的结构化视图。本轮没有一次性删除 legacy 状态。

### 6.2 上一轮问题上下文

当用户只回答：

```text
Acme
hiking boots
medium
```

词表本身可能无法确定属性。系统会读取 `pending_clarification.attribute`，将普通回答解释为上一轮所问的 brand/category/size。

如果用户使用显式 `material: leather` 或发出 intent override，则优先尊重显式内容，不受上一轮问题类型限制。

## 7. Intent Override 语义

### 7.1 Full Override

触发形式包括：

- ignore my earlier preference
- ignore everything
- forget everything
- start over

清理：

- hard constraints
- soft preferences
- structured constraints
- exclusions
- budget min/max

保留会话 ID、历史、已问属性和原类别；如果新消息明确提供类别，则更新类别。

### 7.2 Attribute Override

例如：

```text
Actually, blue instead of black.
Change the size to large.
```

只替换对应属性，其他 slot 保留。

### 7.3 Category Override

例如：

```text
I'm looking for hiking boots instead of running shoes.
```

替换 category，并清除对旧类别依赖较强的 category/size/style slot；预算等通用条件保留。

### 7.4 轮次保护

- 相同 turn、相同输入：返回缓存响应，不重复执行 Dense/LLM 或修改状态。
- 相同 turn、不同输入：拒绝。
- 旧 turn 覆盖新状态：拒绝。

## 8. Over-Generality 检测

新增 `OverGeneralityDecision`：

```text
overloaded
confidence
reasons
unique_candidate_count
saturated_routes
query_term_count
active_slot_count
```

检测信号：

1. 当前必须是 discovery track。
2. category 必须为空或属于 product/clothing/item 等泛类别。
3. active slot 数不能超过配置阈值。
4. 查询 token 过少，或者候选唯一数超限，或者多个 sparse route 饱和。

默认配置：

```text
over_generality_cutoff_enabled=true
over_generality_max_query_terms=4
over_generality_max_active_slots=0
over_generality_min_unique_candidates=160
over_generality_min_saturated_routes=2
over_generality_ask_until_turn=9
```

如果所有属性都已问过/不可用，或者超过 cutoff 提问窗口，则不再截止，恢复完整检索，避免系统无法继续收敛。

## 9. 两阶段检索

### 9.1 Probe

`HybridPipeline.probe()` 执行：

- BM25 keyword
- Category Route
- metadata BM25
- sparse fusion
- unique candidate count
- route saturation

正常路径复用 Probe 结果，不会重复执行稀疏查询。

### 9.2 Full Path

非 over-general 请求继续执行：

- Dense
- fusion/supplement
- hard constraint policy
- deterministic rerank
- optional cross encoder
- SemanticRanker

### 9.3 Cutoff Path

过载轮次执行 `HybridPipeline.provisional()`：

- 不调用 Dense
- 不调用 Cross Encoder
- 不调用 SemanticRanker
- 对稀疏候选做轻量确定性排序
- 返回 provisional Top 10
- 稀疏候选为空时只使用 catalog 内合法热门商品补足

SemanticRanker 诊断 reason 明确记录为：

```text
over_generality_cutoff
```

它与 `ranker_disabled`、模型异常 fallback 不混淆。

## 10. 主动澄清

`choose_clarification()` 返回结构化决策：

```text
attribute
score
reason
coverage
entropy
expected_reduction
example_values
prompt
```

选择仍基于候选覆盖率、属性熵、预期候选缩减和策略先验，并保留：

- 每轮只问一个合法属性
- 不重复询问
- 不询问用户已声明无偏好的属性
- category 已明确时不再问 category

Over-General 提示会说明候选过宽，并尽可能包含：

- 当前已确认条件
- 一个明确属性问题
- 当前候选中出现的 2–3 个示例值

## 11. 诊断与失败追踪

Agent trace 新增：

- dialogue phase
- state revision
- slot store
- Probe candidate count
- saturated routes
- over-generality reasons/confidence
- retrieval cutoff
- clarification score/entropy/examples
- semantic skip reason

`experiments/trace_failures.py` 已同步导出这些字段，后续真实 Qwen 接入时可以逐轮审查：

- 为什么跳过模型
- 哪个 slot 导致恢复完整检索
- override 删除了哪些旧值
- 哪个澄清问题被选择

## 12. 测试结果

当前完整回归为 `35/35` 测试通过。对话策略新增覆盖：

- 全局 override slot reset
- 属性级 black → blue rewrite
- category override 且保留 budget
- override 不受上一轮问题错误类型影响
- Slot Store 增量累积
- pending clarification 类型推断
- stale/conflicting turn 拒绝
- 重复 respond 返回缓存且不重复调用 Dense/Ranker
- 候选数量和多 route 饱和检测
- Over-General 首轮跳过 Dense/Ranker
- cutoff 仍返回合法 provisional recommendations
- 主动提示与 `ask_attribute`
- 用户补充 slot 后恢复 Dense/Ranker
- 既有检索、排序、Dense 降级和 Agent 合同回归

## 13. 性能

| 版本 | 150 dev 耗时 |
|---|---:|
| 第二阶段对照 | 293.023 秒 |
| 最终状态机版本 | 306.818 秒 |
| 变化 | +13.796 秒，约 1.047 倍 |

该差异可能包含机器运行波动，但当前没有证据证明状态机完全无开销。正常路径 Probe 会复用稀疏结果；真正 Over-General 轮次会跳过 Dense/LLM，理论上显著更快，但官方 dev 缺少无类别过载样本，无法用该集合验证整体节省比例。

## 14. 当前问题与风险

### 14.1 公开 dev 不覆盖真正的 Over-General 首轮

评测器会根据目标商品生成具体类别，因此 dev 的 Browsing 初始消息通常不是完全开放请求。Cutoff 正确性由专项合成测试验证，但真实触发率、阈值和用户收敛率需要独立数据集或线上 shadow 日志。

### 14.2 Intent/Slot Parser 仍是英文规则

当前适合比赛模板及常见 rewrite 句式，但自由语言、中文、复杂否定、多个替代选项仍可能误判。Qwen 接入时建议先 shadow 输出 TurnEvent/SlotMutation，不直接修改正式状态。

### 14.3 Context Slot Typing 可能过度信任上一问

普通无前缀回复默认解释为上一轮所问属性。如果用户无视问题、主动回答另一属性，可能发生误分类。显式 `attribute: value` 和 override 已优先处理；未来可通过模型置信度或确认机制改进。

### 14.4 Provisional 结果不具备 Dense 跨类别能力

这是 cutoff 的设计目的：先收敛再进行昂贵语义检索。用户补充 slot 后下一轮恢复 Dense/LLM。若产品要求首轮必须展示语义多样结果，可配置关闭 cutoff，但会违背本模块的主动收敛目标。

### 14.5 状态存在双份表示

`slot_store/structured_constraints` 与 legacy hard/soft/budget 字段目前并存，降低迁移风险，但增加维护成本。后续需要在完整 BGE/Qwen 指标稳定后统一数据源。

### 14.6 Session/Response Cache 无跨会话回收策略

比赛会话最多 10 轮，当前风险可控；长期服务化时应增加 session TTL、容量上限和显式 close/reset 清理。

### 14.7 Qwen/BGE 仍待合并

本轮没有下载或管理模型。真实模型上线后需要重新验证：

- 正常路径 Ranker 调用率
- cutoff skip 率
- slot 收敛轮数
- P95 延迟
- token/cost
- fallback 率
- HR/MRR/MTTC

## 15. 主要改动文件

新增：

- `solution/state_machine.py`
- `solution/generality.py`

修改：

- `solution/schemas.py`
- `solution/state.py`
- `solution/constraint_parser.py`
- `solution/intent.py`
- `solution/clarification.py`
- `solution/pipeline.py`
- `solution/agent.py`
- `solution/config.py`
- `solution/README.md`
- `experiments/trace_failures.py`
- `tests/test_solution.py`

未修改：

- `evaluator/local_evaluator.py`
- `starter/agent.py`
- catalog 内容
- 官方指标公式

## 16. 复现命令

```powershell
# 单元与回归测试
python -m unittest discover -s tests -v

# 最终冻结 dev 评测
python -m experiments.run_experiment `
  --config experiments\configs\hybrid_steps_3_10.json `
  --run-dir experiments\runs\post_dialog_state_final

# 与第二阶段改造前比较
python -m experiments.compare_runs `
  experiments\runs\post_dual_track_v2 `
  experiments\runs\post_dialog_state_final
```

## 17. 后续工作建议

1. 构造 100–200 条真正无类别、短查询、候选过载的对话集，校准 cutoff 阈值。
2. 接入 Qwen shadow parser，比较 TurnEvent 和 SlotMutation，不立即控制正式状态。
3. BGE 合并后复测正常路径与 cutoff 恢复路径。
4. 对 Context Slot Typing 增加置信度和“你是指品牌 Acme 吗？”确认策略。
5. 为 session state、response cache 和 retrieval cache 增加 TTL/容量策略。
6. 统计 clarification attribute → slot acquisition → 下一轮候选缩减的真实转化漏斗。

## 18. 最终审核意见

本轮已经满足 Dynamic State Machine、Information Accumulation、Intent Override、Over-Generality Cutoff 和 Proactive Guidance 的代码要求，并保持第一阶段正常 LLM Pipeline 的结构不变。

冻结 dev 证明准确率未下降；Over-General 特殊分支由专项测试证明不会调用 Dense/Ranker，并能在用户补充 slot 后恢复完整链路。成果可以进入下一模块或 Qwen/BGE 合并准备阶段。
