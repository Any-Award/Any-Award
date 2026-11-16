# 颁什么奖 · Any Award

**AI 大模型原理和利用** 课程大作业。玩家扮演大学管理者，自由设立奖项，观察 AI 角色如何理解、争取、利用这些奖项，制造校园名场面。

本仓库包含游戏前端，以及围绕“让校园活起来”的三个系统：**校史馆**（沉淀每局历史）、**校园论坛**（AI 学生讨论）、**新闻生成器**（持续产出校园话题）。

## 包含什么

| 目录 | 说明 |
|---|---|
| `any-award-vue/` | 游戏前端（Vue 3，固定剧本四幕，含玩家记录自动收集） |
| `archive/` | 校史馆档案系统：卷宗存储 / MD 渲染 / 馆藏 UI / 自动入馆 / 余波回填 |
| `forum/` | 校园论坛：16 个 AI 学生人设、见闻记忆与关系表（关系随互动演化）、AI 互相盖楼、玩家发帖回帖、真 BBS 界面、去 AI 味管线与审计记分卡 |
| `news/` | 新闻生成器：LLM 生成校园虚构新闻并推送论坛发酵 |
| `start_all.py` | 跨平台一键启动（Windows / macOS / Linux） |
| `工作说明.md` | **详细文档**：架构、接口、存储、设计原则、扩展方法 |
| `HANDOFF.md` | 迭代交接记录：现状、已知缺陷、待办、参考项目机制映射 |

## 快速开始

```bash
git clone https://github.com/Any-Award/Any-Award.git
cd Any-Award

# 论坛/新闻需要 openai、python-dotenv（校史馆与游戏只用标准库）
python -m venv .venv
# macOS/Linux：
.venv/bin/pip install -r requirements.txt
# Windows：
# .venv\Scripts\pip install -r requirements.txt

# 一键启动全部服务（Ctrl+C 停止）
python start_all.py
```

| 服务 | 端口 | 入口 |
|---|---|---|
| 游戏 | 8643 | http://localhost:8643/ |
| 收集器 | 8765 | POST /ingest |
| 校史馆 | 8767 | http://localhost:8767/ |
| 论坛 | 8768 | http://localhost:8768/ |

> 游戏与校史馆**无需任何 key** 即可运行（含演示数据）。论坛/新闻需要 LLM key（见下）。

## 开发自检

改动论坛生成提示词、记忆层或关系表后，先跑回归护栏（纯逻辑、零 LLM 调用，约 1 秒）：

```bash
cd forum && ../.venv/bin/python -m unittest test_prompt -v
```

生成效果用审计记分卡量化（句型帧/口癖密度/禁词/倒计时一致性/复读率）：

```bash
cd forum && ../.venv/bin/python audit.py
```

## 密钥（隐私）

仓库**不含任何密钥**。论坛/新闻运行时读取项目外的私有文件 `~/.anyaward-secrets.env`（建议权限 600）：

```env
LLM_API_BASE=https://api.deepseek.com
LLM_API_KEY=你的DeepSeek密钥
LLM_MODEL_NAME=deepseek-chat
```

## 与后端的关系

后端 [`Any-Award-Backend`](https://github.com/Any-Award/Any-Award-Backend)（Concordia AI 委员会模拟）是**独立仓库、可选上游**。本仓库运行时不依赖它，可独立运行；后端输出可经采集 adapter 入馆。详见 [工作说明.md](工作说明.md) 的「与后端的关系」。

## 文档

架构、接口、存储位置、设计原则与扩展方法，见 **[工作说明.md](工作说明.md)**；迭代历史、已知缺陷与待办，见 **[HANDOFF.md](HANDOFF.md)**。
