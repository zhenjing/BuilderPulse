# HackerNews Daily Analyzer

## Skills

### HNdaily
Analyze Hacker News front page for user complaints and generate a daily report.

**Usage:** `/HNdaily` — fetches top stories, scores complaint density, analyzes comments, outputs `HackerNews_{date}.md`.

**Implementation:**
- Skill definition: `.claude/skills/HNdaily.md`
- Data fetcher: `.claude/scripts/hn_analyzer.py`

**Workflow:**
1. Run `.claude/scripts/hn_analyzer.py` to fetch data → outputs JSON
2. Claude analyzes the JSON, identifies Top 5 complaints, proposes product solutions
3. Write final report to `HackerNews_{YYYY-MM-DD}.md`

### BuilderPulse
Fetch 7 data sources, cross-validate signals, and generate a Chinese product daily brief for indie hackers.

**Usage:** `/BuilderPulse` — fetches HN, GitHub, HuggingFace, Reddit, Lobsters, DEV Community, Product Hunt → outputs `BuilderPulse_{date}.md`.

**Implementation:**
- Skill definition: `.claude/skills/BuilderPulse.md`
- Data fetcher: `.claude/scripts/builderpulse_fetcher.py` (~900 lines, 7 sources)

**Workflow:**
1. Run `.claude/scripts/builderpulse_fetcher.py .claude/builderpulse_data.json` → outputs JSON (3-5 min)
2. Claude reads JSON, cross-validates `cross_source_clusters` (>=2 sources), extracts revenue/complaint/trend signals
3. Generates 9-section Chinese report with 🔍signal → plain-talk → key-judgment → counter-view structure
4. Write final report to `BuilderPulse_{YYYY-MM-DD}.md`

## 日报生成规则 (Daily Report Rules)

### 必须遵守
1. **产品化分析（必须）**：每条 Top 5 抱怨必须包含独立的产品化分析模块，包括：现有方案缺陷、更优技术方案、产品化可行性（高/中/低）、产品形态建议与商业模式、目标市场
2. **中文输出**：报告正文使用中文，用户评论引用保留英文原文
3. **更新 CLAUDE.md**：每次生成日报后，如有新规则或模式发现，必须同步更新本文件

### 报告结构
1. **🤖 AI 需求全景**（必须首位）— AI 需求表（强度🔴🟡）+ 3 个可构建产品（🥇🥈🥉，每个含做什么/为什么是现在/技术路线/定价/MVP天数）
2. **🛠️ Top 5 产品机会**（非 AI 部分）— 2×2 矩阵筛选结果，含产品化分析表格
3. **📰 今日情绪背景** — 高抱怨低机会帖子表格
4. 当日市场信号汇总（含强度、方向、含义）
5. 总体洞察（情绪基调、反直觉发现）

### AI 需求专项分析规则（必须）
- 从 `ai_posts` 字段读取全部 AI 相关帖子
- 阅读高评论数（descendants > 50）AI 帖子的评论，提取需求信号
- 需求强度判断：评论中明确付费意愿/替代搜寻 = 🔴强；讨论活跃但无付费信号 = 🟡中；纯科技新闻 = 🟢弱（不列）
- 最终输出限 5-8 条需求，按"个人开发者可满足"排序
- 提炼 3 个可构建产品，每个说明：做什么、为什么是现在、技术路线、定价、MVP 天数

### Top 5 筛选规则（双重评分）

使用 `complaint_score` 和 `opportunity_score` 两个独立维度交叉筛选：

| 象限 | complaint | opportunity | 处理方式 |
|------|-----------|-------------|---------|
| 🔥 头条机会 | 高 | 高 | 深度产品化分析（如 Stripe 欺诈） |
| 📡 弱信号 | 低 | 高 | **升级为产品机会**（如新 API 缺口、工具链空白） |
| 📰 背景噪音 | 高 | 低 | 降级为"今日情绪背景"（如化学灾难、政治事件） |
| 🗑️ 跳过 | 低 | 低 | 不纳入报告 |

**关键规则：**
- `opportunity_score >= 3` 为"高"，`< 3` 为"低"
- `complaint_score >= 5` 为"高"，`< 5` 为"低"
- 低抱怨+高机会的信号优先于高抱怨+低机会的信号
- 每条 Top 5 候选标注"可构建性"：🟢单人2周可做 / 🟡需小团队 / 🔴需融资

### 数据获取
- 当天数据：使用 Firebase API (`hacker-news.firebaseio.com`)
- 历史数据：使用 Algolia API (`hn.algolia.com/api/v1/search`)，timestamp 计算注意 EST (UTC-5)
- 评论抓取：取每篇帖子的 `kids` 前 20-30 条，过滤 dead/deleted，去除 HTML 标签

## BuilderPulse 生成规则

