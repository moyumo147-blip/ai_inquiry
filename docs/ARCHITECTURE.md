# 架构设计说明

> 本文解释「为什么这样拆」以及「关键取舍」，配合 `README.md` 的结构说明一起看。

## 1. 设计目标

| 目标 | 落点 |
|---|---|
| 复用已完成的知识库，不重复建设 | 检索只读 `medical_cases / qa_pairs / case_chunks`，不引入 Milvus/新向量库 |
| 医疗场景「不能出错」优先 | 规则护栏前置、急诊不过模型、不做确诊/处方、统一免责 |
| 与 EduAgent 同构，便于对照学习 | 目录、配置、日志、LLM 工厂、Agent 图、SSE 协议一一对应 |
| 可演示、可验证 | 后端 10 项冒烟 + 前端浏览器冒烟 + 截图 |

## 2. 分层职责

```
api/        只做 HTTP：参数校验、鉴权、事务边界、事件序列化
agents/     只做「一次业务推理」：状态机 + Prompt + 结构化输出
core/       横切能力：LLM、向量、检索、安全、日志、编排
db/         持久化：会话、消息、分诊、病历（知识库走原生 SQL）
```

约束：

- Agent 不直接 `ChatOpenAI(...)`，一律 `core.llm_factory.get_llm(agent_type)`；
- API 不拼 SQL，一律 `db.repositories`；
- 检索失败 / 模型超时必须降级，不能让接口 500。

## 3. 三个 Agent

### 3.1 分诊 Triage

```
START → safety_check（规则） → triage（qwen-max 结构化） → END
```

- `safety_check` 只做规则，产出 `level / flags`；
- `triage` 输出 `TriageOutput`：科室、紧急度、红旗、鉴别方向、建议检查、追问、建议、理由；
- **合并策略**：`urgency = max(规则, LLM)` —— 规则判急诊时，LLM 不能降级；
- 模型不可用 → `rule_based_fallback`（14 条科室关键词表），接口仍可用。

耗时实测：约 5-6 s（qwen-max，含网络）。

### 3.2 问诊 Consultation

```
START → safety_check ──emergency──► emergency → END
                    └─► classify ──record/chitchat──► generate → suggest_followup → END
                                └──medical──► retrieve → generate → suggest_followup → END
```

状态字段（`state.py`）刻意保持扁平，便于 SSE 阶段从 `on_chain_end` 增量合并：

| 字段 | 来源 | 用途 |
|---|---|---|
| `safety / urgency` | safety_check | 分级、急诊话术 |
| `intent` | classify（正则） | medical / chitchat / record |
| `context / citations / confidence / coverage` | retrieve | Prompt 与前端引用 |
| `answer / answer_mode` | generate | 回答与展示标签（rag / llm_direct / emergency / chitchat / record_hint） |
| `followups` | suggest_followup | 追问按钮 |

**为什么分类用正则而不是 LLM**：只有三类且特征明显（寒暄、含「病历」、其余），正则零成本、确定性好；把模型调用留给真正需要理解的部分。

**为什么不用 LangGraph Checkpointer**：会话历史落在 `consult_messages`，重启/多副本都不丢；每轮把最近 10 条注入 State，比内存 checkpointer 更符合「会话要能被前端查询」的需求。

### 3.3 病历 Record

```
START → generate_record（qwen-max 结构化 SOAPOutput） → END
```

- 输入：整段会话 + 最近一次分诊；
- 输出：主诉 / 现病史 / 既往史 / 过敏史 / 体格检查 / 初步评估 / 诊疗计划 / 初步诊断 / 摘要；
- 落库为 `draft`，前端可编辑后 `PUT`；
- 模型失败 → `_fallback_soap`（仅客观摘录患者原话，不做医学判断）。

### 3.4 长会话摘要（`core/summarizer.py`，不是 Agent）

消息数 ≥ `summary_trigger_messages`（默认 12）时触发：

1. 取 `id > summary_message_id` 的消息，保留最近 `summary_keep_recent`（默认 6）条原文；
2. 其余交给 qwen-plus 压成 ≤300 字的「就诊摘要」（主诉、病程、关键症状、既往史/用药/过敏、已做检查、已给建议）；
3. 写入 `consult_sessions.summary`，把 `summary_message_id` 前移到被压缩的最后一条 id。

