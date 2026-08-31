# 步骤 12：冻结 dev 失败会话审核报告

## 1. 数据边界与结论

- 数据角色：`tuning`；样本数：150。
- Dataset SHA256：`c8955cacd79bb2e2ed6b984979bca91f379fc699648c5bc2e3ac2efb37f8b22a`。
- Catalog SHA256：`da979b05a68af864cb0dcf9ee6a81c010c7e66a57978ad286c7a2e005fc69a67`；catalog 仅被读取。
- 失败会话：13；Intent Override miss：4。
- 本报告只复盘既有结果，不修改权重，不读取 holdout/public/final，不生成或注入 ASIN。
- 合规复核：最多 10 轮；共审查 1300 个推荐位置；未知 ID、重复 ID、重放漂移均为 0。

| HR@10 | MRR | MTTC ↓ | Efficiency | TechnicalScore |
|---:|---:|---:|---:|---:|
| 0.913333 | 0.597302 | 4.406667 | 0.659333 | 0.767724 |

## 2. 场景分层

| 场景 | 样本 | 命中 | 失败 | 失败率 | 已复盘 | 说明 |
|---|---:|---:|---:|---:|---:|---|
| buying | 60 | 55 | 5 | 8.33% | 5 | 已覆盖全部可用失败 |
| browsing | 60 | 57 | 3 | 5.00% | 3 | 已覆盖全部可用失败 |
| intent_override | 22 | 18 | 4 | 18.18% | 4 | 已覆盖全部可用失败 |
| boundary | 8 | 7 | 1 | 12.50% | 1 | 已覆盖全部可用失败 |

> dev 150 中 Boundary 总样本仅 8 条；任何场景不足 20 个 miss 时复盘全部可用失败，绝不从 holdout/public 补数或伪造案例。

## 3. 根因分布

| 根因 | 数量 | 通用处理方向 |
|---|---:|---|
| `final_rank_over_10` | 11 | 目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。 |
| `not_recalled` | 2 | 优先改进通用查询表达、类目/元数据覆盖和 Dense 候选补充；禁止针对 sample_id 或目标 ASIN 写规则。 |

## 4. 跨案例审核结论

- 13 个 miss 中，BM25 召回 10 个、Metadata 召回 9 个、Dense 召回 3 个、融合后保留 11 个、最终列表可见 11 个。
- 最佳最终排名分布：缺失 2 个，11-20 名 2 个，21-50 名 8 个，51 名以后 1 个。
- 失败会话共提出 91 次问题，平均 7.00 次；重复提问会话 0 个。
- Over-General 截断涉及 0 个失败会话；Semantic Ranker 生效轮次 0，符合默认 LLM 关闭基线。
- 硬约束实际生效于 9 个失败会话，发生安全放宽的会话 1 个。
- 优先级：先解决 2 个全路由未召回，再处理 2 个最终第 11-20 名的通用重排近失；其余样本只用于验证跨案例规律，禁止单样本硬编码。

## 5. 全部失败摘要

| sample_id | scenario | 根因 | BM25 | Dense | 稀疏 RRF | 融合 | 最终 | 首次最终出现轮次 |
|---|---|---|---:|---:|---:|---:|---:|---:|
| public_0020 | buying | not_recalled | - | - | - | - | - | - |
| public_0094 | buying | not_recalled | - | - | - | - | - | - |
| public_0174 | buying | final_rank_over_10 | 80 | - | 73 | 73 | 19 | 1 |
| public_0028 | buying | final_rank_over_10 | 95 | - | 74 | 74 | 21 | 5 |
| public_0161 | buying | final_rank_over_10 | 28 | - | 23 | 23 | 23 | 4 |
| public_0151 | browsing | final_rank_over_10 | 20 | - | 17 | 17 | 12 | 1 |
| public_0016 | browsing | final_rank_over_10 | 80 | 102 | 49 | 49 | 23 | 1 |
| public_0087 | browsing | final_rank_over_10 | 54 | - | 46 | 46 | 44 | 5 |
| public_0080 | intent_override | final_rank_over_10 | 29 | - | 28 | 28 | 22 | 4 |
| public_0144 | intent_override | final_rank_over_10 | 98 | - | 95 | 95 | 25 | 4 |
| public_0198 | intent_override | final_rank_over_10 | 117 | - | 100 | 100 | 32 | 6 |
| public_0034 | intent_override | final_rank_over_10 | 87 | 112 | 116 | 116 | 43 | 4 |
| public_0187 | boundary | final_rank_over_10 | - | 25 | 144 | 144 | 100 | 1 |

## 6. 分场景逐轮复盘

### buying：5 个可用失败案例

#### public_0020 · `not_recalled`

- 目标：`B08P4SSFX4` · Funny Saying Novelty Gift ideas - My Favorite People Call Me Grandma Long Sleeve T-Shirt
- 类目：Clothing, Shoes & Jewelry > Novelty & More > Clothing > Novelty > Women
- 提问序列：size, brand, material, feature, color, style, budget；重复提问：无。
- 建议：优先改进通用查询表达、类目/元数据覆盖和 Dense 候选补充；禁止针对 sample_id 或目标 ASIN 写规则。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 是 | I'm looking for Novelty Women. A key requirement is: cotton. | Here are the strongest current matches. Do you have a required size or fit? | size | - | - | - | - | - | B01JOTZKE8, B07NQLKVW6, B089LN7GZ8, B00LIO1UM4, B018BHRNSK, B00VHU5RP0, B07B91CJQP, B0B46LNQXZ, B07F96YNJD, B01JND7T0S |
| 2 | 是 | I don't have an additional preference for size. | Here are the strongest current matches. Is there a brand you prefer? | brand | - | - | - | - | - | B01JOTZKE8, B07NQLKVW6, B089LN7GZ8, B00LIO1UM4, B018BHRNSK, B00VHU5RP0, B07B91CJQP, B0B46LNQXZ, B07F96YNJD, B01JND7T0S |
| 3 | 是 | I don't have an additional preference for brand. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | - | - | - | - | - | B01JOTZKE8, B07NQLKVW6, B089LN7GZ8, B00LIO1UM4, B018BHRNSK, B00VHU5RP0, B07B91CJQP, B0B46LNQXZ, B07F96YNJD, B01JND7T0S |
| 4 | 是 | For that, what matters is: Solid colors: 100% Cotton; Heather Grey: 90% Cotton, 10% Polyester; … | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | - | - | - | - | - | B01EW382K0, B0714KB949, B01HOQZ1YC, B06XNTNTSY, B071DSW9NL, B071RTD6WK, B071CVKC4M, B01BD4MHHK, B0741YG3MH, B01C1FM658 |
| 5 | 是 | For that, what matters is: Imported. | Here are the strongest current matches. Which color should I prioritize? | color | - | - | - | - | - | B01EW382K0, B0714KB949, B01HOQZ1YC, B071DSW9NL, B06XNTNTSY, B071RTD6WK, B071CVKC4M, B01BD4MHHK, B0741YG3MH, B01C1FM658 |
| 6 | 是 | For that, what matters is: color: grey. | Here are the strongest current matches. Do you prefer a casual, athletic, or formal style? | style | - | - | - | - | - | B072JJCFK8, B01EW382K0, B0714KB949, B01HOQZ1YC, B071DSW9NL, B06XNTNTSY, B071RTD6WK, B01BD4MHHK, B071CVKC4M, B0741YG3MH |
| 7 | 是 | I don't have an additional preference for style. | Here are the strongest current matches. What budget range should I stay within? | budget | - | - | - | - | - | B072JJCFK8, B01EW382K0, B0714KB949, B01HOQZ1YC, B071DSW9NL, B06XNTNTSY, B071RTD6WK, B01BD4MHHK, B071CVKC4M, B0741YG3MH |
| 8 | 是 | I don't have an additional preference for budget. | Here are the strongest current matches. | - | - | - | - | - | - | B072JJCFK8, B01EW382K0, B0714KB949, B01HOQZ1YC, B071DSW9NL, B06XNTNTSY, B071RTD6WK, B01BD4MHHK, B071CVKC4M, B0741YG3MH |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | - | - | - | - | - | B072JJCFK8, B01EW382K0, B0714KB949, B01HOQZ1YC, B071DSW9NL, B06XNTNTSY, B071RTD6WK, B01BD4MHHK, B071CVKC4M, B0741YG3MH |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | - | - | - | - | - | B072JJCFK8, B01EW382K0, B0714KB949, B01HOQZ1YC, B071DSW9NL, B06XNTNTSY, B071RTD6WK, B01BD4MHHK, B071CVKC4M, B0741YG3MH |

