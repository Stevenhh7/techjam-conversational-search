# Qwen3.5 9B 完整 dev 量化验证报告

> 历史报告：本文件记录接入 Dynamic Context Programming 之前的 Hashing 主链。当前主链结果以 `docs/QWEN35_CONTEXT_DEV_ABLATION_ZH.md` 为准，两组数据不可混用。

## 1. 审核结论

本轮只验证本地 Ollama `qwen3.5:9b` Top-30 语义重排，不调整默认检索权重，不启用 Cross-Encoder，不切换 BGE，也不读取 holdout、public 或 sealed final 调参。

**结论：Qwen 在冻结 dev150 上提高了 MRR，但没有提高 HR@10，同时 MTTC 和运行延迟变差，因此不满足“HR 与 MRR 同时改善且耗时可接受”的默认启用门槛。默认 `semantic_ranker_enabled=false` 应保持不变，本轮不生成、不运行新的 final split。**

## 2. 严格配对设置

| 项目 | Qwen-off 基准 | Qwen-on 候选 |
|---|---|---|
| Agent | `solution.agent:Agent` | `solution.ablations:OllamaQwenAgent` |
| 数据 | `data/splits/dev.jsonl`，150 条 | 相同 |
| Dataset SHA256 | `c8955cacd79bb2e2ed6b984979bca91f379fc699648c5bc2e3ac2efb37f8b22a` | 相同 |
| Catalog SHA256 | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` | 相同 |
| Git commit | `cb15f6dbc3339ee8af6a98d7b44ca6b795d84dd3` | 相同 |
| Dense | Hashing，50K catalog | 相同 |
| Cross-Encoder | 关闭 | 关闭 |
| Qwen | 关闭 | Ollama `qwen3.5:9b`、Top-30 |
| 温度 / seed / thinking | 不适用 | `0` / `0` / `false` |
| 上下文 / 最大输出 | 不适用 | 8192 / 1024 tokens |
| 官方 evaluator | 未修改 | 未修改 |

本机预检环境为 Ollama 0.33.2、NVIDIA GeForce RTX 5070 Ti Laptop GPU 12 GB。真实冒烟测试验证了 Buying/Browsing 会调用 Qwen、Over-General 会跳过 Qwen、推荐 ID 全部来自只读 catalog。

## 3. 总体指标

| 指标 | Qwen-off | Qwen-on | 变化 | 判定 |
|---|---:|---:|---:|---|
| HR@10 | 0.913333 | 0.913333 | 0.000000 | 持平，未改善 |
| MRR | 0.597302 | 0.611868 | +0.014566（约 +2.44%） | 改善 |
| MTTC ↓ | 4.406667 | 4.420000 | +0.013333 | 轻微退化 |
| Efficiency | 0.659333 | 0.658000 | -0.001333 | 退化 |
| Technical Score | 0.767724 | 0.771827 | +0.004103（约 +0.53%） | 改善 |

Qwen 没有扩大 Top-10 覆盖边界；收益来自少数已经命中的目标被推到更靠前的位置。

## 4. 分场景指标

| 场景 | 样本 | HR@10 变化 | MRR：off → on | MTTC：off → on |
|---|---:|---:|---:|---:|
| Buying | 60 | 0 | 0.599107 → 0.623413 | 3.566667 → 3.600000 |
| Browsing | 60 | 0 | 0.641653 → 0.642487 | 4.816667 → 4.816667 |
| Intent Override | 22 | 0 | 0.462428 → 0.493182 | 5.500000 → 5.500000 |
| Boundary | 8 | 0 | 0.622024 → 0.622024 | 4.625000 → 4.625000 |

主要 MRR 收益来自 Buying（+0.024306）和 Intent Override（+0.030754）。Boundary 完全不变，Browsing 仅提高 0.000834。

## 5. 逐会话配对结果

| 结果 | 会话数 |
|---|---:|
| Reciprocal Rank 改善 | 8 |
| Reciprocal Rank 退化 | 2 |
| 排名不变 | 140 |
| 新增 Top-10 命中 | 0 |
| 丢失 Top-10 命中 | 0 |
| 更早命中 | 1 |
| 更晚命中 | 2 |
| 命中轮次不变 | 147 |

最大改善包括：

- `public_0183`（Intent Override）：rank 4 → 1；
- `public_0097`（Buying）：rank 3 → 1，但命中轮次 3 → 4；
- `public_0101`（Buying）：rank 3 → 1，但命中轮次 1 → 3。

明确退化包括：

- `public_0130`（Intent Override）：rank 3 → 4；
- `public_0023`（Intent Override）：rank 8 → 9。

这说明 Qwen 的排序收益高度集中：150 条中只有 10 条的 reciprocal rank 发生变化，而且两项最大的排名收益伴随更晚命中，解释了 MRR 上升但 MTTC 轻微变差的组合。

## 6. 调用成功率、Token 与延迟

| 项目 | 结果 |
|---|---:|
| 实际会话 | 150 |
| 实际评测轮次 / Qwen 请求 | 650 |
| 成功应用 Qwen 排序 | 554 |
| 安全回退 | 96 |
| 成功率 | 85.23% |
| 回退率 | 14.77% |
| Prompt tokens | 1,763,233 |
| Completion tokens | 215,302 |
| 总 reported tokens | 1,978,535 |
| 平均每次成功调用 prompt tokens | 约 3,182.7 |
| 平均每次成功调用 completion tokens | 约 388.6 |
| Qwen-off 总耗时 | 202.41 秒 |
| Qwen-on 总耗时 | 4,612.09 秒（约 76 分 52 秒） |
| 总耗时倍率 | 约 22.79× |
| 相对基准增量耗时 | 4,409.69 秒 |
| 估算每次请求增量耗时 | 约 6.78 秒 |

Token 统计只包含成功返回并应用的结果；安全回退请求没有可靠的服务端 token 记录，不能将上述 token 总数解释为全部 650 次请求的真实消耗。

当前适配器只保存累计请求数、累计成功数和最后一次错误，未保存每次调用的错误类别及延迟序列。因此本轮能精确确认 96 次安全回退，但不能在不重新全量运行的情况下把它们进一步拆分为超时、HTTP、JSON 或候选排列错误，也不能给出严格的 P50/P95。该观测缺口不影响 HR/MRR/MTTC 的官方结果，但会降低故障诊断能力。

## 7. 门槛审核

| 启用条件 | 本轮结果 | 是否通过 |
|---|---|---|
| HR@10 改善 | 0.913333 → 0.913333，仅持平 | 否 |
| MRR 改善 | +0.014566 | 是 |
| MTTC 不恶化 | +0.013333，轻微恶化 | 否 |
| 延迟可接受 | 总耗时约 22.79×，估算每请求增加约 6.78 秒 | 否 |
| 调用稳定 | 成功率 85.23%，回退率 14.77% | 否 |

最终判定：**不通过默认启用门槛**。

本轮不读取或运行 holdout/final，不修改默认开关。若将来继续研究 Qwen，应先增加逐请求错误类别与 P50/P95 观测，再在 dev 上试验更小候选窗口、条件触发或只对低置信度会话调用；这些属于后续工作，不在本轮范围内。

## 8. 原始产物

- Qwen-off：`experiments/runs/step12_hashing_dev/`
- Qwen-on：`experiments/runs/qwen_hashing_dev_full/`
- Qwen-on 原始结果 SHA256：`3cae42a31bf5a3dd895183b651d1f247c88f1b02ce4492a5995eeefd56cb4a67`
- 机器可读摘要：`experiments/analysis/qwen_hashing_dev_ablation.json`
