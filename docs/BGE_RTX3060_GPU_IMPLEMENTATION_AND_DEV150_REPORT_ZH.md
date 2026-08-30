# RTX 3060 全量 BGE GPU 实现与 dev 150 配对评测报告

## 1. 结论

本机已经在 **E 盘项目目录**完成 `BAAI/bge-small-en-v1.5` 的 50,000 商品全量向量构建，并通过严格 CUDA BGE Agent 在冻结 `dev 150` 上完成配对评测。

- 全量索引有效：`50000 × 384`、`float16`、`complete_catalog=true`。
- 构建与查询均可使用 `CUDAExecutionProvider`；评测时观测到 Python GPU 计算进程、约 27% GPU 利用率和约 1.9 GiB 总显存占用。
- 相比当前 Hashing 基线，BGE 的总体 HR@10 持平，MRR、MTTC、Efficiency 和推荐技术分均有净提升，没有低于现有总体准确率。
- BGE 不是每个场景都单向提升：Intent Override 明显改善，Browsing HR@10 小幅下降一个样本。当前证据支持保留 BGE，但不支持针对两个样本硬编码规则。
- 精确向量搜索已做安全性能优化：磁盘仍保存 `float16`，启动时一次性转换为内存 `float32` BLAS 矩阵；40 个查询的矩阵点积微基准提升约 12.31 倍，Top-120 顺序完全一致。
- 本轮没有真正调用 LLM，报告中的 token 使用量为 0；Ollama/Qwen3.5 9B 接口仍保持默认关闭，符合当前“暂时可不用 LLM”的约束。

## 2. 数据集身份与本轮边界

### 2.1 `public 200` 是否自行构建

不是。本仓库的 `data/public_set.jsonl` 是原始官方公开开发集合，共 200 条会话。其冻结记录为：

- 样本数：200
- 角色：`final_only`
- 当前文件 SHA-256：`571359a8a69014c43fc30d39c996c4a28e875dccc249dffc707358757beb16c0`

此前工作区曾因 LF/CRLF 行尾不同产生另一个文件字节哈希，但 JSONL 语义和 Git 内容一致。本轮已经恢复仓库期望的行尾形式，并通过冻结数据校验。

### 2.2 `dev 150` 的来源

`data/splits/dev.jsonl` 不是另一套官方独立测试集，而是项目从官方 `public 200` 以固定 seed `techjam-2026-v1`、按场景分层确定性切出的冻结调优子集：

- 样本数：150
- SHA-256：`c8955cacd79bb2e2ed6b984979bca91f379fc699648c5bc2e3ac2efb37f8b22a`
- Buying：60
- Browsing：60
- Intent Override：22
- Boundary：8
- 角色：`tuning`

剩余 50 条为冻结 holdout，未在本轮读取或评测。用户确认允许改用 dev 150 后，本轮停止了尚未完成的 public 200 运行，删除其空的不完整运行目录，之后只采纳完整 dev 150 指标。

### 2.3 断点与部分数据

- 没有把 512/2,048 商品 smoke 索引当作正式结果；这些临时产物已删除。
- 正式 BGE 索引从头构建 50,000 行，没有从部分索引断点恢复。
- `StrictBgeAgent` 会拒绝 `complete_catalog=false`、商品数量不符、catalog SHA 不符、模型不符或 CUDA 不可用的产物。
- 评测器仅在 150 条全部完成后写入并采纳汇总；中断运行没有被当作指标。

## 3. 本机环境

| 项目 | 值 |
|---|---|
| GPU | NVIDIA GeForce RTX 3060 Laptop GPU |
| 显存 | 6,144 MiB |
| NVIDIA Driver | 610.47 |
| Python | 3.13.3 |
| FastEmbed | 0.7.3 |
| ONNX Runtime GPU | 1.29.0 |
| NumPy | 2.5.2 |
| ORT device | GPU |
| 可用 Provider | TensorRT、CUDA、CPU |
| 项目/虚拟环境/缓存/索引 | 均位于 E 盘项目目录 |

Windows 下 FastEmbed 会按依赖名安装 CPU `onnxruntime`，它与 `onnxruntime-gpu` 共用同一个 Python 模块路径，可能导致 CPU wheel 覆盖 GPU wheel。本轮新增安装脚本，在安装依赖后卸载两个 ORT 分发包，再以 `--no-deps --force-reinstall` 最后安装 GPU wheel，并强制断言 CUDA provider 存在。

模型推理出现的“部分节点未分配给首选 provider”是 ONNX Runtime 对 shape 等节点放到 CPU 的普通提示，不代表整个模型回退到 CPU。评测期间的 GPU 进程和利用率采样进一步确认 CUDA 实际工作。

## 4. 全量索引结果

| 属性 | 结果 |
|---|---|
| 模型 | `BAAI/bge-small-en-v1.5` |
| 行数 | 50,000 |
| 维度 | 384 |
| 磁盘 dtype | `float16` |
| NPY 大小 | 38,400,128 bytes |
| 模型缓存大小 | 67,181,178 bytes |
| 构建 Provider | `CUDAExecutionProvider` |
| 构建耗时 | 约 55.66 秒 |
| catalog SHA-256 | `da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67` |
| matrix SHA-256 | `31137495bb7a3d3eddaef04af361556ec848fd39de167a8590968a654e871243` |
| metadata SHA-256 | `42bcc26659cf3b2fa8d96a9072acb75ce1ef717fb21ffbafd905c36f88723686` |