#### public_0094 · `not_recalled`

- 目标：`B01L99SW78` · Ariat Fatbaby Western Boot – Women’s Leather Western Boots
- 类目：Clothing, Shoes & Jewelry > Women > Shoes > Boots > Mid-Calf
- 提问序列：size, material, brand, feature, use_case, color, style；重复提问：无。
- 建议：优先改进通用查询表达、类目/元数据覆盖和 Dense 候选补充；禁止针对 sample_id 或目标 ASIN 写规则。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 是 | I'm looking for Boots Mid-Calf. A key requirement is: leather. | Here are the strongest current matches. Do you have a required size or fit? | size | - | - | - | - | - | B00Q9NPS18, B07MNF68KH, B08S6SXF31, B00BWBLXIE, B08FSTW789, B00NI6BALQ, B07XBMLV4H, B00OFOZ61U, B07KW31YGZ, B005IFCZ6O |
| 2 | 是 | I don't have an additional preference for size. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | - | - | - | - | - | B00Q9NPS18, B07MNF68KH, B08S6SXF31, B00BWBLXIE, B08FSTW789, B00NI6BALQ, B07XBMLV4H, B00OFOZ61U, B07KW31YGZ, B005IFCZ6O |
| 3 | 是 | I don't have an additional preference for material. | Here are the strongest current matches. Is there a brand you prefer? | brand | - | - | - | - | - | B00Q9NPS18, B07MNF68KH, B08S6SXF31, B00BWBLXIE, B08FSTW789, B00NI6BALQ, B07XBMLV4H, B00OFOZ61U, B07KW31YGZ, B005IFCZ6O |
| 4 | 是 | I don't have an additional preference for brand. | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | - | - | - | - | - | B00Q9NPS18, B07MNF68KH, B08S6SXF31, B00BWBLXIE, B08FSTW789, B00NI6BALQ, B07XBMLV4H, B00OFOZ61U, B07KW31YGZ, B005IFCZ6O |
| 5 | 是 | For that, what matters is: Synthetic sole; Shaft measures approximately 8" from arch. | Here are the strongest current matches. What activity or occasion will you use it for? | use_case | - | - | - | - | - | B00OFOZ61U, B01KORH54W, B00C847D3S, B0074O30F2, B07WZDN4PH, B002C74IEI, B098YWJWK5, B00BWBLXIE, B00NI6BALQ, B00R54V2IS |
| 6 | 是 | I don't have an additional preference for use_case. | Here are the strongest current matches. Which color should I prioritize? | color | - | - | - | - | - | B00OFOZ61U, B01KORH54W, B00C847D3S, B0074O30F2, B07WZDN4PH, B002C74IEI, B098YWJWK5, B00BWBLXIE, B00NI6BALQ, B00R54V2IS |
| 7 | 是 | I don't have an additional preference for color. | Here are the strongest current matches. Do you prefer a casual, athletic, or formal style? | style | - | - | - | - | - | B00OFOZ61U, B01KORH54W, B00C847D3S, B0074O30F2, B07WZDN4PH, B002C74IEI, B098YWJWK5, B00BWBLXIE, B00NI6BALQ, B00R54V2IS |
| 8 | 是 | I don't have an additional preference for style. | Here are the strongest current matches. | - | - | - | - | - | - | B00OFOZ61U, B01KORH54W, B00C847D3S, B0074O30F2, B07WZDN4PH, B002C74IEI, B098YWJWK5, B00BWBLXIE, B00NI6BALQ, B00R54V2IS |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | - | - | - | - | - | B00OFOZ61U, B01KORH54W, B00C847D3S, B0074O30F2, B07WZDN4PH, B002C74IEI, B098YWJWK5, B00BWBLXIE, B00NI6BALQ, B00R54V2IS |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | - | - | - | - | - | B00OFOZ61U, B01KORH54W, B00C847D3S, B0074O30F2, B07WZDN4PH, B002C74IEI, B098YWJWK5, B00BWBLXIE, B00NI6BALQ, B00R54V2IS |

#### public_0174 · `final_rank_over_10`

- 目标：`B0794VPVBH` · NY Threads Luxurious Mens Shawl Collar Fleece Bathrobe Spa Robe
- 类目：Clothing, Shoes & Jewelry > Men > Clothing > Sleep & Lounge > Robes
- 提问序列：size, material, brand, feature, use_case, color, style；重复提问：无。
- 建议：目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 是 | I'm looking for Sleep & Lounge Robes. A key requirement is: polyester. | Here are the strongest current matches. Do you have a required size or fit? | size | - | - | 123 | 123 | 78 | B08ND4R9MK, B0756C4C1R, B075697T3J, B07FF27D4Q, B01LDELSIO, B08FZZ68T2, B082N4XNWS, B085HRZVWP, B075VLHTV4, B08CRPJ3C5 |
| 2 | 是 | I don't have an additional preference for size. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | - | - | 123 | 123 | 78 | B08ND4R9MK, B0756C4C1R, B075697T3J, B07FF27D4Q, B01LDELSIO, B08FZZ68T2, B082N4XNWS, B085HRZVWP, B075VLHTV4, B08CRPJ3C5 |
| 3 | 是 | For that, what matters is: 100% Polyester. | Here are the strongest current matches. Is there a brand you prefer? | brand | - | - | 117 | 117 | 48 | B0756C4C1R, B075697T3J, B01LDELSIO, B00Z7BJJIQ, B082N4XNWS, B075VLHTV4, B01M29D3YO, B07111P7Q7, B07SF6X8N2, B00F4O2QC2 |
| 4 | 是 | I don't have an additional preference for brand. | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | - | - | 117 | 117 | 48 | B0756C4C1R, B075697T3J, B01LDELSIO, B00Z7BJJIQ, B082N4XNWS, B075VLHTV4, B01M29D3YO, B07111P7Q7, B07SF6X8N2, B00F4O2QC2 |
| 5 | 是 | For that, what matters is: Imported; Tie closure. | Here are the strongest current matches. What activity or occasion will you use it for? | use_case | 80 | - | 73 | 73 | 19 | B00F4O2QC2, B079JJXSSN, B079JGHJN3, B00O3BRNXY, B01HVLWJ7M, B0043RS6B6, B00KHYHRIC, B072C3WJT8, B00F3DOFSW, B0756C4C1R |
| 6 | 是 | I don't have an additional preference for use_case. | Here are the strongest current matches. Which color should I prioritize? | color | 80 | - | 73 | 73 | 19 | B00F4O2QC2, B079JJXSSN, B079JGHJN3, B00O3BRNXY, B01HVLWJ7M, B0043RS6B6, B00KHYHRIC, B072C3WJT8, B00F3DOFSW, B0756C4C1R |
| 7 | 是 | I don't have an additional preference for color. | Here are the strongest current matches. Do you prefer a casual, athletic, or formal style? | style | 80 | - | 73 | 73 | 19 | B00F4O2QC2, B079JJXSSN, B079JGHJN3, B00O3BRNXY, B01HVLWJ7M, B0043RS6B6, B00KHYHRIC, B072C3WJT8, B00F3DOFSW, B0756C4C1R |
| 8 | 是 | I don't have an additional preference for style. | Here are the strongest current matches. | - | 80 | - | 73 | 73 | 19 | B00F4O2QC2, B079JJXSSN, B079JGHJN3, B00O3BRNXY, B01HVLWJ7M, B0043RS6B6, B00KHYHRIC, B072C3WJT8, B00F3DOFSW, B0756C4C1R |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 80 | - | 73 | 73 | 19 | B00F4O2QC2, B079JJXSSN, B079JGHJN3, B00O3BRNXY, B01HVLWJ7M, B0043RS6B6, B00KHYHRIC, B072C3WJT8, B00F3DOFSW, B0756C4C1R |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 80 | - | 73 | 73 | 19 | B00F4O2QC2, B079JJXSSN, B079JGHJN3, B00O3BRNXY, B01HVLWJ7M, B0043RS6B6, B00KHYHRIC, B072C3WJT8, B00F3DOFSW, B0756C4C1R |