### 核心哲学：编辑思维 > 分析师思维
- **定位**：编辑精选 + 行动手册，不是数据分析报告
- **核心问题**："今天你应该做什么、为什么？"（不是"今天发生了什么？"）
- **筛选原则**：隐藏风险 + 买方紧迫度 = 重要（不是数据量大、跨源多 = 重要）
- **叙事方法**：故事钩子 → 人类后果 → 行动判断（不是数据 → 结论）
- **统一性**：9 段共用一个叙事透镜（Narrative Lens），不是 9 段各说各的

### 叙事透镜（Narrative Lens）—— 动笔前必做
1. 找出今天最反直觉的一个数据点（不是最大的，是最让你意外的）
2. 用一句话写出来："今天的变化是，______" → 这句话成为整篇 9 段的统一透镜
3. 好的透镜揭示隐藏风险/代价/机会，坏的透镜只是数据描述或趋势描述
4. 透镜定义好之后，9 段每一段都必须服务它——不服务的内容砍掉

### 信号筛选三层过滤器（选信号时必须逐层过）
1. **隐藏风险过滤器**：这个信号是否暴露了一个人们默认信任但实际可能出错的假设？（是 → 进入候选 / 否 → 降级为背景）
2. **买方紧迫度过滤器**：谁会因为这个故障而受伤？有多快需要修复？（生产故障 > 合规审计 > 月度成本优化 > 便利性提升）
3. **可构建性过滤器**：这个故障能否在 2 小时内做出一个可展示的产物？（是 → 头条 + 2h 构建 / 否 → 仅做信号分析）

### 刘小排说写作规范（~280 字，编辑专栏风格）
- 第一句必须是"为什么你要关心这个"，不是"今天数据说了什么"
- 结构：故事钩子 + 3 个简洁问答（谁在受伤？→ 为什么是现在？→ 价格锚点在哪？）
- 用具体的故障后果替代抽象的统计数据
- 保持节奏：短句→中句→短句→中句
- 最后一句让读者在 5 秒内做出行动决定

### 证据表规范（硬性上限 3-4 行）
- 每行必须服务于当天的叙事透镜（不服务 = 砍掉，留给明天或附录）
- 行与行之间必须有递进或并列的逻辑关系（不能随机堆叠）
- 白话含义栏用"买方后果"语言，不是"趋势描述"语言

### 白话翻译三层检查
- 第一层（数据→趋势）：发生了什么技术变化？
- 第二层（趋势→后果）：这个变化对谁有什么实际影响？
- 第三层（后果→买方语言）：受影响的人需要买什么来解决？
- 每个"白话说"至少到达第二层，头条内容必须到达第三层

### 必须遵守
1. **单一推荐**：每天仅推荐 1 个最佳 2 小时构建机会（"今日 2 小时构建" + "行动触发"详细拆解）
2. **中文输出**：正文中文，专业术语首次出现加括号英文原文（如：智能体（AI Agent）、MCP（模型上下文协议））
3. **数据支撑**：每个断言必须引用至少 1 个数据源（HN/GitHub/Reddit/PH/DEV/HF/Lobsters）
4. **四层分析**：每子节必须遵循 🔍信号 → 白话说 → 关键判断 → 反向视角
5. **交叉验证**：优先使用 `cross_source_clusters`（≥2 源），单源信号标注"单源，待验证"
6. **自反性**：每个判断必须有反向视角，指出信号的可能局限或反方逻辑
7. **术语解释**：首次出现的专业术语在括号中提供一句话解释

### 报告结构（9 段）
1. 📝 刘小排说 — 编辑精选（~280 字）：故事钩子 + 3 个简洁问答 + 行动判断
2. 🎯 今日 2 小时构建 — 单一最佳产品机会（~100 字），按紧迫度排序选题
3. 今日 Top 3 信号 — 交叉验证的 top 3 信号（~200 字），每条注明来源
4. 白话简报 — 证据表（上限 3-4 行）+ 读者含义表（科技爱好者/构建者/谨慎点）
5. 发现机会 — 4 子节：solo 发布 / 搜索词 / GitHub 缺口 / 抱怨分析
6. 技术选型 — 5 子节：关闭降级 / 开发者工具 / HF 模型 / 开源 AI / Show HN 栈
7. 竞争情报 — 4 子节：收入定价 / 复活项目 / 迁移故事 / PH-DX 重叠
8. 趋势判断 — 4 子节：关键词 / VC 话题 / 降温词 / 新词雷达
9. 行动触发 — 4 子节：2h 方案 / 定价模型 / 反直觉发现 / PH-DX 重叠

### 数据获取
- 脚本：`python .claude/scripts/builderpulse_fetcher.py .claude/builderpulse_data.json`（约 3-5 分钟）
- 7 个数据源：HN Firebase + Algolia / GitHub Search / HuggingFace / Reddit (3 subs) / Lobsters / DEV Community / Product Hunt RSS
- Google Trends 不可用（GFW + API 限制），改用跨源 bigram 频率推断
- Product Hunt 评论数通过详情页抓取富化（仅今日发布产品）
- 所有 fetch 函数包裹 try/except，单源失败不影响整体
