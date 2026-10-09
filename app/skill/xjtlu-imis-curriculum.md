# 西交利物浦大学 IMIS 专业课程知识库

> **来源**:西交利物浦大学官网本科专业页面(Information Management and Information Systems,2025-2026 学年模块列表;官方注明"Programme modules listed are illustrative only and subject to change",以 e-Bridge Portal 生效课程为准)。
> **用途**:配合 imis-course-tutor skill 使用,帮助学生把每份课件放回专业课程体系中理解。细节一律以学生提供的课件为准。
> **参考网站(可选)**:IMIS 职业地图 https://xjtlu-imis-career-atlas.pastel-pony-0751.chatgpt.site/ (若无法访问就跳过,不阻塞讲解)。

## 一、专业概况

- 全称:BSc Information Management and Information Systems(信息管理与信息系统),XJTLU 下设于国际商学院(IBSS)体系,课程主任 Dr Lu Yang。
- 定位:**管理 + 工程交叉学科**,横跨智能运营、信息技术、经济学、金融等领域。
- 毕业生去向:电子商务、信息技术、金融服务等行业的管理岗和技术岗,以及深造(硕士)读研。
- 培养主线(按年份):Y1 英语/数学/通识 → Y2 商业与技术基础 → **Y3 信息系统核心(数据库、软件工程、电商、BI、金融数学)** → Y4 高阶方向(大数据、金融科技、机器学习等)。

## 二、课程体系总览图

```
Year 1  英语(EAP) + 数学物理 + 人文社科(通识打底)
   │
Year 2  商业基础:会计(2门) / 经济学 / 金融学 / 统计 / 数量方法
   │    技术基础:数据库导论 / Java 编程 / 算法与问题求解 / AI in Business
   │    (注:Y2 的 SQL 与 Java 是大三所有技术课的"地基")
   ▼
Year 3  ★ 核心:软件工程 I / 软件工程小组项目 / 电商系统 / 高级数据库管理
   │          商业智能 / 数字化与可持续发展 / 金融数学导论
   │    选修:高级 OO 编程 / 人本计算 / 财务管理 / 证券市场
   ▼
Year 4  核心:电商技术 / 金融与市场 / 大数据分析
   │    选修:FYP 毕业设计 / 机器学习 / 移动计算 / 计算机系统安全 /
   │          软件工程 II / 金融科技交易 / 电商模式与战略 / 营销类 / 商业战略等
   ▼
就业方向  数据分析 / BI / 后端开发 / 产品经理 / 电商运营 / ERP与IT咨询 / 金融科技
```

## 三、Year 3 核心课程(重点,逐门详解)

### 1. Software Engineering I(软件工程 I)
- **定位**:从"写代码"上升到"工程化地做软件"。前置:Y2 Java 编程 + 算法;后续:Y4 Software Engineering II。
- **核心主题**:
  - 软件生命周期模型:瀑布(Waterfall)、敏捷(Agile)、Scrum 迭代开发;
  - 需求工程:功能性/非功能性需求、用例(Use Case);
  - UML 建模:用例图、类图、时序图、活动图;
  - 软件设计原则:模块化、内聚与耦合、SOLID 入门;
  - 软件测试基础:单元测试、集成测试、验收测试;
  - 配置管理与版本控制(Git 概念)。
- **现实应用**:后端/全栈开发、IT 项目中的需求分析;工作中写需求文档、画 UML、按 Scrum 迭代开发、用 Git 协作,全是这门课的内容。

### 2. Software Engineering Group Project(软件工程小组项目)
- **定位**:SE I 的实战课,以小组形式从需求到交付完整做一个软件项目(含演示与文档)。前置:SE I;后续:Y4 FYP。
- **核心主题**:团队分工与角色(Scrum Master/Product Owner)、需求分析与范围控制、系统设计、迭代开发、测试、项目文档、演示与答辩。
- **现实应用**:这就是"工作经验"本身——求职时最常被问的项目经历;工作中敏捷团队协作、代码评审、迭代节奏都在这门课里练过。

### 3. E-Business Systems(电子商务系统)
- **定位**:商业 + 技术交叉,理解电商平台怎么运转。前置:Y2 数据库、经济学;后续:Y4 Technologies for E-Commerce、E-Business Models and Strategies。
- **核心主题**:
  - 电商模式:B2B / B2C / C2C / C2B / O2O;
  - 电商系统架构:前端商城、订单系统、库存、支付、物流、推荐;
  - 在线支付与安全:支付网关、第三方支付、交易安全;
  - 数字营销与用户转化:流量、转化率、复购;
  - 电商供应链与履约。
- **现实应用**:电商运营、产品经理、跨境电商(亚马逊/Shein/Temu 类)从业者的核心知识;面试常问"订单状态机怎么设计""转化漏斗怎么分析"。

### 4. Advanced Database Management(高级数据库管理)
- **定位**:在 Y2 Introduction to Databases(SQL)基础上深入数据库内核与管理。前置:Y2 数据库导论;后续:Y4 Big Data Analytics。
- **核心主题**:
  - 事务(Transaction)与 ACID、并发控制与锁、隔离级别;
  - 索引原理(B+Tree)与查询优化(执行计划);
  - 规范化与反规范化、数据完整性;
  - NoSQL:文档型(MongoDB)、列族(HBase/Cassandra)、键值、图数据库;
  - 数据仓库与 ETL 入门;
  - 数据库安全、备份与恢复、性能调优。
