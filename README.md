# 安诊 — AI 问诊系统

> 面向常见病与慢病复诊的 AI 预问诊平台。  
> 基于 **FastAPI + LangGraph 1.2 + PostgreSQL/pgvector** 构建，核心大模型为 **通义千问 qwen-plus / qwen-max**，知识库来自 **54,118 条真实医患问答病例**。

---

## 项目背景

门诊场景里，医生的大量时间花在重复性工作上：

| 场景 | 痛点 |
|------|------|
| 预问诊 | 患者说不清「该挂哪个科」，挂错号后反复转诊 |
| 病史采集 | 每次都要重问一遍病程、用药、过敏史 |
| 病历书写 | 门诊量大，SOAP 病历靠手打，耗时且格式不一 |
| 健康咨询 | 同类问题反复解答，回答质量依赖医生个人经验 |
| 安全风险 | 胸痛、呼吸困难等急症被当成普通咨询，延误就医 |

安诊把这几件事拆成三个独立的 AI Agent：**分诊、问诊、病历**，每个 Agent 内置完整业务流程、融合真实病例知识库，并在最前面加了一层规则安全护栏。

---

## 核心模块

| 模块 | 业务能力 | 核心技术范式 |
|------|---------|------------|
| **智能分诊（Triage）** | 主诉 → 科室 / 紧急程度 / 红旗症状 / 建议检查 | 规则引擎 + qwen-max 结构化输出，紧急度取两者较大值 |
| **RAG 问诊（Consultation）** | 多轮追问、病例引用、就医方向建议 | LangGraph 条件图 + pgvector 检索 + SSE 流式 |
| **SOAP 病历（Record）** | 对话 → 主诉 / 现病史 / 既往史 / 评估 / 计划 | 结构化输出 + 可编辑草稿 |
| **安全护栏（Safety）** | 20+ 类红旗症状识别与急诊话术 | 正则规则 + 否定词处理，急症不经过大模型 |
| **病例知识库** | 5.4 万条病例的关键词与语义检索 | pgvector HNSW（COSINE）+ pg_trgm |
| **长会话摘要** | 12 条消息后压缩历史，控制上下文长度 | qwen-plus 摘要 + 水位线增量压缩 |

三个 Agent 之上由 **Orchestrator** 统一做会话级编排：新建会话时先跑分诊，把科室与紧急度回写会话，并生成开场白。

---

## 技术栈

| 层面 | 选型 |
|------|------|
| 开发语言 | Python 3.11（严格锁定） |
| Web 框架 | FastAPI + SSE-Starlette |
| Agent 框架 | LangGraph 1.2 + LangChain Core 1.7 |
| 大模型 | qwen-plus（对话） / qwen-max（分诊、病历） |
| 向量模型 | text-embedding-v2（1536 维，与知识库入库一致） |
| 向量数据库 | PostgreSQL 18 + pgvector 0.8.6（HNSW / COSINE） |
| 关系数据库 | PostgreSQL 18 + SQLAlchemy 2.0（asyncpg，全异步） |
| 认证 | JWT（PyJWT）+ PBKDF2-SHA256 |
| 前端 | Vue 3.5 + TypeScript + Element Plus + Vite 5 |

> 检索不依赖独立向量服务：案例向量直接存在 `case_chunks` 表，与业务表同库，省掉一次跨服务调用。

---

## 系统架构

```
┌─────────────────────────────────────────────────┐
│              前端层   Vue3 SPA (:5173)           │
└────────────────────┬────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────────┐
│            API 层   FastAPI (:8000)              │
│       JWT 鉴权 / SSE 流式 / 会话与病历 CRUD       │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│          编排层   Orchestrator                   │
│      会话创建 → 预问诊分诊 → 开场白落库            │
└──────┬───────────┬────────────────┬─────────────┘
       │           │                │
 ┌─────▼─────┐ ┌───▼────────┐ ┌────▼──────┐
 │  Triage   │ │Consultation│ │  Record   │   ← LangGraph StateGraph × 3
 │  Agent    │ │   Agent    │ │  Agent    │
 └───────────┘ └────────────┘ └───────────┘
                     │
                  公共层 core
   ├── LLM Factory（qwen-plus / qwen-max 路由 + 缓存）
   ├── Embeddings（text-embedding-v2，1536 维）
   ├── Retriever（pgvector 召回 + 科室/关键词精排）
   ├── Safety（红旗症状规则 + 急诊固定话术）
   └── Summarizer（长会话摘要压缩）
                     │
┌────────────────────▼────────────────────────────┐
│        数据层   PostgreSQL 18 + pgvector          │
│   知识库（只读）：medical_cases / qa_pairs /      │
│                   case_chunks                    │
│   业务表（读写）：users / consult_sessions /      │
│                   consult_messages /             │
│                   triage_records / medical_records│
└─────────────────────────────────────────────────┘
```

**问诊 Agent 的状态图**

