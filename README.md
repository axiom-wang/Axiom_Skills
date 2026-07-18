# Axiom_Skills

个人维护的 AI Agent Skills 集合，面向**Codex**,**Cursor** 与 **Claude Code**。

每个 skill 是一个独立目录，核心文件是 `SKILL.md`。Agent 会按描述自动匹配，或在你显式引用时加载。

---

## 目录

| Skill | 一句话说明 |
| --- | --- |
| [personal-blog-writing-coach](./personal-blog-writing-coach/) | 苏格拉底式采访 + 叙事结构，写中文第一人称个人博客 |
| [blog-writing-workflow](./blog-writing-workflow/) | 选题 → 证据采集 → 角度评分 → 写作包 → 校验的博客流水线 |
| [refine-prompt](./refine-prompt/) | 把模糊需求改写成可执行的 Agent 实现提示词 |

---

## 快速安装

### 方式 A：整库克隆后拷贝（推荐）

```bash
git clone https://github.com/2485359996/Axiom_Skills.git
cd Axiom_Skills
```

按你使用的工具，把需要的 skill 目录拷到对应位置：

| 工具 | 个人全局（所有项目可用） | 项目内（仅当前仓库） |
| --- | --- | --- |
| **Cursor** | `~/.cursor/skills/<skill-name>/` | `.cursor/skills/<skill-name>/` 或 `.agents/skills/<skill-name>/` |
| **Claude Code** | `~/.claude/skills/<skill-name>/` | `.claude/skills/<skill-name>/` |

Windows PowerShell 示例（安装全部三个到 Cursor 全局）：

```powershell
$src = "D:\path\to\Axiom_Skills"
$dst = "$env:USERPROFILE\.cursor\skills"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
foreach ($s in @("personal-blog-writing-coach", "blog-writing-workflow", "refine-prompt")) {
  Copy-Item -Recurse -Force "$src\$s" "$dst\$s"
}
```

macOS / Linux 示例（安装全部三个到 Claude Code 全局）：

```bash
SRC="/path/to/Axiom_Skills"
DST="$HOME/.claude/skills"
mkdir -p "$DST"
for s in personal-blog-writing-coach blog-writing-workflow refine-prompt; do
  cp -R "$SRC/$s" "$DST/$s"
done
```

只装某一个时，把循环里的名字换成对应目录即可。

### 方式 B：稀疏检出单个 skill

```bash
git clone --filter=blob:none --sparse https://github.com/2485359996/Axiom_Skills.git
cd Axiom_Skills
git sparse-checkout set personal-blog-writing-coach
# 然后按方式 A 拷到 skills 目录
```

### 安装后如何使用

1. **重启或新开 Agent 会话**，确保技能被重新扫描。
2. 在对话里直接描述任务，或显式引用：
   - `/personal-blog-writing-coach`
   - `/blog-writing-workflow`
   - `/refine-prompt`
3. 也可说自然语言，例如：「用个人博客写作教练帮我挖素材」。

---

## Skills 详情

### 1. personal-blog-writing-coach

**做什么**

把真实经历整理成 2000–5000 字的中文第一人称非虚构文章。默认先采访、挖细节，再给结构，最后成稿；不会一上来空写成功学文章。

**适合**

- 个人经历 / 项目故事
- 职业成长与求职复盘
- 产品实践与 AI 探索
- 面试、实习、offer、失败与选择

**目录结构**

```text
personal-blog-writing-coach/
├── SKILL.md
├── agents/openai.yaml
└── references/style-guide.md
```

**依赖**

无额外运行时依赖。成稿前会读取 `references/style-guide.md`。

---

### 2. blog-writing-workflow

**做什么**

可复用的博客生产流水线：按主题路由信息源、收集证据、打分选题、生成写作包，再由 Agent 写稿并本地校验。

**两种入口**

1. **指定选题**：你给 topic，再采集与成稿  
2. **自动发现**：按品类扫近期信号，再选题

**快速试跑**

```bash
cd blog-writing-workflow
python scripts/blog_workflow.py --list-categories
python scripts/blog_workflow.py --topic "AI agent browser" --days 14
```

**目录结构**

```text
blog-writing-workflow/
├── SKILL.md
├── scripts/blog_workflow.py
├── references/          # 品类、信源、写作画像等
├── tests/
└── runs/                # 运行产物（默认不入库）
```

**依赖说明**

- 需要 **Python 3**
- 部分信源需要额外 CLI / API Key（如 Product Hunt、BlockBeats、Folo 等）；缺凭证时会降级并写进 `metadata.json`，不会直接中断
- 完整交付链路可能依赖外部的 `claude-blog` 脚本与 `humanizer-zh` 等配套 skill；本地没有时，校验会标记 `needs_work`，基础 research brief 仍可生成

---

### 3. refine-prompt

**做什么**

检查当前仓库后，把模糊的产品 / UI / 后端 / 全栈想法，改写成简洁、可执行的 Agent 实现提示词。需求太糊时会先苏格拉底式提问，而不是瞎猜。

**适合**

- 「帮我优化这个提示词」
- 「不知道怎么描述这个需求」
- 「把这个想法变成 agent 能执行的 prompt」

**目录结构**

```text
refine-prompt/
└── SKILL.md
```

**依赖**

无脚本依赖。涉及前端设计时，会建议参考你环境里已有的 design skills（如 `frontend-design`、`impeccable`），那些不在本仓库内。

**注意**

该 skill 默认**只产出优化后的提示词**，不直接改代码、不写文件。

---

## 仓库约定

- 一个 skill = 一个顶层目录 + 必需的 `SKILL.md`
- 不要把个人运行产物（如 `blog-writing-workflow/runs/*`）提交上来
- 欢迎按同样结构继续往这个仓库加新 skill

## License

未单独声明前，默认仅供学习与个人使用；若你二次分发，请保留原作者署名与本说明。