- **现实应用**:DBA、后端开发、数据分析师;工作中写复杂 SQL、调慢查询、设计表结构、选型(MySQL vs NoSQL)全靠这门课。

### 5. Business Intelligence(商业智能)
- **定位**:把数据变成决策依据。前置:Y2 统计、数据库;后续:Y4 Big Data Analytics、机器学习。
- **核心主题**:
  - BI 全流程:**ETL(抽取-转换-加载)→ 数据仓库 → OLAP 多维分析 → 可视化仪表盘**;
  - 指标体系:KPI、北极星指标、转化漏斗;
  - 报表与仪表盘设计(Tableau / Power BI 类工具的逻辑);
  - 决策支持系统(DSS)与数据驱动决策;
  - 数据质量与数据治理入门。
- **现实应用**:BI 分析师/数据分析师/经营分析岗的日常工作;老板看的大屏、周报月报背后的取数-建模-可视化链路就是这门课。

### 6. Digitalization for Sustainability(数字化与可持续发展)
- **定位**:新兴交叉方向,讨论数字化技术如何服务(或伤害)可持续发展。选修性质偏管理。
- **核心主题**:ESG 概念、绿色 IT/绿色数据中心、数字产品碳足迹、数字化赋能的可持续商业模式、企业可持续发展报告中的数据。
- **现实应用**:ESG 咨询、企业可持续发展部门、绿色金融;大厂碳中和报告中"数字化碳管理平台"就是这类工作的产物。

### 7. Introduction to Financial Mathematics(金融数学导论)
- **定位**:给非金融专业打金融数学底子,衔接金融科技方向。前置:Y2 数量方法、金融学基础;后续:Y4 Finance and Markets、Computer-Based Trading、机器学习。
- **核心主题**:
  - 货币时间价值(TVM)、现值和终值、折现;
  - 利率与债券定价、到期收益率;
  - 风险与收益、均值-方差、投资组合入门;
  - 衍生品入门:期权、期货、远期的基本概念与定价直觉;
  - 复利、年金、分期付款的数学。
- **现实应用**:银行/证券/基金从业资格考试内容;金融科技(借贷利率模型、风控定价)、量化交易入门必学。

## 四、Year 3 选修课程

| 课程 | 一句话定位 | 现实应用方向 |
|---|---|---|
| Advanced OO Programming(高级面向对象编程) | 深入 Java:设计模式、泛型、集合框架、并发 | 后端开发(Spring 系) |
| Human-Centric Computing(人本计算) | 人机交互:可用性、用户体验、用户研究 | UX 设计师、产品经理 |
| Financial Management(财务管理) | 资本预算、资本结构、财务分析与决策 | 企业财务、投行/咨询 |
| Securities Markets(证券市场) | 股票债券市场结构与交易机制 | 证券、基金、金融科技 |

## 五、Year 2 基础课程(Y3 的前置,快速参考)

- **技术线**:Introduction to Programming in Java(Java 基础)、Introduction to Databases(SQL 基础)、Algorithmic Foundations and Problem Solving(算法与逻辑)、Artificial Intelligence In Business(AI 商业应用入门)。
- **数量线**:Introduction to Statistics(统计)、Quantitative Methods for Business(数量方法)、Foundations of Finance(金融学基础)。
- **商业线**:Introduction to Financial Accounting and Accountability、Foundations of Financial Accounting(会计)、Economic Principles for Business and Markets(经济学)、The Entrepreneurial Journey(创业思维)。

## 六、Year 4 前瞻(让学生看到"大三学的东西通向哪里")

- **核心**:Technologies for E-Commerce(电商技术)、Finance and Markets(金融与市场)、Big Data Analytics(大数据分析)。
- **选修亮点**:Machine Learning、Computer-Based Trading In Financial Markets、E-Business Models and Strategies、Software Engineering II、Mobile Computing、Computer Systems Security、Final Year Project(毕业设计)。
- 大三的数据库/BI/软件工程/金融数学,分别通向 Y4 的大数据、电商技术、金融科技、ML 方向。

## 七、职业方向 × 课程映射表

| 求职方向 | 最相关课程 | 常用工具 |
|---|---|---|
| 数据分析师 / BI 分析师 | 统计、数据库、高级数据库、商业智能、大数据分析 | SQL、Excel、Tableau、Power BI、Python |
| 后端 / 全栈开发 | Java 编程、算法、软件工程 I/II、高级 OO、高级数据库 | Java、Git、SQL、Spring |
| 产品经理 | 电商系统、人本计算、创业课、软件工程小组项目 | Jira、Figma、Axure |
| 电商运营 / 跨境电商 | 电商系统、电商模式与战略、营销类 | 数据分析平台、广告后台 |
| ERP / IT 咨询 | 数据库、电商系统、商业智能 | SAP 系、SQL |
| 金融科技 / 证券基金 | 金融学、金融数学、证券市场、金融与市场、机器学习 | Excel、Python、Wind/彭博类 |
| 数据科学 / 深造读研 | 统计、机器学习、大数据分析、FYP | Python、SQL、ML 框架 |

## 八、使用提示(给辅导模型)

1. 学生给课件时:先定位到上面对应的课程,再按 SKILL.md 的流程讲。
2. 课件内容与本知识库冲突时,**以课件为准**,并提醒学生核对 e-Bridge。
3. 学生问"这门课怎么学/考什么"时:结合课件高频内容 + 本库的"核心主题"给建议,注明推断部分。
4. 学生问职业发展时:用第七节映射表回答,结合其兴趣细化。
