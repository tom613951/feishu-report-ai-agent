# AI Agent Project Resume & Interview Guide

This guide is designed to help you integrate this project into your resume and prepare for technical interviews. It highlights the architectural details and stability optimizations that align with the requirements of an **AI Agent Application Development Engineer**.

---

## 1. Resume Project Experience (Chinese Version for Copy-Paste)

### **项目名称**：基于大模型自我纠错机制的飞书数据看板智能体 (AI Agent)
**技术栈**：Python, LangChain/OpenAI API, Pydantic, Tenacity, Feishu (Lark) Open Platform, Pytest
**项目描述**：
针对企业日常销售/工作数据手工汇总效率低、大模型直接处理报表易产生计算幻觉与执行中断的问题，自主设计并实现了一套企业级自愈式 AI Agent 自动化报表工作流。系统从飞书多维表格（Bitable）自动拉取原始数据，调用大模型（GPT/Claude）进行深度指标提炼、异常标红与趋势分析，最终格式化为交互式飞书消息卡片自动推送至群聊。

**核心业绩与技术亮点**：
* **构建“零幻觉”程序化数据防线**：针对大模型在指标聚合与财务计算上的“数值幻觉”，设计了 **Pydantic 双向 Schema 校验 guardrails**。程序在 Python 侧对大模型返回的 JSON 进行二次代数校验（如求和、分类汇总对齐）。
* **设计 Agent 自我反思与纠错机制 (Self-Correction Loop)**：引入**反思智能体模式**，当校验引擎检测到数据偏差或幻觉字段时，自动捕获异常 Trace 并回流为反馈 Prompt，引导大模型进行多轮迭代纠错（Reflection），直至 100% 通过代数验证，实现大模型输出端“零幻觉”交付。
* **实现管道高可用与弹性容错 (Failover)**：
  - 针对外部 API 速率限制（Rate Limits / 429）和网络偶发抖动，基于 **Tenacity 封装了指数退避重试机制 (Exponential Backoff)**，实现无感重连。
  - 设计了 **硬限容灾兜底机制 (Programmatic Fallback)**，在大模型连续 3 次反思失败或模型服务崩溃时，自动降级为 Python 程序化本地聚合算法，确保生成绝对精确的基础数据报表，避免下游业务管道中断。
* **边界 Case 驱动的高质量交付**：设计了覆盖“零数据空值”、“接口 503 崩溃”、“模型计算偏差”、“模型幻觉编造”等极端边界场景的自动化测试集，实现了智能体在恶劣环境下的企业级稳定性。

---

## 2. Interview Deep-Dive (面试核心问题攻防)

### **Q1: 为什么不用大模型直接计算？大模型处理数据的硬伤是什么？**
* **回答要点**：
  1. **计算幻觉**：大模型本质是基于概率的 Token 预测，并不具备真正物理意义上的代数计算能力，面对多条数据的汇总求和极易算错。
  2. **接地性缺失 (Grounding)**：大模型在归纳团队业绩时，容易无中生有，捏造 raw data 中不存在的人名或产品名。
  3. **解决方案**：在我的设计中，**“模型做语义分析，程序做代数校验”**。大模型仅负责提取趋势和撰写小结，所有汇总、排行榜数据都通过 Python 程序化校验或者自我纠错环路来保证 100% 准确性。

### **Q2: 你的自我纠错 (Reflection Loop) 具体是怎么运转的？**
* **回答要点**：
  - 当大模型生成 Structured Output (JSON) 后，系统会使用 Pydantic 解析。
  - 解析通过后，进入 Python 编写的 **Verification Guardrail Engine**。引擎会计算 `sum(raw_records.amount)` 并将其与大模型的 `total_sales_amount` 比较；同时，比对大模型 highlights 中的销售人员集合是否与原始数据的销售人员集合一致（检测幻觉）。
  - 一旦发现偏差（例如总金额不一致，或者出现了未知的 salesperson ），程序不崩溃，而是将具体错误打包成 feedback。
  - **Prompt 示例**："The previous output failed guardrail validation. Mismatch: total salesperson highlights sum is Y, but raw sum is X. Please correct these calculations."
  - 大模型接收反馈后会在下一轮 Attempt 中改正。在测试用例中，大模型在 Attempt 2 均能完成自愈并通过校验。

### **Q3: 如果大模型连续报错，或者遭遇严重的 API Timeout，你怎么保证系统不崩溃？**
* **回答要点**：
  1. **层级重试**：网络请求用 Tenacity 包装，遇到 5xx 或 429 错误自动触发 3 次指数退避重试，解决了接口瞬时抖动。
  2. **反思上限 (Max Attempts)**：反射纠错环路设置了 `MAX_REFLECTION_ATTEMPTS = 3` 阈值，防止死循环导致 API 费用失控和响应超时。
  3. **程序化兜底 (Programmatic Fallback)**：如果 3 次反思依然报错，系统会抓取异常，直接使用纯 Python 逻辑对原始数据进行求和与分类聚合，构建一个满足 schema 的 `FallbackReport`。该报表的 anomalies 中会标注 `系统自动启用程序化聚合` 的警告，并推送到群里。这保障了**“数据准确性第一，业务不中断第一”**的生产标准。

### **Q4: 你在这个项目中如何保证敏捷开发和无 Token 本地测试？**
* **回答要点**：
  - 我设计了 `USE_FEISHU_SIMULATION` 和 `USE_LLM_SIMULATION` 两个开关。
  - 在没有配置 `.env` 密钥时，系统会自动启动 **Feishu Bitable Simulator**（生成符合格式的当日销售记录）和 **LLM Response Simulator**。
  - 在测试中，我不仅模拟了 Happy Path，还通过 `simulate_hallucination=True` 强制模拟了 LLM 的计算偏差，以此成功测试并验证了“反射环路”和“降级兜底”的代码逻辑。这套 Simulator 极大加速了开发迭代，也是大模型 Agent 架构设计中常用的 **Mocking 最佳实践**。