之后每轮 Prompt = 【既往摘要】+【最近对话原文】，上下文不再线性膨胀；压缩失败只记 warning，不影响当轮回答，下一轮会重试。

> 已知风险：摘要只有最新一版、无版本历史，也没有自动校验「摘要是否失真」；性别/年龄等缺失信息需靠 Prompt 明确禁止推测。

## 4. Prompt 设计要点

三个系统提示都显式写了「铁律」，并按优先级排序：

1. **安全**：急诊场景先说「立即急诊/120」，不先问东问西；
2. **边界**：不确诊、不开药、不给剂量；
3. **依据**：引用知识库时用「知识库中类似病例多就诊于××科」，禁止编造医院/医生/论文；
4. **追问**：一次最多 3 个问题，优先病程、伴随症状、既往史/用药、过敏史、特殊人群；
5. **结构**：方向 → 依据 → 下一步（科室 + 紧急度 + 就诊前观察）；
6. **长度**：450 字以内，Markdown 小标题 + 短句。

追问单独用一次 `qwen-plus` 纯文本调用（每行一个问题）而不是结构化输出：实测 qwen 在 function calling 下偶发返回 `None`，纯文本解析更稳。

## 5. SSE 协议

`POST /api/v1/chat/stream`，`text/event-stream`，每帧 `data: {json}`：

| type | 字段 | 时机 |
|---|---|---|
| `progress` | `stage` | 节点开始（安全评估 / 理解问题 / 检索 / 生成 / 整理追问） |
| `token` | `content` | `generate` 节点内模型流式 token |
| `meta` | `citations / followups / urgency / confidence / answer_mode / safety / disclaimer` | 流结束，一次性 |
| `done` | — | 结束标记 |
| `error` | `message` | 异常 |

服务端用 `graph.astream_events()`：`on_chat_model_stream` 只透传 `langgraph_node == "generate"` 的 token（否则 `suggest_followup` 的结构化调用会污染正文）；`on_chain_end` 的节点输出字典按序合并，得到最终 meta。

前端 `useSSEChat.ts` 直接读 `fetch` 的 `ReadableStream`（EventSource 不支持 POST + Bearer），按 `\r?\n\r?\n` 切帧 —— sse-starlette 默认用 `\r\n` 分隔，按 `\n\n` 切会一帧都解析不出来（这是本次联调踩到的真实 bug）。

## 6. 安全分级矩阵

| 级别 | 触发 | 行为 |
|---|---|---|
| emergency | 胸痛、呼吸困难、意识改变、大出血、抽搐、剧烈头痛、自杀风险、孕产急症、婴幼儿精神差、严重过敏、中毒 | 固定话术 + 立即急诊/120；会话后续轮次保持急诊口径；不走 RAG |
| urgent | 高热、剧烈腹痛、频繁吐泻、黄疸、体重骤降、久咳、视力骤降、外伤、精神症状 | 24h 内就诊；正常 RAG，但回答末尾附加强提示 |
| routine | 其余 | 常规门诊建议 |

否定词处理：命中关键词前 4 字内出现「不 / 无 / 没有 / 未 / 否认」时跳过，避免「没有胸痛」被误判。

## 7. 检索实现

```text
query = f"{会话主诉}；{本次提问}"[:300]
vec = embed(query)                    # DashScope text-embedding-v2, 1536
rows = SELECT ... 1-(embedding<=>vec) AS score
       FROM case_chunks c JOIN medical_cases m ON m.id=c.case_id
       ORDER BY embedding<=>vec LIMIT 40
final = 0.75*sim + 0.15*dept_match + 0.10*ngram_overlap
dedup by case_id → top 6
qa = SELECT ... FROM qa_pairs WHERE case_id IN (...) ORDER BY turn_no
```

参数都在 `config.py`：`retrieval_candidates=40`、`retrieval_top_k=6`、`min_confidence=0.35`。

## 8. 关键取舍（ADR）

