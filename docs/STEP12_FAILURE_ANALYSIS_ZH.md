# Project 4 步骤 12：系统化失败分析与审核结论

> 历史说明：本报告记录 Step 12 当时的文件状态。最终提交打包阶段已将
> `starter/agent.py` 改为正式 Agent 的薄适配器；原弱基线移至
> `starter/baseline_agent.py`，官方 evaluator 仍未修改。

## 1. 本轮范围

本轮只在冻结 `dev 150` 上重跑当前默认 Agent，并对全部 miss 做逐轮重放。目标是定位召回、融合、约束过滤、最终排序和提问策略的通用失败模式，不在本轮修改排序权重。

严格边界：

- 未读取 `holdout.jsonl`、`public_set.jsonl` 或任何 final-only split；
- catalog 前后 SHA256 保持一致；
- 未修改 `evaluator/local_evaluator.py` 或 `starter/agent.py`；
- 每轮最多返回 10 个用于审核的推荐 ID，全部属于只读 catalog；
- 不使用 sample ID、目标 ASIN 或单个失败案例编写特殊规则；
- 默认 `semantic_ranker_enabled=false`，本轮不是 Qwen 准确率实验。

## 2. 冻结 dev 结果

运行配置为 Hashing Dense、Cross-Encoder 关闭、Qwen 关闭。完整 150 条耗时 202.41 秒。

| 指标 | 结果 |
|---|---:|
| HR@10 | 0.913333 |
| MRR | 0.597302 |
| MTTC | 4.406667 |
| Efficiency | 0.659333 |
| TechnicalScore | 0.767724 |

| 场景 | 样本 | 命中 | Miss | Miss 率 | MRR | MTTC |
|---|---:|---:|---:|---:|---:|---:|
| Buying | 60 | 55 | 5 | 8.33% | 0.599107 | 3.566667 |
| Browsing | 60 | 57 | 3 | 5.00% | 0.641653 | 4.816667 |
| Intent Override | 22 | 18 | 4 | 18.18% | 0.462428 | 5.500000 |
| Boundary | 8 | 7 | 1 | 12.50% | 0.622024 | 4.625000 |

Intent Override 是当前最明显的场景短板，但 4 个 override miss 在新意图生效后都已进入最终列表，问题主要位于头部排序而非状态未清除。

## 3. 13 个失败会话的根因

| 根因 | 数量 | 证据 |
|---|---:|---|
| 全路由未召回 | 2 | BM25、Category、Metadata、Hashing Dense、融合和最终列表均未出现目标 |
| 最终排名超过 10 | 11 | 目标进入最终完整列表，但最佳位置仍为第 12–100 名 |
| 融合阶段丢失 | 0 | 已召回目标没有在融合中消失 |
| 约束过滤误删 | 0 | 本轮没有目标进入融合后被完全过滤 |

路由覆盖：BM25 召回 10/13，Metadata 召回 9/13，Category 召回 5/13，Hashing Dense 召回 3/13，最终完整列表可见 11/13。

最终最佳排名分布：

- 完全缺失：2；
- 第 11–20 名：2；
- 第 21–50 名：8；
- 第 51 名以后：1。

这说明下一轮不能单纯扩大所有候选池。应先处理两个全路由未召回，再用通用排序证据验证两个 Top 20 近失，最后才考虑更深位置的候选。

## 4. 对话与效率审核

- 13 个失败会话共提出 91 次问题，平均每个会话 7 次；
- 重复 ask_attribute 的失败会话为 0；
- 第 8–10 轮均停止继续提问，符合当前问题窗口；
- 0 个失败会话触发 Over-General 截断，因为官方初始消息已经包含具体粗类目；
- 9 个失败会话应用了硬约束，1 个发生安全放宽；
- Qwen 生效轮次为 0，Token 使用为 0，符合默认关闭基线。

当前问题不是“重复问同一属性”，而是部分会话连续获得“没有额外偏好”，仍用满 7 个不同属性。下一轮可研究基于连续无信息回答的提前停止或策略切换，但必须用独立的对话专项集验证，不能只凭 13 个 miss 调整。

## 5. 建议的下一轮顺序

1. **召回缺失专项**：对 2 个 `not_recalled` 会话比较目标文本与通用 query builder，测试类目规范化、字段查询和 BGE 补充是否能跨样本提高召回。
2. **Top 20 近失专项**：先对最终第 12、19 名的候选做竞争项特征对比；Qwen 只能重排冻结 Top 30，必须保留完整候选排列验证与关闭开关。
3. **Override 专项**：继续使用 override 生效后的 eligible rank，核对新意图查询和通用 reranker；不把覆盖前目标出现视为有效命中。
4. **Boundary 专项**：检查 Category/Dense 证据为什么在最终排序中被压到第 100 名，保持“无偏好”不生成伪约束。
5. **提问效率专项**：对连续两次无新槽位的会话试验停止追问或切换到场景问题，评估 MTTC、slot acquisition 和重复推荐率。
6. **严格配对**：任何改动只在同一 dev SHA、catalog SHA 和 commit 上与本报告配对；通过后才能讨论一次 final-only 确认。

## 6. Qwen 与步骤 12 的关系

步骤 11 已完成本机 Qwen 连接与安全冒烟测试，但默认正式路径仍关闭 LLM。步骤 12 的基线报告因此不把 Qwen 冒烟结果与 Hashing dev 指标混合。

后续 Qwen 准确率实验必须满足：

- 同一冻结 dev split；
- 同一检索后端和权重；
- 关闭/开启 Qwen 的配对结果；
- 记录 HR@10、MRR、MTTC、总耗时、P50/P95、Token 和 fallback；
- 只有 dev 指标与延迟门槛同时通过，才允许一次未使用 final split 确认。

## 7. 复现命令

```powershell
python -m experiments.verify_frozen_data

python -m experiments.run_experiment `
  --config experiments/configs/hybrid_steps_3_10.json `
  --name step12_hashing_dev `
  --run-dir experiments/runs/step12_hashing_dev `
  --overwrite

python -m experiments.trace_failures `
  --results experiments/runs/step12_hashing_dev/results.json `
  --dataset data/splits/dev.jsonl `
  --catalog data/catalog.jsonl `
  --agent solution.agent:Agent `
  --output experiments/analysis/step12_hashing_dev_failures.json `
  --review-limit 20

python -m experiments.finalize_failure_report `
  --input experiments/analysis/step12_hashing_dev_failures.json
```

详细逐轮报告位于 `experiments/analysis/step12_hashing_dev_failures.md`；同名 JSON 保存完整状态、查询、问题、路由 rank、Top 10、约束和 LLM 状态。