#### public_0028 · `final_rank_over_10`

- 目标：`B0B9ZYDDZ1` · Buffway Slim Minimalist Front Pocket RFID Blocking Leather Wallets for Men Women
- 类目：Clothing, Shoes & Jewelry > Men > Accessories > Wallets, Card Cases & Money Organizers > Wallets
- 提问序列：size, brand, color, material, style, budget, feature；重复提问：无。
- 建议：目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 是 | I'm looking for Card Cases & Money Organizers Wallets. A key requirement is: leather. | Here are the strongest current matches. Do you have a required size or fit? | size | - | - | - | - | - | B0768CLQ4W, B00AT8IWWQ, B07VJHL9XN, B077F53FTQ, B07TX5CJ7Y, B081QZ36XJ, B084ZGW146, B08XHRZF7W, B07HQCD43X, B0C6KNC7ST |
| 2 | 是 | I don't have an additional preference for size. | Here are the strongest current matches. Is there a brand you prefer? | brand | - | - | - | - | - | B0768CLQ4W, B00AT8IWWQ, B07VJHL9XN, B077F53FTQ, B07TX5CJ7Y, B081QZ36XJ, B084ZGW146, B08XHRZF7W, B07HQCD43X, B0C6KNC7ST |
| 3 | 是 | I don't have an additional preference for brand. | Here are the strongest current matches. Which color should I prioritize? | color | - | - | - | - | - | B0768CLQ4W, B00AT8IWWQ, B07VJHL9XN, B077F53FTQ, B07TX5CJ7Y, B081QZ36XJ, B084ZGW146, B08XHRZF7W, B07HQCD43X, B0C6KNC7ST |
| 4 | 是 | For that, what matters is: color: black. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | - | - | - | - | - | B01N2TB8EL, B08NWBJ1XR, B008UZO4KO, B09ZJZWXVF, B00793M0Z4, B07GXB6MPF, B09ZPLJ2LF, B010D5SEPE, B08172T8MD, B016QUDKCW |
| 5 | 是 | For that, what matters is: Leather; Polyester lining. | Here are the strongest current matches. Do you prefer a casual, athletic, or formal style? | style | 95 | - | 74 | 74 | 21 | B08172T8MD, B07SQFLSGJ, B008UZO4KO, B00793M0Z4, B07GQNSRMD, B002JIO3RC, B0CHVZSPZG, B01N0F3GH6, B0099NSYPM, B018J3KQLW |
| 6 | 是 | I don't have an additional preference for style. | Here are the strongest current matches. What budget range should I stay within? | budget | 95 | - | 74 | 74 | 21 | B08172T8MD, B07SQFLSGJ, B008UZO4KO, B00793M0Z4, B07GQNSRMD, B002JIO3RC, B0CHVZSPZG, B01N0F3GH6, B0099NSYPM, B018J3KQLW |
| 7 | 是 | I don't have an additional preference for budget. | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | 95 | - | 74 | 74 | 21 | B08172T8MD, B07SQFLSGJ, B008UZO4KO, B00793M0Z4, B07GQNSRMD, B002JIO3RC, B0CHVZSPZG, B01N0F3GH6, B0099NSYPM, B018J3KQLW |
| 8 | 是 | I don't have an additional preference for feature. | Here are the strongest current matches. | - | 95 | - | 74 | 74 | 21 | B08172T8MD, B07SQFLSGJ, B008UZO4KO, B00793M0Z4, B07GQNSRMD, B002JIO3RC, B0CHVZSPZG, B01N0F3GH6, B0099NSYPM, B018J3KQLW |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 95 | - | 74 | 74 | 21 | B08172T8MD, B07SQFLSGJ, B008UZO4KO, B00793M0Z4, B07GQNSRMD, B002JIO3RC, B0CHVZSPZG, B01N0F3GH6, B0099NSYPM, B018J3KQLW |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 95 | - | 74 | 74 | 21 | B08172T8MD, B07SQFLSGJ, B008UZO4KO, B00793M0Z4, B07GQNSRMD, B002JIO3RC, B0CHVZSPZG, B01N0F3GH6, B0099NSYPM, B018J3KQLW |

#### public_0161 · `final_rank_over_10`