```
START → safety_check ──急诊──► emergency（固定话术）→ END
                    │
                    └─► classify ──寒暄/病历──► generate → suggest_followup → END
                              │
                              └──医疗──► retrieve → generate → suggest_followup → END
```

- `safety_check`：纯规则，命中红旗症状直接短路，不让模型改写急诊结论；
- `classify`：正则判断意图（寒暄 / 要求写病历 / 医疗问题），零模型成本；
- `retrieve`：把会话主诉拼进查询做向量召回，再按科室与关键词精排；
- `generate`：qwen-plus 流式生成，SSE 逐字推送；
- `suggest_followup`：生成 ≤3 个追问，前端渲染成可点击的快捷问题。

---

## 环境要求

- Python **3.11**（严格锁定，不兼容其他版本）
- Node 20+ 与 pnpm（前端构建）
- PostgreSQL 18，需安装 `vector`（pgvector 0.8.6+）与 `pg_trgm` 扩展
- 阿里云百炼 API Key（需同时支持 `qwen-plus`、`qwen-max` 与 `text-embedding-v2`）

---

## 快速开始

### 1. 克隆项目 & 创建环境

```bash
git clone <repo-url>
cd AI_Consultation

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env.local
```

打开 `.env.local`，填写必填项：

```ini
DB_HOST=localhost
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=your_db_password

DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx
JWT_SECRET_KEY=any-random-secret-string
```

> `EMBEDDING_MODEL` 必须保持 `text-embedding-v2`：知识库里的 1536 维向量由它生成，换模型会导致检索失效。

### 3. 准备数据库

本机已有 PostgreSQL + pgvector 时直接连；想隔离环境可用附带的 compose（映射到 5433，避免与本地 5432 冲突）：

```bash
docker compose up -d
```

业务表会在后端启动时自动创建（幂等 DDL），也可以手工执行：

```bash
psql -U postgres -d postgres -f scripts/init_db.sql
```

### 4. 导入知识库（首次运行）

把病例 txt 放进 `medical_data/`，执行入库脚本（解析病例 → 拆分问答 → 生成 1536 维向量）：

```bash
python main.py
```

> 原始数据约 7GB，未随仓库提供。入库完成后 `medical_cases` 约 5.4 万条、`qa_pairs` 约 2.5 万条、`case_chunks` 约 5.4 万条。

### 5. 创建演示账号

```bash
python scripts/seed_demo.py       # demo / demo123456
```

### 6. 启动后端

