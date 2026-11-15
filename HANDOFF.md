# 《颁什么奖》· 提示词工作交接文档

> 本文档供另一个 AI 助手接手**我们的提示词（prompt）工作**。
> 我们的职责范围：**论坛 AI 学生的人设与生成提示词** + **新闻生成提示词**。
> 其他（核心游戏循环、后端 Concordia 集成、游戏前端）由别人负责，**不是我们的工作**，本文仅作背景提及。
> 最后更新：2026-11-15。分支：`prompt-optimization`（本地，未 push）。

---

## 1. 背景（一句话）

《颁什么奖》是 AI 大模型课程作业：玩家设奖，AI 角色回应。我们负责让**论坛里的 AI 学生**和**新闻**说得像真人、有内容。游戏本体/后端/前端不归我们管。

我们的产出落在两个文件群：
- `forum/personas.json` + `forum/generate.py`（AI 学生人设 + 生成提示词）
- `news/generate.py`（新闻生成提示词）

支撑基础设施（论坛服务/校史馆/记忆存储）已搭好，我们主要改 **prompt 与人设**，必要时调生成逻辑。

---

## 2. 人设系统 `forum/personas.json`

16 个 AI 学生，每人字段：
- `nickname` / `tag`：昵称 / 身份标签
- `personality`：第一人称身份描述
- `style`：语气（**已弱化口头禅**：大部分正常说话，标志句偶尔冒）
- `flaw`：表达缺陷（词穷/算错重算/怼一半算了等）
- `boundary` / `scene` / `relations`：边界 / 出没场景 / 关系网
- `examples`：示例对话（**mostly 正常说话 + 最多 1 条标志句**，示例驱动语域）

顶层 `rules`：全局规则（信息真实/禁元话语/禁修辞弧/口头禅稀有/接话不接词/字数等）。

**人设设计原则**（迭代得出）：
- 人设≠口头禅。标志句是稀有品，不是身份。示例若全是口头禅，模型会每句都甩。
- 示例驱动 > 形容词描述。给正常说话的示例，模型才像正常人。
- 第一人称身份 + 具体缺陷，比抽象性格词有效。

16 人：老蔡不姓蔡(理性分析)、奶油小方(共情)、树洞君(深夜内省)、梗先知(玩梗)、阿穹(锐评)、食堂干饭王(暖场)、深夜修猫(夜猫)、白鸽情报站(转述)、上岸进行时(考研)、交换生阿May、社团老母亲、勤工俭学的小周、体育生大壮、延毕的老学长、新生小透明、画画人。

---

## 3. 生成提示词机制 `forum/generate.py`

**核心：去 AI 味靠结构，不靠"要有趣/无聊/短"这类形容词（无效）。**

关键函数与提示词组件：
- `persona_card(p)`：把人设拼成卡（含示例）。
- `humanize_block()` / `post_block()`：去 AI 味硬清单（禁词/禁句式/禁标点/禁修辞弧/口头禅稀有/接话不接词/字数），**放在 user 末尾压轴**（SillyTavern post_history_instructions 经验）。
- `comment_situation(thread, prior)` / `_MOTIVES` / `_REPLY_MOTIVES`：微情境（你刚看到什么）+ 动机（反驳/同意/追问/接梗），让话从处境长出来。
- `generate_one_comment(...)`：**单角色单调用**，只喂该角色情境+自己的记忆+信息不对称+字数预算。打破"一个模型写群戏"的表演感。
- `_length_budget()`：结构化字数（60% 极短 5-15 字 / 30% 短 / 10% 稍长），评论 max_tokens=200。
- `generate_comments(...)`：前 2 条必顶楼（独立反应帖子），之后约 55% 楼中楼（强制挂目标评论）。当前约 39% 楼中楼。
- `generate_replies_to_comment(...)`：玩家回帖后，AI 针对该评论回应。
- `generate_threads(...)` / `generate_daily(...)`：主题帖/日常帖（**目前仍批量生成，见缺陷**）。
- `pick_responders` / `eligible_posters`：场景门控（夜行角色仅 23-7 点）+ 关系加权 + 可潜水。