- 目标：`B0B6N6TJ6V` · Thankful Grateful Blessed Shirt for Women Plaid Pumpkin Long Sleeve Tshirts Leopard Stripe Striped Thanksgiving Fall Tee Tops
- 类目：Clothing, Shoes & Jewelry > Women > Clothing > Tops, Tees & Blouses > T-Shirts
- 提问序列：size, brand, material, use_case, feature, color, style；重复提问：无。
- 建议：目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 是 | I'm looking for Tees & Blouses T-Shirts. A key requirement is: cotton. | Here are the strongest current matches. Do you have a required size or fit? | size | - | - | - | - | - | B07GF3YT1X, B07GZMHQ4G, B085XXTT2J, B07KNRH5QB, B08C4PN3LQ, B08C98F1CQ, B0BJV8HNBM, B07JZ6HTP1, B07GCKFRN6, B08XYPFBWF |
| 2 | 是 | I don't have an additional preference for size. | Here are the strongest current matches. Is there a brand you prefer? | brand | - | - | - | - | - | B07GF3YT1X, B07GZMHQ4G, B085XXTT2J, B07KNRH5QB, B08C4PN3LQ, B08C98F1CQ, B0BJV8HNBM, B07JZ6HTP1, B07GCKFRN6, B08XYPFBWF |
| 3 | 是 | I don't have an additional preference for brand. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | - | - | - | - | - | B07GF3YT1X, B07GZMHQ4G, B085XXTT2J, B07KNRH5QB, B08C4PN3LQ, B08C98F1CQ, B0BJV8HNBM, B07JZ6HTP1, B07GCKFRN6, B08XYPFBWF |
| 4 | 是 | For that, what matters is: cotton blend. | Here are the strongest current matches. What activity or occasion will you use it for? | use_case | 57 | - | 46 | 46 | 77 | B0792QTYTF, B08RWPDL46, B0C1YPPMQ1, B07Q2QJ3GL, B07G47C934, B08C4PN3LQ, B08T7G47R7, B07M6W5JWT, B07C6RYRRJ, B07RBP6CRX |
| 5 | 是 | I don't have an additional preference for use_case. | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | 57 | - | 46 | 46 | 77 | B0792QTYTF, B08RWPDL46, B0C1YPPMQ1, B07Q2QJ3GL, B07G47C934, B08C4PN3LQ, B08T7G47R7, B07M6W5JWT, B07C6RYRRJ, B07RBP6CRX |
| 6 | 是 | For that, what matters is: Imported; Pull On closure. | Here are the strongest current matches. Which color should I prioritize? | color | 28 | - | 23 | 23 | 23 | B0C1YPPMQ1, B08J9TRGJV, B0BW2Y7JNS, B0BDMJ4TDN, B0792QTYTF, B07M6W5JWT, B08T7G47R7, B08C4PN3LQ, B07C6RYRRJ, B09XVCFXY8 |
| 7 | 是 | I don't have an additional preference for color. | Here are the strongest current matches. Do you prefer a casual, athletic, or formal style? | style | 28 | - | 23 | 23 | 23 | B0C1YPPMQ1, B08J9TRGJV, B0BW2Y7JNS, B0BDMJ4TDN, B0792QTYTF, B07M6W5JWT, B08T7G47R7, B08C4PN3LQ, B07C6RYRRJ, B09XVCFXY8 |
| 8 | 是 | I don't have an additional preference for style. | Here are the strongest current matches. | - | 28 | - | 23 | 23 | 23 | B0C1YPPMQ1, B08J9TRGJV, B0BW2Y7JNS, B0BDMJ4TDN, B0792QTYTF, B07M6W5JWT, B08T7G47R7, B08C4PN3LQ, B07C6RYRRJ, B09XVCFXY8 |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 28 | - | 23 | 23 | 23 | B0C1YPPMQ1, B08J9TRGJV, B0BW2Y7JNS, B0BDMJ4TDN, B0792QTYTF, B07M6W5JWT, B08T7G47R7, B08C4PN3LQ, B07C6RYRRJ, B09XVCFXY8 |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 28 | - | 23 | 23 | 23 | B0C1YPPMQ1, B08J9TRGJV, B0BW2Y7JNS, B0BDMJ4TDN, B0792QTYTF, B07M6W5JWT, B08T7G47R7, B08C4PN3LQ, B07C6RYRRJ, B09XVCFXY8 |

### browsing：3 个可用失败案例

#### public_0151 · `final_rank_over_10`

- 目标：`B08CFNQNJK` · Under Armour Men's Micro G Valsetz Mid Military and Tactical Boot
- 类目：Clothing, Shoes & Jewelry > Boot Shop > Men > Outdoor & Work > Work & Safety
- 提问序列：feature, size, material, brand, use_case, budget, color；重复提问：无。
- 建议：目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 是 | I'm looking for Outdoor & Work Work & Safety, but I'm still exploring. | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | 75 | - | 67 | 67 | 114 | B07C58PZZP, B07TSMB66F, B08CZR9J3K, B07SCQDKKP, B08HCP1KBY, B07TSJBWZX, B0925VYP8N, B07YY582SF, B09699PSB5, B01MAV53ST |
| 2 | 是 | For that, what matters is: Imported; Rubber sole. | Here are the strongest current matches. Do you have a required size or fit? | size | 31 | - | 25 | 25 | 19 | B0925VYP8N, B009DLKT7Q, B000MRV3JI, B09NVZ1S54, B007KJ62NI, B01J8WZC2Q, B00BFA928A, B00G8P3RLK, B00IJWXT54, B00DJB60QA |
| 3 | 是 | I don't have an additional preference for size. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | 31 | - | 25 | 25 | 19 | B0925VYP8N, B009DLKT7Q, B000MRV3JI, B09NVZ1S54, B007KJ62NI, B01J8WZC2Q, B00BFA928A, B00G8P3RLK, B00IJWXT54, B00DJB60QA |
| 4 | 是 | For that, what matters is: leather. | Here are the strongest current matches. Is there a brand you prefer? | brand | 20 | - | 17 | 17 | 12 | B000MRV3JI, B009DLKT7Q, B007KJ62NI, B00BFA928A, B00G8P3RLK, B00DJB60QA, B00EA90PNO, B071YSX2RJ, B00IJWXT54, B00UPHJC3E |
| 5 | 是 | I don't have an additional preference for brand. | Here are the strongest current matches. What activity or occasion will you use it for? | use_case | 20 | - | 17 | 17 | 12 | B000MRV3JI, B009DLKT7Q, B007KJ62NI, B00BFA928A, B00G8P3RLK, B00DJB60QA, B00EA90PNO, B071YSX2RJ, B00IJWXT54, B00UPHJC3E |
| 6 | 是 | I don't have an additional preference for use_case. | Here are the strongest current matches. What budget range should I stay within? | budget | 20 | - | 17 | 17 | 12 | B000MRV3JI, B009DLKT7Q, B007KJ62NI, B00BFA928A, B00G8P3RLK, B00DJB60QA, B00EA90PNO, B071YSX2RJ, B00IJWXT54, B00UPHJC3E |
| 7 | 是 | I don't have an additional preference for budget. | Here are the strongest current matches. Which color should I prioritize? | color | 20 | - | 17 | 17 | 12 | B000MRV3JI, B009DLKT7Q, B007KJ62NI, B00BFA928A, B00G8P3RLK, B00DJB60QA, B00EA90PNO, B071YSX2RJ, B00IJWXT54, B00UPHJC3E |
| 8 | 是 | I don't have an additional preference for color. | Here are the strongest current matches. | - | 20 | - | 17 | 17 | 12 | B000MRV3JI, B009DLKT7Q, B007KJ62NI, B00BFA928A, B00G8P3RLK, B00DJB60QA, B00EA90PNO, B071YSX2RJ, B00IJWXT54, B00UPHJC3E |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 20 | - | 17 | 17 | 12 | B000MRV3JI, B009DLKT7Q, B007KJ62NI, B00BFA928A, B00G8P3RLK, B00DJB60QA, B00EA90PNO, B071YSX2RJ, B00IJWXT54, B00UPHJC3E |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 20 | - | 17 | 17 | 12 | B000MRV3JI, B009DLKT7Q, B007KJ62NI, B00BFA928A, B00G8P3RLK, B00DJB60QA, B00EA90PNO, B071YSX2RJ, B00IJWXT54, B00UPHJC3E |

#### public_0016 · `final_rank_over_10`

