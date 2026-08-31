# 最终提交检查清单

## GitHub

- [ ] 最终仓库为 Public；
- [ ] 默认分支包含干净提交；
- [ ] `git status --short` 无输出；
- [ ] 未提交 `data/catalog.jsonl`、Dense/BGE 索引、模型缓存、`.venv`、`.vscode` 或密钥；
- [ ] GitHub 文件列表中没有个人绝对路径和实验临时目录；
- [ ] 从 GitHub 全新 clone 后完成安装、索引构建、测试和三轮演示。

## 默认入口

- [ ] `agent:Agent` 指向 `solution.agent.Agent`；
- [ ] `starter.agent:Agent` 指向 `solution.agent.Agent`；
- [ ] `evaluator/local_evaluator.py` 未修改；
- [ ] `python -m evaluator.local_evaluator` 运行的是最终方案；
- [ ] 原弱基线保存在 `starter.baseline_agent:Agent`。

## Devpost

- [ ] 替换 `docs/DEVPOST_DESCRIPTION.md` 中的 GitHub 链接；
- [ ] 替换 YouTube Public 视频链接；
- [ ] 团队成员与贡献符合真实情况；
- [ ] 列出 Python、SQLite FTS5、NumPy、FastEmbed、Ollama/Qwen 和本地 Web 前端；
- [ ] 说明 Qwen 默认关闭的实测原因；
- [ ] 指标明确标记为 dev150，不声称私有集同分；
- [ ] 写明数据来源、已知限制和未来改进。

## Demo

- [ ] 首次加载后看到 `系统就绪`；
- [ ] 三轮脚本完整通过；
- [ ] 输入框每轮恢复可用；
- [ ] 终端 `demo/cli_demo.py` 可作为备用；
- [ ] 视频未显示密钥、个人路径、通知或未授权商标素材。