同事 RTX 5070 机器历史报告中的 matrix SHA 为 `7f3bd95e...`，本机 matrix SHA 不同，但 metadata SHA、catalog SHA、形状、dtype、行顺序和完整性一致。最可能原因是不同 GPU/CUDA 图执行带来的低位数值差异；不能把跨 GPU 的矩阵字节哈希相等作为唯一正确性条件。合并时仍应明确选定并发布一个标准 artifact，同时提供其 SHA。

## 5. 代码改动

### 5.1 E 盘 GPU 环境

- 新增 `scripts/setup_gpu_environment.ps1`：创建 E 盘 `.venv`，将 pip cache 和临时目录放到 E 盘，修正 CPU/GPU ONNX wheel 覆盖问题，并断言 CUDA provider。
- 更新 `requirements-gpu.txt`：记录 FastEmbed/ORT Windows 冲突和正确安装入口。
- 更新 `.gitignore`：忽略 E 盘项目内可重建的 pip cache 和临时目录。

### 5.2 全量构建与离线加载

- `scripts/build_embeddings.py` 新增 `--cache-dir`，模型缓存默认落在 `artifacts/fastembed_cache`。
- 新增 `--local-files-only`，首次下载完成后，后续构建不再访问网络。
- `SolutionConfig` 新增 `dense_cache_dir`。
- `Agent` 解析项目相对缓存目录并传给 `DenseRetriever`。
- `DenseRetriever` 运行时强制 `local_files_only=True`，避免线上请求和缓存漂移。

### 5.3 精确搜索性能优化

原实现直接执行：

```python
scores = float16_memmap @ float32_query
```

NumPy 在本机的 CPU `float16` 矩阵向量路径明显较慢。当前实现保留紧凑的 `float16` 磁盘文件，在加载并完成完整性校验后，一次性建立 `float32` 内存搜索矩阵，再执行精确内积。

固定随机种子的 50,000×384、40 查询微基准：

| 指标 | 原路径 | 优化路径 |
|---|---:|---:|
| 40 次矩阵点积 | 1.9913 秒 | 0.1617 秒 |
| 一次性转换成本 | - | 0.0418 秒 |
| 点积加速比 | - | 12.31× |
| 40 组 Top-120 交集 | - | 全部 120/120 |
| 40 组 Top-120 有序结果 | - | 全部完全一致 |
| 最大分数差 | - | 0.0 |

端到端 Hashing dev 150 的耗时从此前相同指标运行的 306.818 秒下降到 295.450 秒，约减少 3.71%。端到端收益小于点积微基准，说明 BM25、对话状态、约束处理和重排仍占主要耗时。

## 6. dev 150 严格配对结果

两次运行使用相同 catalog、相同 dev SHA、相同权重、相同候选数、相同状态机、相同澄清策略和关闭的 LLM；唯一核心变量是 Dense 后端。

| 方案 | HR@10 | MRR | MTTC ↓ | Efficiency | 技术分 | 耗时 |
|---|---:|---:|---:|---:|---:|---:|
| 当前 Hashing | 0.913333 | 0.597302 | 4.406667 | 0.659333 | 0.767724 | 295.450s |
| 全量 BGE/CUDA | 0.913333 | 0.603272 | 4.373333 | 0.662667 | 0.770181 | 332.911s |
| BGE 改变量 | 0.000000 | +0.005970 | +0.033334 改善 | +0.003334 | +0.002457 | +37.461s |

结论：总体命中率没有下降，MRR 和技术分提升，平均命中轮次略提前；代价是完整评测耗时增加约 12.68%。

### 6.1 分场景结果

| 场景 | 方案 | HR@10 | MRR | MTTC ↓ |
|---|---|---:|---:|---:|
| Boundary | Hashing | 0.875000 | 0.622024 | 4.625000 |
| Boundary | BGE | 0.875000 | 0.684524 | 4.625000 |
| Browsing | Hashing | 0.950000 | 0.641653 | 4.816667 |
| Browsing | BGE | 0.933333 | 0.649372 | 4.850000 |
| Buying | Hashing | 0.916667 | 0.599107 | 3.566667 |
| Buying | BGE | 0.916667 | 0.588724 | 3.533333 |
| Intent Override | Hashing | 0.818182 | 0.462428 | 5.500000 |
| Intent Override | BGE | 0.863636 | 0.487680 | 5.272727 |

关键差异：

- BGE 在 Intent Override 新救回 `public_0198`，该场景 HR 提升 4.55 个百分点。
- BGE 在 Browsing 丢失 `public_0076`，该场景 HR 下降 1.67 个百分点。
- Buying 命中数持平、MTTC 略好，但 MRR 略低。
- Boundary 命中数和 MTTC 不变，MRR 明显改善；该分组只有 8 条，需谨慎解释。
- 共 35/150 个会话的首次命中轮次或最佳名次发生变化，BGE 的影响不是只来自两个命中翻转样本。