- 目标：`B07PH3X7QK` · Amazon Essentials Women's Lace-Up Combat Boot
- 类目：Clothing, Shoes & Jewelry > Women > Shoes > Boots > Mid-Calf
- 提问序列：size, brand, material, feature, use_case, color, style；重复提问：无。
- 建议：目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 是 | I'm looking for Boots Mid-Calf, but I'm still exploring. | Here are the strongest current matches. Do you have a required size or fit? | size | - | - | 166 | 166 | 167 | B00416VC9M, B091MDRQGG, B07MNF68KH, B07FZ49LDL, B00Q9NPS18, B00CZOHFVQ, B0098BNL58, B00OLG411S, B08S6SXF31, B00BWBLXIE |
| 2 | 是 | I don't have an additional preference for size. | Here are the strongest current matches. Is there a brand you prefer? | brand | - | - | 166 | 166 | 167 | B00416VC9M, B091MDRQGG, B07MNF68KH, B07FZ49LDL, B00Q9NPS18, B00CZOHFVQ, B0098BNL58, B00OLG411S, B08S6SXF31, B00BWBLXIE |
| 3 | 是 | I don't have an additional preference for brand. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | - | - | 166 | 166 | 167 | B00416VC9M, B091MDRQGG, B07MNF68KH, B07FZ49LDL, B00Q9NPS18, B00CZOHFVQ, B0098BNL58, B00OLG411S, B08S6SXF31, B00BWBLXIE |
| 4 | 是 | For that, what matters is: leather. | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | - | - | 88 | 88 | 90 | B00Q9NPS18, B07MNF68KH, B00BWBLXIE, B08S6SXF31, B08FSTW789, B00NI6BALQ, B00OFOZ61U, B07XBMLV4H, B005IFCZ6O, B07KW31YGZ |
| 5 | 是 | For that, what matters is: Imported; Rubber sole. | Here are the strongest current matches. What activity or occasion will you use it for? | use_case | 80 | 102 | 49 | 49 | 23 | B08M68Q4J5, B00R54V2IS, B00Q9NPS18, B00BWBLXIE, B00AY48OP0, B01DIOPTWS, B01H7CUSOG, B008WMIF6E, B08FSTW789, B00CCYB8XK |
| 6 | 是 | I don't have an additional preference for use_case. | Here are the strongest current matches. Which color should I prioritize? | color | 80 | 102 | 49 | 49 | 23 | B08M68Q4J5, B00R54V2IS, B00Q9NPS18, B00BWBLXIE, B00AY48OP0, B01DIOPTWS, B01H7CUSOG, B008WMIF6E, B08FSTW789, B00CCYB8XK |
| 7 | 是 | I don't have an additional preference for color. | Here are the strongest current matches. Do you prefer a casual, athletic, or formal style? | style | 80 | 102 | 49 | 49 | 23 | B08M68Q4J5, B00R54V2IS, B00Q9NPS18, B00BWBLXIE, B00AY48OP0, B01DIOPTWS, B01H7CUSOG, B008WMIF6E, B08FSTW789, B00CCYB8XK |
| 8 | 是 | I don't have an additional preference for style. | Here are the strongest current matches. | - | 80 | 102 | 49 | 49 | 23 | B08M68Q4J5, B00R54V2IS, B00Q9NPS18, B00BWBLXIE, B00AY48OP0, B01DIOPTWS, B01H7CUSOG, B008WMIF6E, B08FSTW789, B00CCYB8XK |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 80 | 102 | 49 | 49 | 23 | B08M68Q4J5, B00R54V2IS, B00Q9NPS18, B00BWBLXIE, B00AY48OP0, B01DIOPTWS, B01H7CUSOG, B008WMIF6E, B08FSTW789, B00CCYB8XK |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 80 | 102 | 49 | 49 | 23 | B08M68Q4J5, B00R54V2IS, B00Q9NPS18, B00BWBLXIE, B00AY48OP0, B01DIOPTWS, B01H7CUSOG, B008WMIF6E, B08FSTW789, B00CCYB8XK |

#### public_0087 · `final_rank_over_10`

- 目标：`B0BT158RRR` · Goodthreads Men's Standard-Fit Short-Sleeve Printed Poplin Shirt
- 类目：Clothing, Shoes & Jewelry > Men > Clothing > Shirts > Casual Button-Down Shirts
- 提问序列：size, use_case, brand, material, style, feature, color；重复提问：无。
- 建议：目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 是 | I'm looking for Shirts Casual Button-Down Shirts, but I'm still exploring. | Here are the strongest current matches. Do you have a required size or fit? | size | - | - | - | - | - | B01F52IEIW, B07GGP7948, B0B4WXRJTB, B07XXS4WDT, B07DYHH772, B07XHPVVCW, B08HV94JDJ, B08Z3YL2M4, B08HCRGMBC, B097YB478K |
| 2 | 是 | I don't have an additional preference for size. | Here are the strongest current matches. What activity or occasion will you use it for? | use_case | - | - | - | - | - | B01F52IEIW, B07GGP7948, B0B4WXRJTB, B07XXS4WDT, B07DYHH772, B07XHPVVCW, B08HV94JDJ, B08Z3YL2M4, B08HCRGMBC, B097YB478K |
| 3 | 是 | I don't have an additional preference for use_case. | Here are the strongest current matches. Is there a brand you prefer? | brand | - | - | - | - | - | B01F52IEIW, B07GGP7948, B0B4WXRJTB, B07XXS4WDT, B07DYHH772, B07XHPVVCW, B08HV94JDJ, B08Z3YL2M4, B08HCRGMBC, B097YB478K |
| 4 | 是 | I don't have an additional preference for brand. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | - | - | - | - | - | B01F52IEIW, B07GGP7948, B0B4WXRJTB, B07XXS4WDT, B07DYHH772, B07XHPVVCW, B08HV94JDJ, B08Z3YL2M4, B08HCRGMBC, B097YB478K |
| 5 | 是 | For that, what matters is: cotton; 100% Cotton. | Here are the strongest current matches. Do you prefer a casual, athletic, or formal style? | style | 93 | - | 70 | 70 | 80 | B07XHPVVCW, B07XXS4WDT, B09P39YM3Z, B07PMV29LB, B075F6PX8W, B0781FBSJK, B075F615WT, B00HUH76KS, B097K8YT3K, B0057XA406 |
| 6 | 是 | I don't have an additional preference for style. | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | 93 | - | 70 | 70 | 80 | B07XHPVVCW, B07XXS4WDT, B09P39YM3Z, B07PMV29LB, B075F6PX8W, B0781FBSJK, B075F615WT, B00HUH76KS, B097K8YT3K, B0057XA406 |
| 7 | 是 | For that, what matters is: Imported; Button closure. | Here are the strongest current matches. Which color should I prioritize? | color | 54 | - | 46 | 46 | 44 | B09QB2NP99, B009FWGUO4, B083ZPTRRF, B00MLPDFL8, B07KQ36LVT, B00S1GQMV6, B07Q4CN3R7, B07KQ4PF54, B085T9Q34Z, B07GXP4TR2 |
| 8 | 是 | I don't have an additional preference for color. | Here are the strongest current matches. | - | 54 | - | 46 | 46 | 44 | B09QB2NP99, B009FWGUO4, B083ZPTRRF, B00MLPDFL8, B07KQ36LVT, B00S1GQMV6, B07Q4CN3R7, B07KQ4PF54, B085T9Q34Z, B07GXP4TR2 |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 54 | - | 46 | 46 | 44 | B09QB2NP99, B009FWGUO4, B083ZPTRRF, B00MLPDFL8, B07KQ36LVT, B00S1GQMV6, B07Q4CN3R7, B07KQ4PF54, B085T9Q34Z, B07GXP4TR2 |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 54 | - | 46 | 46 | 44 | B09QB2NP99, B009FWGUO4, B083ZPTRRF, B00MLPDFL8, B07KQ36LVT, B00S1GQMV6, B07Q4CN3R7, B07KQ4PF54, B085T9Q34Z, B07GXP4TR2 |