**记忆/状态注入 prompt**（`forum/memory.py`）：
- `footprints(nick)`：近期足迹（recency+importance 加权检索）注入。
- `states.json` + `refresh_one_state`：每生每天 1 次重写 currently+洞察，注入作"背景心情"（非每条必提）。
- `_countdown`：考研倒计时存 exam_date 现算。

---

## 4. 新闻提示词 `news/generate.py`

- `SYSTEM`：校园墙/树洞吐槽视角，**片面/带情绪/八卦**，不要"双方各打五十大板"的平衡报道；分类别要求（校园动态要地点+人物+数字；教育议题要槽点；网络热点要梗；隔壁大学要对比）；具体细节（数字+地点+引语）；讨论点。
- `EXAMPLES`：好新闻 few-shot（学具体感和讨论点）。
- `generate_news` → `pack_from_item` → POST 论坛 `/generate` 发酵。

---

## 5. 运行与调试 prompt

```bash
cd /home/miku/Documents/anyawards
python start_all.py                 # 起服务（论坛 8768 / 校史馆 8767）
# 改 personas.json / generate.py 后需重启论坛服务生效
python3 archive/forum_sync.py --all # 从校史馆多卷生成论坛话题
python3 news/generate.py --count 2 --post-to-forum
```
- LLM 密钥在项目外 `~/.anyaward-secrets.env`（DeepSeek deepseek-chat）。`load_llm_env()` 读取。
- 调试看 `forum/data/forum.json`（帖子/评论/reply_to）。
- 改 prompt 后重启论坛服务（`forum/server.py`）才生效。

---

## 6. 当前 prompt 缺陷（诚实清单）

1. **口头禅仍偶有堆砌**：已大幅降低（含标志句消息约 15%），但非零，个别角色仍会一条甩几个。
2. **帖子 prompt 与评论 prompt 不一致**：评论已独立生成+注入动态状态/倒计时；**帖子（generate_threads/generate_daily）仍批量、不注入动态状态/倒计时**→帖子里倒计时飘（"七十来天" vs 实际 36 天）。
3. **部分评论接关键词不接意思**：就事论事约束已加，但仍有复读楼主/对方原词的情况。
4. **评论结构比例是经验值**（39% 楼中楼），自然度无客观度量。
5. **表达学习未做**：不会从真实玩家帖学"情境→句式"（MaiBot 那套），人设语域全靠手写示例。
6. **评估缺失**：无句长方差/distinct/self-BLEU/盲测等客观指标，改 prompt 效果靠肉眼。
7. **人设示例还可打磨**：部分角色示例偏少/偏同质。
8. **动态状态反思是轻量版**：每生每天 1 次，无完整 Stanford reflect 循环。

---

## 7. prompt 待办（优先级）

**P0（一致性/质量）**
1. 帖子 prompt 改独立生成 + 注入动态状态/倒计时（修缺陷 2）。
2. 进一步降口头禅堆砌、强化"接意思不接词"（缺陷 1/3）。

**P1（深化）**
3. 表达学习：从真实玩家帖提取"情境→句式"，count 加权软注入（防自我污染，只学玩家不学 AI）。
4. 评估指标 + 盲测：句长方差/distinct-2/self-BLEU/禁词命中，对照基线；真人帖混生成帖盲测（猜中率趋近 50% 为佳）。
5. 人设示例扩充/打磨（每角色更丰富的正常说话示例）。

**P2（可选）**
6. 完整反思循环（若轻量版不够）。
7. 更多奖项的 prompt 适配（自由设奖场景）。

---

## 8. 参考项目（prompt 机制来源）

