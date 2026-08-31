# Ollama Qwen3.5 9B 本地语义排序接入说明

## 当前状态

代码已接入 Ollama 官方本地 Chat API，模型标签为 `qwen3.5:9b`。为了保证尚未部署模型时的基线稳定性，`semantic_ranker_enabled` 默认仍为 `false`。

正常检索路径会在关键词、品类和向量召回及确定性排序之后，把 Top-N 候选交给 Qwen3.5。过泛查询的主动澄清截断仍会跳过 Dense 和 LLM，待用户补充槽位后再恢复完整路径。

官方参考：

- [Ollama qwen3.5:9b 模型](https://ollama.com/library/qwen3.5:9b)
- [Ollama Chat API](https://docs.ollama.com/api/chat)
- [Ollama Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)

## 部署与启用

```powershell
ollama pull qwen3.5:9b
ollama run qwen3.5:9b
```

Ollama 默认监听 `http://127.0.0.1:11434`。代码侧显式启用：

```python
from solution.agent import Agent
from solution.config import SolutionConfig

config = SolutionConfig(semantic_ranker_enabled=True)
agent = Agent(config=config, diagnostics=True)
```

如服务地址不同，可配置：

```python
config = SolutionConfig(
    semantic_ranker_enabled=True,
    semantic_ranker_base_url="http://127.0.0.1:11434",
)
```

## 默认参数

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `semantic_ranker_backend` | `ollama` | 本地 Ollama 后端 |
| `semantic_ranker_model` | `qwen3.5:9b` | 官方 9B 模型标签 |
| `semantic_ranker_top_n` | `30` | 交给模型重排的候选数 |
| `semantic_ranker_timeout_ms` | `120000` | 包含首次模型加载的请求超时 |
| `semantic_ranker_keep_alive` | `10m` | Ollama 模型驻留时间 |
| `semantic_ranker_temperature` | `0` | 降低排序随机性 |
| `semantic_ranker_num_ctx` | `8192` | 当前排序请求上下文窗口 |
| `semantic_ranker_num_predict` | `1024` | 最大输出 token 预算 |

请求固定使用 `stream:false`、`think:false` 和 JSON Schema。Schema 要求返回每个输入 `parent_asin` 恰好一次。

## 安全与降级

- 仅发送当前 Top-N 商品的有限 catalog 摘要，不发送完整目录。
- catalog 文本按不可信输入处理，系统提示禁止执行商品文本内的指令。
- 模型只能重排候选，不能新增、删除、重复或修改商品 ID。
- 连接失败、超时、HTTP 错误、超过 1 MiB 的响应、非法 JSON、未知 ID、缺失 ID 或重复 ID 均回退到原确定性排序。
- Agent 初始化不会探测或拉取模型，因此 Ollama 离线时默认配置不受影响。

## 合并后的真实模型验收

1. 确认 `ollama list` 中存在 `qwen3.5:9b`。
2. 使用一个 Buying 和一个 Browsing 会话确认诊断中的 `backend=ollama`、`applied=true`。
3. 检查 `prompt_tokens`、`completion_tokens`、`last_latency_ms` 和 `last_error`。
4. 对冻结开发集分别运行 LLM 关闭和开启版本，比较 HR@10、MRR、MTTC 与总延迟。
5. 验证过泛首轮仍为 `over_generality_cutoff`，用户补充槽位后的下一轮才调用 Ollama。

当前自动测试使用模拟 Ollama 响应，不需要下载模型；真实模型质量与性能必须在部署机器上完成最终复验。

## 本机真实模型冒烟测试

仓库提供独立测试入口。它会先检查本地模型标签，然后运行一个 Buying、一个 Browsing 和一个 Over-General 会话：前两项必须真实调用 Qwen，第三项必须在主动澄清截断处跳过 LLM。所有推荐 ID 都会再次验证为当前只读 catalog 的成员，结果可保存为 JSON。

```powershell
python scripts/test_ollama_integration.py `
  --catalog data/catalog.jsonl `
  --output experiments/runs/ollama_qwen35_live_smoke.json
```

如果 catalog 位于其他本地目录，可通过 `--catalog` 传入绝对路径。该测试只覆盖连接、结构化输出、安全边界、回退路径和延迟记录，不替代冻结 dev 的准确率配对评测。

冻结 dev 的完整配对实验入口为：

```powershell
python -m experiments.run_experiment `
  --config experiments/configs/qwen_hashing_dev.json `
  --name qwen_hashing_dev
```

该实验必须与同一 commit、同一 catalog、同一 dev split 的 LLM 关闭版本比较；不得读取 holdout 调权。

## 2026-08-31 本机验收结果

- 环境：Ollama `0.33.2`，模型 `qwen3.5:9b`，RTX 5070 Ti Laptop 12 GB；Ollama 报告模型约占 5.7 GB、100% GPU，检索侧使用 Hashing Dense 50K catalog。
- Buying：`applied=true`，Prompt 2815 tokens，Completion 387 tokens，模型调用约 6.67 秒。
- Browsing：`applied=true`，Prompt 2990 tokens，Completion 385 tokens，模型调用约 6.27 秒。
- Over-General：`retrieval_cutoff=true`，Ollama 请求增量为 0，usage 为 0，原因是 `over_generality_cutoff`。
- 三个会话总耗时约 46.25 秒，推荐均为 10 个不重复 catalog ID；未发现新增、未知或重复 ASIN。

以上是连接与安全边界的冒烟验收，不是准确率结论。默认权重和 `semantic_ranker_enabled=false` 保持不变，未读取 holdout，也未执行 final split。

## Dynamic Context Programming 合并后的最终 dev150 结果

当前主链已重新进行严格配对，不能与上面的早期 Hashing 报告混用：

- Context-only：HR@10 0.920000、MRR 0.607254、MTTC 4.360000、196.13 秒；
- Context + Qwen：HR@10 0.920000、MRR 0.620931、MTTC 4.380000、4,800.70 秒；
- 623 次请求中 546 次成功，77 次 `invalid_candidate_permutation` 安全回退；
- 成功率 87.64%，回退率 12.36%；平均 7.40 秒、P50 7.77 秒、P95 8.28 秒；
- HR 未改善、MTTC 轻微退化、耗时约 24.48 倍，默认启用门槛未通过；
- `semantic_ranker_enabled=false` 保持不变，未运行 holdout/final。

当前报告见 `docs/QWEN35_CONTEXT_DEV_ABLATION_ZH.md`。冒烟工具现在会在单场景失败后继续检查其余场景并保存 JSON；它仍以非零退出码明确报告失败。