```bash
# 在项目根目录（AI_Consultation/）下执行
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### 7. 启动前端

```bash
cd frontend
pnpm install
pnpm dev
```

---

## 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| FastAPI 后端 | **8000** | REST + SSE，`/docs` 查看 Swagger |
| Vue3 前端 | **5173** | 患者端界面，`/api` 已代理到 8000 |
| PostgreSQL | **5432** | 知识库与业务表同库 |

> 连接配置统一从 `.env.local` 读取，**禁止硬编码**。

---

## 访问地址 & 测试账号

| 地址 | 说明 |
|------|------|
| http://127.0.0.1:5173 | 前端应用 |
| http://127.0.0.1:8000/docs | FastAPI 接口文档（Swagger） |
| http://127.0.0.1:8000/health | 健康检查 |

| 账号 | 密码 | 角色 |
|------|------|------|
| demo | demo123456 | 患者 |

---

## 目录结构

```
AI_Consultation/
├── backend/
│   ├── main.py                  # FastAPI 入口 & lifespan（日志 + 自动迁移）
│   ├── config.py                # pydantic-settings 配置（.env.local）
│   ├── dependencies.py          # JWT 鉴权依赖注入
│   ├── api/v1/                  # 路由：auth / sessions / chat / triage / records / cases / system
│   ├── agents/
│   │   ├── triage/              # graph.py / nodes.py / state.py / prompts.py
│   │   ├── consultation/
│   │   └── record/
│   ├── core/
│   │   ├── llm_factory.py       # LLM 统一工厂（qwen-plus / qwen-max）
│   │   ├── embeddings.py        # 查询向量化（text-embedding-v2）
│   │   ├── retriever.py         # pgvector 召回 + 规则精排
│   │   ├── safety.py            # 红旗症状规则 + 急诊话术
│   │   ├── summarizer.py        # 长会话摘要压缩
│   │   ├── orchestrator.py      # 预问诊编排
│   │   └── security.py          # PBKDF2 + JWT
│   ├── db/
│   │   ├── session.py           # 异步引擎 / 会话
│   │   ├── migrations.py        # 启动时幂等 DDL
│   │   └── repositories.py      # 数据访问层
│   ├── models/entities.py       # ORM 实体
│   └── schemas/                 # API 模型 + Agent 结构化输出
├── frontend/src/
│   ├── views/                   # 登录 / 概览 / 问诊 / 病历 / 病例库
│   ├── components/              # 聊天气泡、分诊卡片、引用列表、布局
│   ├── composables/             # useSSEChat（fetch 流式解析）
│   ├── api/                     # HTTP 客户端封装
│   └── stores/                  # Pinia 状态管理
├── scripts/
│   ├── init_db.sql              # 业务表 DDL
│   ├── seed_demo.py             # 演示账号
│   ├── smoke_test.py            # 端到端冒烟
│   ├── evaluate.py              # 离线评测（检索 / 分诊 / 安全）
│   └── test_summary.py          # 长会话摘要验证
├── docs/                        # 架构说明、评测报告、界面截图
├── main.py                      # 知识库入库脚本
├── requirements.txt
└── docker-compose.yml
```

---

## 知识库导入

知识库是**只读**的：问诊、分诊、病历都只做 SELECT，不会写回病例数据。

```bash
# 把 medical_data/*.txt 放入目录后执行
python main.py
```

脚本会完成三件事：

1. 按 `id=数字` 切分病例，解析医院 / 科室 / 疾病 / 病情 / 对话；
2. 按 URL 去重写入 `medical_cases`，并把对话拆成 `qa_pairs`；
3. 生成病例摘要 chunk，调用 `text-embedding-v2` 得到 1536 维向量写入 `case_chunks`。

可选：给检索加辅助索引（只建索引，不改数据）：

```sql
CREATE INDEX IF NOT EXISTS idx_cases_desc_trgm ON medical_cases USING gin (patient_description gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_cases_department ON medical_cases (department);
```

---

## 评测

```bash
python scripts/evaluate.py        # 检索 / 分诊 / 安全护栏，报告写入 docs/EVAL.md
python scripts/smoke_test.py      # 端到端冒烟（分诊、SSE、病历、急诊）
python scripts/test_summary.py    # 长会话摘要链路
```

当前结果（2026-11-03，详见 `docs/EVAL.md`）：

| 套件 | 指标 | 样本 | 结果 |
|------|------|------|------|
| 检索 | 原病例 Recall@1 / Recall@6 | 30 | 80.0% / 86.7% |
| 检索 | 同疾病 Recall@6 / MRR | 30 | 86.7% / 0.828 |
| 分诊 | 科室 Top-1 | 16 | 62.5% |
| 安全护栏 | 分级准确率 | 20 | 100% |

> 知识库科室写法有 886 种，评测前已归一到 20 个二级学科；16 条样本量偏小，62.5% 只作为基线，不宜据此调 Prompt。

---

## 容错机制

| 层级 | 触发条件 | 处理方式 |
|------|---------|---------|
| 第一层：规则兜底 | 分诊模型不可用 | 退回 14 条科室关键词规则表，接口仍返回结果 |
| 第二层：降级回答 | 检索失败 / 无命中 | `answer_mode=llm_direct`，基于通用医学知识回答并标注依据不足 |
| 第三层：固定话术 | 命中红旗症状 | 不经过大模型，直接返回急诊模板，避免结论被改写 |
| 结构化输出失败 | 模型未按 Schema 返回 | 分诊走规则表、病历走客观摘录、追问改纯文本解析 |

SSE 中断、单条记录写入失败都只影响当轮，不会污染会话；用户消息先落库，重试不会丢上下文。

---

## 常见问题

**Q: 前端 SSE 一直显示"生成建议…"，没有逐字输出**

后端 `EventSourceResponse` 默认用 `\r\n` 分隔事件帧。前端必须按 `\r?\n\r?\n` 切帧，只按 `\n\n` 切会一帧都解析不出来，页面表现为一直卡在生成中。

**Q: 检索结果和问题不相关（比如问"需要做哪些检查"却召回高血脂病例）**

追问句太短，单独做向量检索会跑偏。已在 `retrieve` 节点把会话主诉拼进查询（`主诉；本次提问`），相似度从 0.51 提升到 0.77。如果自己改检索逻辑，注意保留这一步。

**Q: 分诊科室和知识库里的科室对不上**

知识库有 886 种科室写法（含"胆石病中心""成人外科中心"这类细分中心），模型输出的是标准二级学科。评估请先做归一化，否则准确率没有意义。

**Q: 改了 embedding 模型后检索全乱**

`case_chunks.embedding` 是用 `text-embedding-v2` 生成的 1536 维向量。换模型必须重跑 `main.py` 重新生成，否则查询向量与库向量不在同一空间。

**Q: 启动时提示端口被占用**

后端默认 8000、前端 5173、数据库 5432。改端口只需改 `.env.local` 的 `APP_PORT` 与 `frontend/vite.config.ts` 的代理目标，不要在代码里硬编码。

**Q: 长会话会不会超出上下文？**

消息数达到 12 条后会自动把早期对话压成 ≤300 字摘要，后续只带「摘要 + 最近 6 条原文」。摘要失败只告警，不影响当轮回答。

---

## License

本项目仅用于学习与研究，未经授权不得用于商业用途。  
系统输出不构成医疗建议、诊断或处方，任何诊疗决策请咨询具备资质的执业医师。