### intent_override：4 个可用失败案例

#### public_0080 · `final_rank_over_10`

- 目标：`B0BPRQY4CF` · IZOD Men's Advantage Performance Short Sleeve Polo Shirt
- 类目：Clothing, Shoes & Jewelry > Men > Clothing > Shirts > Polos
- 提问序列：size, brand, material, feature, style, color, use_case；重复提问：无。
- 建议：目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 否 | I'm looking for Shirts Polos. Button closure | Here are the strongest current matches. Do you have a required size or fit? | size | 99 | - | 107 | 107 | 96 | B07MZ942LH, B07TTZSSRZ, B079HQ9TPF, B07TGBKJRW, B08GS74QC3, B09NR6KTX5, B08JG9KPQZ, B01JOU6KMS, B08GX981MW, B07QL3CB7P |
| 2 | 否 | I don't have an additional preference for size. | Here are the strongest current matches. Is there a brand you prefer? | brand | 99 | - | 107 | 107 | 96 | B07MZ942LH, B07TTZSSRZ, B079HQ9TPF, B07TGBKJRW, B08GS74QC3, B09NR6KTX5, B08JG9KPQZ, B01JOU6KMS, B08GX981MW, B07QL3CB7P |
| 3 | 否 | I don't have an additional preference for brand. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | 99 | - | 107 | 107 | 96 | B07MZ942LH, B07TTZSSRZ, B079HQ9TPF, B07TGBKJRW, B08GS74QC3, B09NR6KTX5, B08JG9KPQZ, B01JOU6KMS, B08GX981MW, B07QL3CB7P |
| 4 | 是 | Actually, ignore my earlier preference. What I need is: cotton. | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | 52 | - | 50 | 50 | 61 | B07MZ942LH, B07TTZSSRZ, B08JG9KPQZ, B08YY4DMS4, B08GS74QC3, B00T6RYA04, B00K6K891G, B07WC4RTZ2, B008VOMUL4, B09FJ3NHQ9 |
| 5 | 是 | For that, what matters is: Imported; Button closure. | Here are the strongest current matches. Do you prefer a casual, athletic, or formal style? | style | 29 | - | 28 | 28 | 22 | B00Y7UQBBQ, B00YQ54F10, B00KTXKSRI, B00596501O, B07NKBP6V4, B01N19VS3S, B079M3M2V4, B07HJDBN4L, B08JG9KPQZ, B01LBHX87M |
| 6 | 是 | I don't have an additional preference for style. | Here are the strongest current matches. Which color should I prioritize? | color | 29 | - | 28 | 28 | 22 | B00Y7UQBBQ, B00YQ54F10, B00KTXKSRI, B00596501O, B07NKBP6V4, B01N19VS3S, B079M3M2V4, B07HJDBN4L, B08JG9KPQZ, B01LBHX87M |
| 7 | 是 | I don't have an additional preference for color. | Here are the strongest current matches. What activity or occasion will you use it for? | use_case | 29 | - | 28 | 28 | 22 | B00Y7UQBBQ, B00YQ54F10, B00KTXKSRI, B00596501O, B07NKBP6V4, B01N19VS3S, B079M3M2V4, B07HJDBN4L, B08JG9KPQZ, B01LBHX87M |
| 8 | 是 | I don't have an additional preference for use_case. | Here are the strongest current matches. | - | 29 | - | 28 | 28 | 22 | B00Y7UQBBQ, B00YQ54F10, B00KTXKSRI, B00596501O, B07NKBP6V4, B01N19VS3S, B079M3M2V4, B07HJDBN4L, B08JG9KPQZ, B01LBHX87M |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 29 | - | 28 | 28 | 22 | B00Y7UQBBQ, B00YQ54F10, B00KTXKSRI, B00596501O, B07NKBP6V4, B01N19VS3S, B079M3M2V4, B07HJDBN4L, B08JG9KPQZ, B01LBHX87M |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 29 | - | 28 | 28 | 22 | B00Y7UQBBQ, B00YQ54F10, B00KTXKSRI, B00596501O, B07NKBP6V4, B01N19VS3S, B079M3M2V4, B07HJDBN4L, B08JG9KPQZ, B01LBHX87M |

#### public_0144 · `final_rank_over_10`

- 目标：`B08LMMDYV7` · URBAN REPUBLIC Women's Winter Jacket - Heavyweight Water Resistant Expedition Faux-Fur Lined Parka Jacket
- 类目：Clothing, Shoes & Jewelry > Women > Clothing > Coats, Jackets & Vests > Down Jackets & Parkas
- 提问序列：size, brand, material, feature, use_case, style, color；重复提问：无。
- 建议：目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 否 | I'm looking for Jackets & Vests Down Jackets & Parkas. Zipper closure | Here are the strongest current matches. Do you have a required size or fit? | size | 101 | - | 100 | 100 | 78 | B0123YHODG, B08D9MX2YY, B01LYCJSER, B074N3DPYZ, B07D8W778T, B075KFSRZJ, B075JGL3JG, B07Y8VL8QH, B09HXN7ZJ5, B07P5GYCWN |
| 2 | 否 | I don't have an additional preference for size. | Here are the strongest current matches. Is there a brand you prefer? | brand | 101 | - | 100 | 100 | 78 | B0123YHODG, B08D9MX2YY, B01LYCJSER, B074N3DPYZ, B07D8W778T, B075KFSRZJ, B075JGL3JG, B07Y8VL8QH, B09HXN7ZJ5, B07P5GYCWN |
| 3 | 否 | I don't have an additional preference for brand. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | 101 | - | 100 | 100 | 78 | B0123YHODG, B08D9MX2YY, B01LYCJSER, B074N3DPYZ, B07D8W778T, B075KFSRZJ, B075JGL3JG, B07Y8VL8QH, B09HXN7ZJ5, B07P5GYCWN |
| 4 | 是 | Actually, ignore my earlier preference. What I need is: polyester. | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | 101 | - | 101 | 101 | 41 | B07CZGMNML, B072LW2R4F, B00YXOCC9Q, B00LEOX31O, B08TTDX89T, B076TTCM7S, B09L5L9463, B00KU0YXQC, B00DDFK0DQ, B00XK86P76 |
| 5 | 是 | For that, what matters is: Imported; Zipper closure. | Here are the strongest current matches. What activity or occasion will you use it for? | use_case | 98 | - | 95 | 95 | 25 | B07CZGMNML, B076TTCM7S, B00LEOX31O, B07BR2J71F, B088Y6BN67, B09L5L9463, B07RS44M91, B09D112TGF, B01GHS9PUE, B08SS3Y79W |
| 6 | 是 | I don't have an additional preference for use_case. | Here are the strongest current matches. Do you prefer a casual, athletic, or formal style? | style | 98 | - | 95 | 95 | 25 | B07CZGMNML, B076TTCM7S, B00LEOX31O, B07BR2J71F, B088Y6BN67, B09L5L9463, B07RS44M91, B09D112TGF, B01GHS9PUE, B08SS3Y79W |
| 7 | 是 | I don't have an additional preference for style. | Here are the strongest current matches. Which color should I prioritize? | color | 98 | - | 95 | 95 | 25 | B07CZGMNML, B076TTCM7S, B00LEOX31O, B07BR2J71F, B088Y6BN67, B09L5L9463, B07RS44M91, B09D112TGF, B01GHS9PUE, B08SS3Y79W |
| 8 | 是 | I don't have an additional preference for color. | Here are the strongest current matches. | - | 98 | - | 95 | 95 | 25 | B07CZGMNML, B076TTCM7S, B00LEOX31O, B07BR2J71F, B088Y6BN67, B09L5L9463, B07RS44M91, B09D112TGF, B01GHS9PUE, B08SS3Y79W |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 98 | - | 95 | 95 | 25 | B07CZGMNML, B076TTCM7S, B00LEOX31O, B07BR2J71F, B088Y6BN67, B09L5L9463, B07RS44M91, B09D112TGF, B01GHS9PUE, B08SS3Y79W |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 98 | - | 95 | 95 | 25 | B07CZGMNML, B076TTCM7S, B00LEOX31O, B07BR2J71F, B088Y6BN67, B09L5L9463, B07RS44M91, B09D112TGF, B01GHS9PUE, B08SS3Y79W |