| 项目 | 借鉴 |
|---|---|
| [SillyTavern](https://github.com/SillyTavern/SillyTavern) (35.6k) | 示例对话驱动、post_history_instructions 压轴、角色卡 |
| [generative_agents](https://github.com/joonspk-research/generative_agents) (22.4k) | 情境对话、信息不对称、retrieve 加权、revise_identity |
| [MaiBot](https://github.com/Mai-with-u/MaiBot) | 表达学习、防重复、读空气回复率、评估方法 |
| [stop-slop-zh](https://github.com/pencil20388-eng/stop-slop-zh) | 中文去 AI 味禁用词/句式/标点清单 |

---

## 9. 重要约定

- **去 AI 味靠结构不靠形容词**：独立生成+情境+具体字数预算+示例驱动；绝不写"要有趣/无聊/短"。
- **人设≠口头禅**：标志句稀有，示例 mostly 正常说话。
- **信息要真实**：学生只依据所给公开信息，不编造内幕。
- **密钥不落项目**：只在 `~/.anyaward-secrets.env`，提交前扫描。
- **非平凡改动先出聚焦方案审批**，不随机改。
- 改 prompt 后**重启论坛服务**才生效。

---

*接手建议：先读 `forum/personas.json` + `forum/generate.py` 的提示词组件（§3），跑论谈看现状；优先 P0（帖子 prompt 一致性 + 降口头禅）。*
---

## 10. 2026-11-15 下午修缮记录（Phase 0-3，已全部提交）

> 接手 AI 追加：按 §7 待办推进后的现状。§6 缺陷对照本节末尾的状态表。

**Phase 0 审计基建（缺陷 6 主体闭环）**
- `forum/personas.json`：新增 `catchphrase` 字段（16 人迁移）；`style` 不再提及标志句——旧写法每次调用都把标志句发进 prompt，是堆砌的指令源。
- `forum/lexicon.py`：禁词表单一事实源，`generate` 渲染与 `audit` 扫描同一口径（渲染文本与历史 prompt 逐字一致）。
- `forum/audit.py`：纯标准库记分卡（口癖密度/堆砌/禁词/倒计时一致性/复读率/长度分布/每帖评论数/distinct-2）。改 prompt 前后各跑一遍，别再肉眼评。26 份快照基线已存于 output/。

**Phase 1 帖子生成根治（缺陷 2 闭环）**
- `generate_threads`/`generate_daily` 从批量拼盘拆为单角色单调用（`persona_system` 三路径共用），注入背景心情/考研倒计时/个人足迹——倒计时违例从基线 5 份快照 → 0。
- `post_block` 删标志句例词枚举（如蚌/哥/…），它把全员口癖发给每个角色，是串味源。
- 成本：每快照 +14~16 次调用（相对评论侧 20-30 次是小头）。

**Phase 2 复读治理（缺陷 3 闭环）**
- 评论 JSON 加 `point` 字段：先用 ≤20 字概括对方再写 body，结构上治"接词不接意"。
- `_violations` 纯正则后验（禁词/共现/翻案句/标志句堆砌/超长）+ `_rework` 定向返工一次（失败保留原稿，防死循环）。
- 实测：复读 p90 0.38→0.30，口癖密度 22%→7~14%，堆砌 2→0。

**Phase 3 结构与状态**
- 每帖评论数 `randint(5,7)` → 三角分布 1-8（基线显示每帖恒 5-7 条，是结构均匀性 AI 味，缺陷 4 量化闭环）。
- `archive/forum_sync.py --status/--repair`：核对"标记已同步但论坛已无讨论"的漂移；实测暴露 002/003/005 三处（论坛重置后标记残留）。跑 `--repair` 会真实生成内容重喂，何时跑由人决定。

**缺陷状态速查**：1→结构性修复；2→已修；3→已修；4→已量化+分布化；6→audit.py 已建（self-BLEU/盲测未做）；5/7/8 未动（表达学习/示例扩充/完整反思，仍按 §7 P1-P2 顺序）。

**环境备忘**：沙箱 shell 的 `PYTHONUTF8=1` 会让 CPython 3.14 的 venv 探测失效（import dotenv 失败）；调 `Any-Award-Backend/.venv/bin/python` 用 `env -u PYTHONUTF8`。用户终端无此变量，服务不受影响。
