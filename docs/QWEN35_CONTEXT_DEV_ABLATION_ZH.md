# 当前 Context Programming 主链 Qwen3.5 dev150 验证

## 结论

Qwen3.5 9B 的功能、真实连接、完整 dev 量化、错误分布、Token、平均/P50/P95 延迟、安全回退和 Session 熔断均已完成。

**发布门槛未通过：保持 `semantic_ranker_enabled=false`，不运行 final。**

## 配对指标

| 指标 | Context-only | Context + Qwen | 变化 |
|---|---:|---:|---:|
| HR@10 | 0.920000 | 0.920000 | 0 |
| MRR | 0.607254 | 0.620931 | +0.013677 |
| MTTC ↓ | 4.360000 | 4.380000 | 退化 0.020000 |
| Efficiency | 0.664000 | 0.662000 | -0.002000 |
| Technical Score | 0.774976 | 0.778679 | +0.003703 |
| 总耗时 | 196.13 秒 | 4,800.70 秒 | 约 24.48× |

分场景：Buying MRR +0.022917、MTTC 退化 0.05；Intent Override MRR +0.030754；Browsing 和 Boundary 完全不变。

逐会话：6 条 reciprocal rank 改善、2 条退化、142 条不变；没有新增或丢失 Top-10 命中；2 条命中变慢。

## 模型调用审核

| 项目 | 结果 |
|---|---:|
| Qwen 请求 | 623 |
| 成功应用 | 546 |
| 安全回退 | 77 |
| 成功率 | 87.64% |
| 回退率 | 12.36% |
| 错误 | 77 次 `invalid_candidate_permutation` |
| 平均延迟 | 7.40 秒 |
| P50 | 7.77 秒 |
| P95 | 8.28 秒 |
| Prompt tokens | 1,737,271 |
| Completion tokens | 212,169 |
| Total tokens | 1,949,440 |

诊断确认 Ollama 可能在满足数组长度的同时重复一个合法 ID 并遗漏另一个，未实际执行 JSON Schema 的 `uniqueItems`。系统不会接受或自动修补此类输出，而是保持原确定性排序。连续两次失败后仅在当前 Session 内熔断；新 Session 不受影响。

## 完整性

- Agent：`solution.ablations:OllamaQwenAgent`；
- 模型：本地 Ollama `qwen3.5:9b`；Top-30；temperature 0；seed 0；`think:false`；
- Dataset SHA256：`c8955cacd79bb2e2ed6b984979bca91f379fc699648c5bc2e3ac2efb37f8b22a`；
- Catalog SHA256：`da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`；
- Qwen-on results SHA256：`95463f74d33cfdcebf86f36fd68cc6911d8e6e9e33f05e539c6bdd3227d9c0c5`；
- 未修改官方 evaluator/starter；
- 未运行 holdout、public 或 sealed final；
- 机器可读报告：`experiments/analysis/qwen_context_dev_ablation.json`。

门槛判断：HR 未改善、MTTC 退化、延迟不可接受，因此“功能完成”不等于“默认启用”。
