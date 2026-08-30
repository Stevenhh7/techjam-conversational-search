# 50K BGE GPU 本轮结果与大模型接入计划

## 本轮已保存成果

- GPU：NVIDIA GeForce RTX 5070 系列，12 GB 显存。
- 运行时：ONNX Runtime GPU 1.29.0，CUDAExecutionProvider，CUDA 13/cuDNN 9。
- 模型：`BAAI/bge-small-en-v1.5`。
- 索引：50,000 行 × 384 维，`float16`，约 38.4 MB。
- catalog SHA256：`da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`。
- BGE matrix SHA256：`7f3bd95ecb598191969893c0682305346cb8776dcd012416efaa367aaee7f49a`。
- metadata SHA256：`42bcc26659cf3b2fa8d96a9072acb75ce1ef717fb21ffbafd905c36f88723686`。
- 元数据确认：`complete_catalog=true`、`build_provider=CUDAExecutionProvider`。

## 同 dev split 严格 ablation

权重、候选数、RRF、reranker、对话状态与澄清策略全部冻结。唯一变量是 Dense 后端。

| 方案 | HR@10 | MRR | MTTC | 技术分 | 耗时/秒 |
|---|---:|---:|---:|---:|---:|
| hashing paired dev | 0.906667 | 0.593405 | 4.453333 | 0.762288 | 139.352 |
| 50K BGE GPU dev | **0.920000** | **0.616587** | **4.353333** | **0.777909** | **137.163** |

BGE 同时改善 HR、MRR、MTTC 和技术分，配对耗时没有增加，因此通过 dev 晋级门槛。

## sealed final 状态

已生成一个与 public 目标 ASIN 零重叠的 200 条 catalog-synthetic sealed final：

- 路径：`data/splits/final_bge_200.jsonl`
- SHA256：`993bed4bd40ce400a6158094d81cb14ea57561a6c4ba5f1aa56dac9115524d8c`
- 场景：80 buying、80 browsing、30 intent override、10 boundary
- public target overlap：0
- 未预生成 intent_card

应用户“尽快结束”要求，本次 final 在完成前停止，没有生成 `results.json`，因此没有有效 final 指标，也没有据此调参。该数据仍保持 sealed，可作为下一轮唯一一次确认任务。它是额外合成泛化证据，不能替代官方私有 800。

## 下一步任务顺序

1. 在资源允许时完成 sealed final 的唯一一次 BGE 运行；完成后封存结果，不再调权。
2. 将向量搜索从 NumPy 50K 暴力乘法迁移到 FAISS GPU/CPU IndexFlatIP，并要求 Top-120 与当前精确检索逐查询一致。
3. 为 evaluator 增加只写进度、不暴露标签的 checkpoint，避免长 final 中断后全部重算。
4. BGE artifact 不提交 Git；在 GitHub Release 或对象存储中发布 SHA256 校验后的构建产物。
5. 接入大模型时先采用 shadow mode，只比较结构化意图解析，不直接改变推荐列表。

## 大模型接入的具体计划

### 1. 接口层

新增以下文件：

- `solution/llm/base.py`：定义 `IntentExtractor` 协议。
- `solution/llm/openai_compatible.py`：OpenAI-compatible HTTP 客户端。
- `solution/llm/schemas.py`：严格 JSON Schema 和服务端校验。
- `solution/llm/fallback.py`：包装当前规则解析器，任何失败立即回退。

环境变量只在运行时读取：

```text
TECHJAM_LLM_ENABLED=0
TECHJAM_LLM_BASE_URL=https://<provider>/v1
TECHJAM_LLM_API_KEY=<secret>
TECHJAM_LLM_MODEL=<model-name>
TECHJAM_LLM_TIMEOUT_MS=1500
TECHJAM_LLM_MAX_TOKENS=300
```

API key 不写入配置、日志、结果文件或 Git。

### 2. 模型只输出结构化意图

第一阶段只允许模型输出：

```json
{
  "intent": "buying|browsing|override",
  "buying_probability": 0.0,
  "category": "string|null",
  "constraints": ["string"],
  "exclusions": ["string"],
  "override": false,
  "no_preference_attribute": "string|null"
}
```

模型不接收 ground truth、不接收 evaluator hidden intent card、不接收完整 catalog，也不能直接生成 ASIN。最终推荐 ID 仍只能来自 BM25/metadata/BGE 候选和 catalog 字典。

### 3. 安全与确定性

- `temperature=0`，固定系统提示词与 JSON Schema 版本。
- 请求只包含当前消息、已确认约束和去标识化聚合画像。
- 超时、限流、无效 JSON、Schema 不通过或网络失败时回退当前规则 parser。
- 按规范化输入和状态哈希缓存结果；缓存记录模型、提示词版本和响应 SHA256。
- 连续失败触发 circuit breaker，本会话后续全部使用规则 parser。
- 日志不记录 API key、完整用户画像或自由文本原文。

### 4. Shadow mode

默认 `TECHJAM_LLM_ENABLED=0`。首次实验设置为 shadow：

- 规则 parser 继续驱动正式推荐。
- LLM 解析结果仅写入独立诊断记录。
- 比较 category、constraints、override 和 ask_attribute 差异。
- 不读取 holdout，只在 dev 做失败审计。

### 5. 晋级门槛

LLM 只有同时满足以下条件才可进入 active ablation：

- dev HR@10 不低于 0.920000；
- dev MRR 不低于 0.616587；
- MTTC 不变差超过 0.10 轮；
- P95 LLM 延迟不超过 1.5 秒；
- 单会话最多调用 3 次；
- fallback 成功率 100%，非法 ASIN 数为 0；
- 记录每 200 会话的 token 和费用上限。

### 6. 推荐的模型顺序

1. 先接一个支持 JSON Schema 的 OpenAI-compatible API 模型，验证接口、回退和成本。
2. 再测试本地 7B/8B instruct 模型（Ollama 或 vLLM），保持同一 Schema 与测试集。
3. 只比较意图解析能力；商品知识仍由 50K catalog+BGE 提供。
4. 若 LLM active dev 未同时改善 HR/MRR，则保留 shadow，不进入最终 Agent。

## 复现命令

```powershell
# GPU 依赖
.\.venv\Scripts\python -m pip install -r requirements-gpu.txt

# 完整 BGE；中断后追加 --resume
.\.venv\Scripts\python scripts\build_embeddings.py `
  --backend fastembed --provider cuda --batch-size 512 --checkpoint-every 2048

# 同 dev split BGE ablation
.\.venv\Scripts\python -m experiments.run_experiment `
  --config experiments\configs\bge_dense_dev.json

# 下一轮唯一 sealed final
.\.venv\Scripts\python -m experiments.run_experiment `
  --config experiments\configs\bge_dense_dev.json `
  --dataset data\splits\final_bge_200.jsonl --final-eval
```
