# ContextCart 现场演示与视频录制流程

## 演示目标

用 3–5 分钟证明四件事：

1. Agent 能区分开放浏览与高意图购买；
2. 多轮状态会积累，也能在 Intent Override 时删除过期偏好；
3. 检索策略会随上下文和候选池动态变化；
4. 推荐结果全部来自只读目录，并有可复现指标和安全降级。

## 演示前 15 分钟

在一个全新终端进入最终提交仓库：

```powershell
cd "<最终提交仓库路径>"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe demo\app.py
```

打开 <http://127.0.0.1:7860>，等待绿色状态条显示：

```text
系统就绪 · 目录 50,000 件商品 · Dense: hashing
```

准备事项：

- 浏览器缩放设为 90%–100%；
- 清空其他标签页和系统通知；
- 不展示本地用户名、API 密钥、Ollama 日志或绝对文件路径；
- 不启动 Qwen，主流程使用已验证的默认确定性 Agent；
- 将 `experiments/analysis/context_programming_dev_summary.json` 作为指标备份；
- 另开一个终端，准备 `python demo\cli_demo.py` 作为浏览器故障备援。

## 3–5 分钟现场脚本

### 0:00–0:30 问题与方案

讲解词：

> 传统搜索把每一轮当作独立关键词，但真实用户会先探索、再增加条件，甚至突然改变目标。ContextCart 不只是保存聊天历史，而是把当前上下文编译成每轮可执行的检索程序。

指向页面顶部的 dev150 指标卡，但明确说明它是开发集结果，不代表私有 800 条同分。

### 0:30–1:15 第一轮：开放浏览与主动截断

输入：

```text
Show me some ideas.
```

应展示：

- `browsing / DISCOVERY`；
- `retrieval_cutoff = true`；
- Agent 主动询问 feature；
- Dense/LLM 被跳过，页面仍返回目录内 Top-10。

讲解词：

> 这是一个过宽请求。系统先停止昂贵路线，再主动问一个高信息量问题，避免无意义地消耗一轮和模型延迟。

### 1:15–2:00 第二轮：信息积累与完整召回

输入：

```text
For that, what matters is: waterproof.
```

应展示：

- 偏好进入蒸馏上下文；
- 截断解除；
- BM25、Metadata、Dense 等路线恢复；
- 候选池与 Top-10 更新；
- Agent 继续询问尚未确定的 category。

讲解词：

> 用户回答后，状态机获得新槽位，Context Program 重新授权完整召回。页面右侧同时显示每个商品来自哪些路线。

### 2:00–3:00 第三轮：Intent Override 与 Buying 精准路线

输入：

```text
Actually, ignore my earlier preference. What I need is: material: leather; category: shoes; under $100.
```

应展示：

- `buying / PRECISION`；
- `override = 1`；
- `material:leather` 成为已应用约束；
- Top-10 主要为鞋类，召回证据来自多条路线；
- Agent 询问 size 或其他尚未确定的购买属性。

讲解词：

> “Actually” 不是普通关键词。系统会执行可审计的覆盖操作，删除与新目标冲突的旧偏好，同时保留仍然有效的信息。当前请求永远优先于长期画像。

### 3:00–3:40 指标与工程取舍

展示指标卡：HR@10 0.92、MRR 0.607254、MTTC 4.36、TechnicalScore 0.774976。

讲解词：

> 我们也完成了 Qwen3.5 9B 的全量开发集对照。它改善 MRR，但没有提高 Hit Rate，MTTC 略差，而且慢 24.48 倍，因此没有设为默认。这是基于证据的部署门控，不是尚未接入模型。

### 3:40–4:20 安全性与落地性

讲解词：

> 所有 ASIN 都由只读 catalog 产生。Dense 索引必须通过 catalog SHA 校验；文件、依赖或模型缺失时会安全降级。默认路径离线运行，不依赖付费 API、外部向量数据库或密钥。

## 视频录制建议

- 画面顺序：标题页 5 秒 → 本地前端三轮 → 指标 → 架构图 → 限制与下一步；
- 视频建议 3–5 分钟，1080p，保证表格与诊断文字可读；
- 不播放完整 150 条评测，展示已保存、带 SHA 的摘要即可；
- 不展示 Amazon 商品图片或第三方商标，页面只显示比赛目录中的文本字段；
- 上传 YouTube 并设为 Public，再把链接填入 Devpost 和 `docs/DEVPOST_DESCRIPTION.md`。

## 故障备援

### 页面打不开

```powershell
.\.venv\Scripts\python.exe demo\app.py --port 7861
```

然后打开 <http://127.0.0.1:7861>。

### 浏览器交互异常

运行相同三轮的终端演示：

```powershell
.\.venv\Scripts\python.exe demo\cli_demo.py
```

该脚本输出路线、候选数、截断、询问属性、蒸馏上下文、编排原因和 Top-10。

### Dense 未启用

检查页面状态条。若 SHA 匹配的 hashing 索引不存在，执行：

```powershell
.\.venv\Scripts\python.exe scripts\build_embeddings.py --backend hashing
```

不要在现场临时下载 BGE 或启动 Qwen。

## 结束前检查

- 三轮后输入框仍可继续输入；
- 页面没有 `运行失败`；
- 第三轮显示 `PRECISION` 和 `material:leather`；
- Top-10 ASIN 无重复；
- Git 工作区为 clean；
- Devpost 中 GitHub 与 YouTube 链接均为公开可访问；
- 团队成员贡献文字已按真实情况更新。