#### public_0198 · `final_rank_over_10`

- 目标：`B08K1ZJZ4N` · lola mae Quilted Crossbody Bag, Medium Lightweight Shoulder Purse Top Zipper Tassel Accent
- 类目：Clothing, Shoes & Jewelry > Women > Handbags & Wallets > Crossbody Bags
- 提问序列：size, brand, color, material, feature, use_case, style；重复提问：无。
- 建议：目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 否 | I'm looking for Handbags & Wallets Crossbody Bags. Imported | Here are the strongest current matches. Do you have a required size or fit? | size | - | - | - | - | - | B07G6WBSX9, B07S8NW7PV, B07LD9FJML, B07VJKRPGH, B01F4SHBMC, B08L8PV9ZW, B07BQKHMVM, B071XZ82D9, B092S3YGJZ, B08VN4NHC1 |
| 2 | 否 | I don't have an additional preference for size. | Here are the strongest current matches. Is there a brand you prefer? | brand | - | - | - | - | - | B07G6WBSX9, B07S8NW7PV, B07LD9FJML, B07VJKRPGH, B01F4SHBMC, B08L8PV9ZW, B07BQKHMVM, B071XZ82D9, B092S3YGJZ, B08VN4NHC1 |
| 3 | 否 | I don't have an additional preference for brand. | Here are the strongest current matches. Which color should I prioritize? | color | - | - | - | - | - | B07G6WBSX9, B07S8NW7PV, B07LD9FJML, B07VJKRPGH, B01F4SHBMC, B08L8PV9ZW, B07BQKHMVM, B071XZ82D9, B092S3YGJZ, B08VN4NHC1 |
| 4 | 是 | Actually, ignore my earlier preference. What I need is: leather. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | - | - | - | - | - | B07S8NW7PV, B07G6WBSX9, B08VN4NHC1, B08L8PV9ZW, B01LZIGLSU, B092S3YGJZ, B087QMPXPV, B082DN5WRT, B01IFU2L26, B07L3Y8B8S |
| 5 | 是 | I don't have an additional preference for material. | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | - | - | - | - | - | B07S8NW7PV, B07G6WBSX9, B08VN4NHC1, B08L8PV9ZW, B01LZIGLSU, B092S3YGJZ, B087QMPXPV, B082DN5WRT, B01IFU2L26, B07L3Y8B8S |
| 6 | 是 | For that, what matters is: PU; Imported. | Here are the strongest current matches. What activity or occasion will you use it for? | use_case | 117 | - | 100 | 100 | 32 | B08SBJ4HD6, B088M19KJ3, B07Q8VPHJJ, B0BNL5B54Z, B0BZRCYNCG, B07T6G3W5Y, B09JWBKRLX, B08TBGR4X2, B07G743XMW, B08L8PV9ZW |
| 7 | 是 | I don't have an additional preference for use_case. | Here are the strongest current matches. Do you prefer a casual, athletic, or formal style? | style | 117 | - | 100 | 100 | 32 | B08SBJ4HD6, B088M19KJ3, B07Q8VPHJJ, B0BNL5B54Z, B0BZRCYNCG, B07T6G3W5Y, B09JWBKRLX, B08TBGR4X2, B07G743XMW, B08L8PV9ZW |
| 8 | 是 | I don't have an additional preference for style. | Here are the strongest current matches. | - | 117 | - | 100 | 100 | 32 | B08SBJ4HD6, B088M19KJ3, B07Q8VPHJJ, B0BNL5B54Z, B0BZRCYNCG, B07T6G3W5Y, B09JWBKRLX, B08TBGR4X2, B07G743XMW, B08L8PV9ZW |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 117 | - | 100 | 100 | 32 | B08SBJ4HD6, B088M19KJ3, B07Q8VPHJJ, B0BNL5B54Z, B0BZRCYNCG, B07T6G3W5Y, B09JWBKRLX, B08TBGR4X2, B07G743XMW, B08L8PV9ZW |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 117 | - | 100 | 100 | 32 | B08SBJ4HD6, B088M19KJ3, B07Q8VPHJJ, B0BNL5B54Z, B0BZRCYNCG, B07T6G3W5Y, B09JWBKRLX, B08TBGR4X2, B07G743XMW, B08L8PV9ZW |

#### public_0034 · `final_rank_over_10`

