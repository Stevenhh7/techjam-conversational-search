# 当前仓库比赛要求完成状态

## 最终状态表

| 比赛要求 | 当前状态 | 当前仓库证据与结论 |
|---|---|---|
| Buying/Browsing 双轨识别 | ✅ 已完成 | `routing.py` 生成 precision/discovery 两套执行方案，配置、过滤、Dense 和多样性不同 |
| Buying 高精度硬约束 | ✅ 已完成 | Buying 启用硬过滤；候选塌缩时执行有记录的保守放松 |
| Browsing Dense 多样召回 | ✅ 已完成 | Dense semantic pool、软类目和跨类目多样化均进入主链 |
| Keyword + Category + Vector 多路召回 | ✅ 已完成 | BM25、Category、Metadata、Dense 独立召回并融合，全部内存运行 |
| LLM Semantic Ranking | ✅ 功能完成，默认禁用 | Ollama Qwen3.5 Top-30、JSON Schema、候选完整排列、错误回退、Session 熔断和完整观测均已实现；量化未通过发布门槛，因此默认关闭 |
| 多轮信息积累 | ✅ 已完成 | 类目、槽位、预算、排除项、软硬偏好、澄清回答和状态版本逐轮积累 |
| Intent Override | ✅ 已完成 | 完整、属性级和类目级覆盖；显式记录 override 轮次，清理失效短期反馈并保护新 precision 计划 |
| Over-Generality 截断 | ✅ 已完成 | 稀疏 Probe 检测过载，跳过 Dense/LLM，输出 provisional Top-10 和主动澄清，补充信息后恢复 |
| Personalized Context Distillation | ✅ 已完成 | 类型化 `DistilledContext` 区分确认/暂定/负向/临时/长期偏好，使用历史和 Outcome，长度固定且可审计 |
| 长期用户画像学习 | ✅ 已完成（内存版） | `ProfileStore` 协议和内存实现；显式 profile ID、跨 Session 提升、remember、forget、衰减、gift 隔离、无 ID 禁止持久化 |
| Adaptive Orchestration | ✅ 已完成 | Pre/Post 两阶段 `ContextProgram`、动态扩池/截断/画像权重/去重/Override 保护/LLM 熔断及 `StrategyOutcome` 闭环 |
| HR@K | ✅ 已完成 | 官方 evaluator 计算总体和分场景 HR@10；当前默认 dev150 为 0.920000 |
| MRR / Top-K | ✅ 已完成 | 官方 evaluator 计算 MRR；当前默认 dev150 为 0.607254 |
| MTTC | ✅ 已完成 | 官方 evaluator 对命中轮次和超过 10 轮失败计分；当前默认 dev150 为 4.360000 |
| LLM 增益验证 | ✅ 已完成，结论不启用 | 当前主链同 dev 配对完成：HR 持平、MRR +0.013677、MTTC -0.020000、耗时 24.48×、回退率 12.36%，不进入默认链路或 final |
| Catalog 只读与 ID Grounding | ✅ 已完成 | 推荐只来自 catalog 字典；重复、未知和伪造 ASIN 被过滤或拒绝，catalog SHA 审核不变 |
| Dense 索引完整性与降级 | ✅ 已完成 | catalog SHA、行数、模型和 complete_catalog 校验；依赖/文件缺失、部分或陈旧索引安全降级 |
| 确定性与会话隔离 | ✅ 已完成 | 同输入、历史和快照产生相同蒸馏/检索/融合/计划；响应缓存、画像和熔断按 Session 隔离 |
| 冻结数据实验治理 | ✅ 已完成 | dev 用于 tuning；holdout/public/final 标记 final_only；本轮未访问 final-only 数据 |
| 失败审计与实验复现 | ✅ 已完成 | 保存 config、metadata、结果、失败 CSV、SHA、Git 状态、逐会话分析和中文报告 |
| 自动测试与工程检查 | ✅ 已完成 | 当前 49 项测试、严格 ResourceWarning、compileall、diff check 和冻结数据校验通过 |

## 重要发布说明

当前默认推荐 Agent 应使用 Context Programming + Hashing Dense，Qwen 保持关闭。Qwen 条目的“功能完成”表示接入、控制、量化和失败处理完整，不表示它已经达到默认发布门槛。

当前默认 dev150：HR@10 0.920000、MRR 0.607254、MTTC 4.360000、Technical Score 0.774976。