| 决策 | 理由 | 代价 |
|---|---|---|
| 用 pgvector 而非 Milvus | 知识库已含向量与 HNSW 索引，零迁移成本 | 无 sparse/多路融合，召回弱于 EduAgent 的 hybrid |
| 查询向量必须用 `text-embedding-v2` | 入库时的向量空间由它决定 | 依赖 DashScope 可用性 |
| 规则护栏前置 | 医疗场景不能被模型幻觉绕过，且规则可解释 | 关键词覆盖有限，需持续补充 |
| `qa_pairs` 不补向量 | 遵守「不再向知识库加数据」的要求 | 相似问答只能按病例关联 |
| PBKDF2 而非 passlib+bcrypt | 标准库实现，避免 Windows 上 bcrypt 版本冲突 | 无 argon2 的抗 GPU 强度 |
| 会话历史存 DB，不用 checkpointer | 可查询、可重启、可多副本 | 每轮多一次查询，长会话需摘要压缩（未做） |
| 分诊/病历用 qwen-max，对话用 qwen-plus | 结构化任务要稳定，对话要成本与延迟 | 两档模型，成本略高 |

## 9. 降级与容错

| 故障 | 表现 | 降级 |
|---|---|---|
| LLM 超时/限流 | 生成节点异常 | 返回固定提示；分诊走规则表；病历走客观摘录 |
| 结构化输出失败 | `with_structured_output` 返回 None | 追问改纯文本解析；分诊/病历有 fallback |
| Embedding 失败 | `RetrievalError` | `context` 置空，`answer_mode=llm_direct`，前端提示知识库不可用 |
| 迁移失败 | 启动告警 | 不阻断启动（业务表缺失时接口报错可定位） |
| SSE 中断 | 客户端 abort | 后端生成器退出，已落库的用户消息保留 |

## 10. 测试

- `scripts/smoke_test.py`：健康检查、注册、建会话（自动分诊）、普通问诊、SSE、病历、列表、病例库关键词/语义、统计、急诊分诊与急诊话术，共 10 组断言。
- `scripts/evaluate.py`：三套离线评测 —— 检索（原病例 Recall@1/@6、同疾病 Recall@6、MRR）、分诊（科室 Top-1 与科室族准确率，只抽 ≥300 条的常见科室）、安全护栏（20 条人工构造的急诊/否定/常规样例）。报告写入 `docs/EVAL.md`。
- `scripts/test_summary.py`：连续 6 轮触发摘要压缩，校验消息数、摘要长度与关键信息，并在摘要后继续问诊。
- `frontend/scripts/ui-smoke.mjs`：Playwright（复用系统 Edge）+ 真实点击，覆盖登录、新建问诊、SSE 对话、病历页、病例库语义检索，输出 5 张截图并收集控制台错误。
- `frontend` 通过 `vue-tsc --noEmit` 类型检查与 `vite build` 生产构建。

## 11. 当前评测结果（2026-11-03）

| 套件 | 指标 | 结果 |
|---|---|---|
| 检索（30 条） | 原病例 Recall@1 / Recall@6 | 80.0% / 86.7% |
| 检索（30 条） | 同疾病 Recall@6 / MRR | 86.7% / 0.828 |
| 分诊（16 条） | 科室 Top-1 / 科室族 | 62.5% / 62.5% |
| 安全护栏（20 条） | 分级准确率 | 100% |

> 分诊失败多为「神经内科 vs 神经外科」「胸外科 vs 呼吸内科」这类相邻科室；知识库科室写法有 886 种，评测已归一。详见 `docs/EVAL.md`。

## 12. 演进路线

1. **评测集扩充**：当前 30 条检索 / 16 条分诊 / 20 条安全样例偏少，分诊 Top-1 62.5% 需扩到 100+ 条人工标注后再谈提升。
2. **摘要质量**：摘要版本化（保留历史版本 + 压缩前后差异）、加入「摘要是否遗漏红旗症状」的自动检查。
3. **复诊 Agent**：基于 `medical_records` 生成随访计划与提醒。
4. **医生端**：审核队列、病历修改留痕、危急值升级通知。
5. **多模态**：皮肤照片、化验单 OCR、语音问诊。