- 目标：`B07Q9PNNB5` · DUOYANGJIASHA Loafers for Women Casual Slip on Dress Loafers Womens Comfortable Leather Driving Shoes Outdoor Walking Flats Shoes
- 类目：Clothing, Shoes & Jewelry > Women > Shoes > Loafers & Slip-Ons
- 提问序列：feature, size, material, brand, color, use_case, style；重复提问：无。
- 建议：目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 否 | I'm looking for Shoes Loafers & Slip-Ons. Leather Loafers Women:can be bend and curled in 360°,… | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | 1 | 1 | 1 | 1 | 1 | B07Q9PNNB5, B07QQNZ3L1, B08G4WVYLJ, B083VZXVRM, B09BN8WM1T, B09LTSZJTM, B083SFV5HQ, B083TRSXV1, B07CWL6FFR, B096XLCK7S |
| 2 | 否 | For that, what matters is: Rubber sole. | Here are the strongest current matches. Do you have a required size or fit? | size | 1 | 1 | 1 | 1 | 1 | B07Q9PNNB5, B07QQNZ3L1, B08G4WVYLJ, B09BN8WM1T, B083SFV5HQ, B083TRSXV1, B07CWL6FFR, B0756DDVMX, B07WP4KG63, B0924JF9ST |
| 3 | 否 | I don't have an additional preference for size. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | 1 | 1 | 1 | 1 | 1 | B07Q9PNNB5, B07QQNZ3L1, B08G4WVYLJ, B09BN8WM1T, B083SFV5HQ, B083TRSXV1, B07CWL6FFR, B0756DDVMX, B07WP4KG63, B0924JF9ST |
| 4 | 是 | Actually, ignore my earlier preference. What I need is: leather. | Here are the strongest current matches. Is there a brand you prefer? | brand | 87 | 112 | 116 | 116 | 43 | B01I3NKV90, B07D3SK95J, B07DHM2PJ5, B07ML2GYT7, B07BDKQQ19, B081TJRYVG, B07Q2Z4SVS, B01NBPCYI3, B08ZXPZT5V, B01MR0QH2V |
| 5 | 是 | I don't have an additional preference for brand. | Here are the strongest current matches. Which color should I prioritize? | color | 87 | 112 | 116 | 116 | 43 | B01I3NKV90, B07D3SK95J, B07DHM2PJ5, B07ML2GYT7, B07BDKQQ19, B081TJRYVG, B07Q2Z4SVS, B01NBPCYI3, B08ZXPZT5V, B01MR0QH2V |
| 6 | 是 | I don't have an additional preference for color. | Here are the strongest current matches. What activity or occasion will you use it for? | use_case | 87 | 112 | 116 | 116 | 43 | B01I3NKV90, B07D3SK95J, B07DHM2PJ5, B07ML2GYT7, B07BDKQQ19, B081TJRYVG, B07Q2Z4SVS, B01NBPCYI3, B08ZXPZT5V, B01MR0QH2V |
| 7 | 是 | I don't have an additional preference for use_case. | Here are the strongest current matches. Do you prefer a casual, athletic, or formal style? | style | 87 | 112 | 116 | 116 | 43 | B01I3NKV90, B07D3SK95J, B07DHM2PJ5, B07ML2GYT7, B07BDKQQ19, B081TJRYVG, B07Q2Z4SVS, B01NBPCYI3, B08ZXPZT5V, B01MR0QH2V |
| 8 | 是 | I don't have an additional preference for style. | Here are the strongest current matches. | - | 87 | 112 | 116 | 116 | 43 | B01I3NKV90, B07D3SK95J, B07DHM2PJ5, B07ML2GYT7, B07BDKQQ19, B081TJRYVG, B07Q2Z4SVS, B01NBPCYI3, B08ZXPZT5V, B01MR0QH2V |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 87 | 112 | 116 | 116 | 43 | B01I3NKV90, B07D3SK95J, B07DHM2PJ5, B07ML2GYT7, B07BDKQQ19, B081TJRYVG, B07Q2Z4SVS, B01NBPCYI3, B08ZXPZT5V, B01MR0QH2V |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | 87 | 112 | 116 | 116 | 43 | B01I3NKV90, B07D3SK95J, B07DHM2PJ5, B07ML2GYT7, B07BDKQQ19, B081TJRYVG, B07Q2Z4SVS, B01NBPCYI3, B08ZXPZT5V, B01MR0QH2V |

### boundary：1 个可用失败案例

#### public_0187 · `final_rank_over_10`

- 目标：`B000GQ1F3O` · Eastland Men's Newport Slip-On Shoe
- 类目：Clothing, Shoes & Jewelry > Men > Shoes > Loafers & Slip-Ons
- 提问序列：size, color, brand, material, style, feature, use_case；重复提问：无。
- 建议：目标已进入最终候选，优先审查通用 reranker 特征、语义排序和近邻竞争项，不扩大无证据候选池。

| 轮次 | Override 已生效 | 用户消息 | Agent 提问 | ask_attribute | BM25 | Dense | RRF | 融合 | 最终 | 返回 Top 10 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | 是 | I'm looking for Shoes Loafers & Slip-Ons, but I'm still exploring. | Here are the strongest current matches. Do you have a required size or fit? | size | - | - | 144 | 144 | 105 | B07BDKQQ19, B08SCMMXSS, B07YS3QZ94, B089WBHSNC, B016XLLDNM, B071VY9FS7, B08KT91J75, B006WBLD6G, B07Z1YM4HZ, B07DCJFK54 |
| 2 | 是 | I don't have a preference for size; please use your judgment. | Here are the strongest current matches. Which color should I prioritize? | color | - | - | 144 | 144 | 105 | B07BDKQQ19, B08SCMMXSS, B07YS3QZ94, B089WBHSNC, B016XLLDNM, B071VY9FS7, B08KT91J75, B006WBLD6G, B07Z1YM4HZ, B07DCJFK54 |
| 3 | 是 | I don't have an additional preference for color. | Here are the strongest current matches. Is there a brand you prefer? | brand | - | - | 144 | 144 | 105 | B07BDKQQ19, B08SCMMXSS, B07YS3QZ94, B089WBHSNC, B016XLLDNM, B071VY9FS7, B08KT91J75, B006WBLD6G, B07Z1YM4HZ, B07DCJFK54 |
| 4 | 是 | I don't have an additional preference for brand. | Here are the strongest current matches. Do you have a preferred material, such as cotton, leath… | material | - | - | 144 | 144 | 105 | B07BDKQQ19, B08SCMMXSS, B07YS3QZ94, B089WBHSNC, B016XLLDNM, B071VY9FS7, B08KT91J75, B006WBLD6G, B07Z1YM4HZ, B07DCJFK54 |
| 5 | 是 | For that, what matters is: leather; 100% Leather. | Here are the strongest current matches. Do you prefer a casual, athletic, or formal style? | style | - | 25 | 150 | 150 | 100 | B00V9AABEU, B007GGAX26, B008U0WIDO, B00RES87GU, B006T6CT4E, B06XS2T88L, B00HHYFUAM, B00S25TOE8, B00HLWR5S0, B00HF6Z5MK |
| 6 | 是 | I don't have an additional preference for style. | Here are the strongest current matches. Which feature matters most, such as comfort, durability… | feature | - | 25 | 150 | 150 | 100 | B00V9AABEU, B007GGAX26, B008U0WIDO, B00RES87GU, B006T6CT4E, B06XS2T88L, B00HHYFUAM, B00S25TOE8, B00HLWR5S0, B00HF6Z5MK |
| 7 | 是 | I don't have an additional preference for feature. | Here are the strongest current matches. What activity or occasion will you use it for? | use_case | - | 25 | 150 | 150 | 100 | B00V9AABEU, B007GGAX26, B008U0WIDO, B00RES87GU, B006T6CT4E, B06XS2T88L, B00HHYFUAM, B00S25TOE8, B00HLWR5S0, B00HF6Z5MK |
| 8 | 是 | I don't have an additional preference for use_case. | Here are the strongest current matches. | - | - | 25 | 150 | 150 | 100 | B00V9AABEU, B007GGAX26, B008U0WIDO, B00RES87GU, B006T6CT4E, B06XS2T88L, B00HHYFUAM, B00S25TOE8, B00HLWR5S0, B00HF6Z5MK |
| 9 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | - | 25 | 150 | 150 | 100 | B00V9AABEU, B007GGAX26, B008U0WIDO, B00RES87GU, B006T6CT4E, B06XS2T88L, B00HHYFUAM, B00S25TOE8, B00HLWR5S0, B00HF6Z5MK |
| 10 | 是 | Those options are not quite right yet. Ask me about one specific attribute. | Here are the strongest current matches. | - | - | 25 | 150 | 150 | 100 | B00V9AABEU, B007GGAX26, B008U0WIDO, B00RES87GU, B006T6CT4E, B06XS2T88L, B00HHYFUAM, B00S25TOE8, B00HLWR5S0, B00HF6Z5MK |

## 7. 使用说明

本 Markdown 用于人工复盘；同名 JSON 保存完整查询、状态、约束、路由、问题、Token、LLM 状态、目标摘要和逐轮 rank。任何后续修改只能采用跨样本通用规则，并先在同一冻结 dev 上配对验证。