## 7. 测试与证据

- 冻结数据验证：通过，dev/public/holdout 的样本数和哈希符合 `experiments/frozen_datasets.json`。
- 单元测试：36/36 通过。
- 新增回归测试验证：磁盘 `float16` 索引会被提升为内存 `float32` 搜索矩阵，形状不变。
- Hashing 优化前后总体指标逐项完全一致。
- BGE 严格运行状态：`dense.enabled=true`、`dense.backend=fastembed`。
- LLM 状态：disabled；prompt/completion token 均为 0。
- 配对差异文件：`experiments/runs/gpu_round_bge_dev/comparison_vs_hashing.json`。

实验运行目录属于可重建产物，已由 `.gitignore` 忽略，但当前 E 盘工作区中保留，方便本机复核。

## 8. 当前问题与风险

1. **BGE 未在每个场景胜出。** 总体技术分净提升，但 Browsing HR 和 Buying MRR 有回退。后续应在独立 holdout/final 上验证，不应继续依据 dev 两个翻转样本手调。
2. **BGE 查询编码有端到端成本。** 当前 BGE dev 150 比 Hashing 慢约 37.46 秒。精确矩阵搜索已优化，下一热点应通过 profiler 确认，不能直接假设必须引入 FAISS。
3. **跨 GPU artifact 字节不一致。** 元数据和结构一致但矩阵 SHA 不同；发布/合并时必须选择单一标准构建产物及 SHA，或定义允许的数值容差验证流程。
4. **ORT 包元数据冲突。** 为保证 CUDA 模块最终生效，GPU wheel 最后以 `--no-deps` 安装；`pip check` 可能仍报告 FastEmbed 声明的 CPU `onnxruntime` 分发缺失。运行时 CUDA provider 断言比包名检查更可靠，但团队文档必须保留这一说明。
5. **6 GiB GPU 余量有限。** 当前 BGE-small 工作正常；未来同时常驻 Qwen3.5 9B 时很可能无法全部放入这块 GPU，需要 Ollama 分层卸载、量化、CPU offload 或独立设备规划。
6. **LLM 尚未进入本轮准确率。** 现有 Ollama 接口和安全降级已就绪，但 Qwen3.5 9B 未下载、未运行，不能宣称已经验证“BGE + LLM”的最终效果。
7. **官方 public 200 未在本轮完成。** 这是按用户要求主动停止以避免用 final-only 集调参；本报告只代表 dev 150 调优证据，不代表最终官方成绩。

## 9. 推荐后续顺序

1. 合并时统一 BGE artifact 来源，核对 catalog SHA、metadata SHA、行数和 provider；不要提交 `.npy` 到 Git，可通过 Release/对象存储发布。
2. 冻结当前代码和权重，在独立 holdout 或规定的最终集合上只运行一次 BGE 验证；查看后不再回到 dev 调权。
3. 使用 profiler 拆分 BM25、BGE query encode、矩阵点积、约束和 reranker 耗时，再决定是否加入 FAISS IndexFlatIP。若加入，逐查询校验 Top-120 与当前精确实现一致。
4. 部署 Ollama/Qwen3.5 9B 后先做 shadow 评测；仅当同一冻结集合的 HR/MRR 不下降且超时/格式错误可安全降级时，才打开 `semantic_ranker_enabled`。
5. 针对 `public_0076` 和 `public_0198` 做语义失败分析，但只提炼可泛化机制，不添加 sample-id、目标商品或答案特征硬编码。

## 10. 复现命令

首次安装与首次模型下载：

```powershell
.\scripts\setup_gpu_environment.ps1
.\.venv\Scripts\python.exe scripts\build_embeddings.py `
  --backend fastembed `
  --provider cuda `
  --batch-size 512 `
  --checkpoint-every 50000 `
  --cache-dir artifacts\fastembed_cache
```

缓存就绪后的离线全量重建：

```powershell
.\.venv\Scripts\python.exe scripts\build_embeddings.py `
  --backend fastembed `
  --provider cuda `
  --batch-size 512 `
  --checkpoint-every 50000 `
  --cache-dir artifacts\fastembed_cache `
  --local-files-only
```

冻结校验与配对评测：

```powershell
.\.venv\Scripts\python.exe -m experiments.verify_frozen_data

.\.venv\Scripts\python.exe -m experiments.run_experiment `
  --config experiments\configs\hybrid_steps_3_10.json `
  --name gpu_round_hashing_dev `
  --dataset data\splits\dev.jsonl `
  --run-dir experiments\runs\gpu_round_hashing_dev

.\.venv\Scripts\python.exe -m experiments.run_experiment `
  --config experiments\configs\bge_dense_dev.json `
  --name gpu_round_bge_dev `
  --dataset data\splits\dev.jsonl `
  --run-dir experiments\runs\gpu_round_bge_dev

.\.venv\Scripts\python.exe -m experiments.compare_runs `
  experiments\runs\gpu_round_hashing_dev `
  experiments\runs\gpu_round_bge_dev
```

