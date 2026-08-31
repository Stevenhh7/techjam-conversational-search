# ContextCart 本地前端演示

`demo/app.py` 是现有 `solution.agent.Agent` 的轻量展示层。前端采用仓库内的单页 HTML/CSS/JavaScript，后端仅使用 Python 标准库 HTTP 服务，因此不需要 Gradio、Node.js、云服务或 API 密钥。它不会修改产品目录、检索逻辑或官方 evaluator；所有推荐 ASIN 均来自只读的 50K 比赛目录。

## 安装与启动

在仓库根目录执行：

```powershell
python -m pip install -r requirements.txt
python demo/app.py
```

浏览器打开 <http://127.0.0.1:7860>。服务默认只监听本机，不创建公网链接。首次启动需要加载 50K 目录与内存索引；等待遮罩层自动消失并显示“系统就绪”后开始演示。

如端口被占用：

```powershell
python demo/app.py --port 7861
```

## 建议现场流程

依次发送：

1. `Show me some ideas.`
2. `For that, what matters is: waterproof.`
3. `Actually, ignore my earlier preference. What I need is: material: leather; category: shoes; under $100.`

第一轮发送结束后，输入框和发送按钮会恢复可用；同一页面可以连续完成最多 10 轮。页面同步显示：

- Buying/Browsing 路线与意图置信度；
- Over-Generality 截断和主动澄清；
- 多路候选数量、运行时 Context Program 与本轮约束；
- Top-10 商品、ASIN、类目、价格和评分；
- 蒸馏上下文、Intent Override、LLM 是否应用及安全降级原因。

“验证证据”页只读取仓库中已保存的 dev150 聚合摘要，不会在演示时读取评测标签、目标 ASIN 或重新运行 public/holdout。

## 本地 API

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/status` | 初始化、目录、Dense 和 LLM 状态 |
| GET | `/api/scenarios` | 无标签的固定演示场景 |
| GET | `/api/evidence` | 已保存的 dev150 聚合证据 |
| POST | `/api/reset` | 创建隔离会话 |
| POST | `/api/respond` | 执行一轮真实 Agent 推理 |
| POST | `/api/llm` | 显式开启或关闭本地 Qwen 排序器 |

请求体最大 64 KB，单条消息最大 2,000 字符，会话严格限制为 10 轮。Agent 的初始化和调用固定在同一个专用线程，避免 SQLite FTS 连接跨线程造成第二轮卡死。

## 可选 Qwen

默认保持 Qwen 关闭，以使用已验证的确定性方案。若现场机器已运行 Ollama，可在页面中显式开启，或在启动前配置：

```powershell
$env:CONTEXTCART_LLM_ENABLED = "true"
$env:CONTEXTCART_LLM_MODEL = "qwen3.5:9b"
python demo/app.py
```

其他环境变量包括 `CONTEXTCART_WEB_PORT`、`CONTEXTCART_LLM_BACKEND`、`CONTEXTCART_LLM_BASE_URL`、`CONTEXTCART_LLM_TIMEOUT_MS` 和 `CONTEXTCART_LLM_TOP_N`。即使 Ollama 不可用，严格校验与确定性回退也不会使整个 Agent 失败。

## 设计边界

- 页面固定 Top-10，并强制执行比赛的 10 轮上限。
- 默认使用已验证配置，Qwen 不因页面启动而自动开启。
- 多个浏览器会话以随机 `session_id` 隔离，目录和索引只加载一次。
- 页面不接触评测目标，不参与调参，也不改变任何评测结果。
- 关闭终端进程即可停止服务（`Ctrl+C`）。

终端备用演示：

```powershell
python demo/cli_demo.py
```
