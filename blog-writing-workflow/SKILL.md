---
name: blog-writing-workflow
description: Build source-grounded blog posts from the project's information skills with category-based source routing. Use when the user wants a blog writing workflow, wants to turn an idea/topic into an article, asks an agent to discover current topics automatically, or needs a reusable research-to-draft pipeline across categories such as AI agents, Web3, economy, product, career, technology, investment, culture, education, social observation, travel, lifestyle, and case studies.
---

# Blog Writing Workflow

Use this skill to turn scattered information sources into a reusable blog production flow. It supports two entry points:

1. **User topic mode**: start from a user idea or topic, classify the writing theme, collect targeted evidence, choose an angle, then draft.
2. **Autonomous discovery mode**: select a writing category, collect recent signals first, score candidate topics, then draft.

## Quick Start

Run the workbench script from this skill directory:

```bash
python3 scripts/blog_workflow.py --topic "AI agent browser" --days 14
python3 scripts/blog_workflow.py --topic "如何建立学习系统" --category "教育与学习系统" --days 30
python3 scripts/blog_workflow.py --auto --category "Web3相关" --days 3
python3 scripts/blog_workflow.py --topic "用 Agent 自动整理资料" --category "技术分享" --article-type tutorial
python3 scripts/blog_workflow.py --topic "短篇新闻解读" --article-type news-analysis --min-length 1000 --max-length 1600
python3 scripts/blog_workflow.py --validate-run runs/<run-id>
python3 scripts/blog_workflow.py --validate-run runs/<run-id> --strict-delivery
python3 scripts/blog_workflow.py --list-categories
```

The script creates a run folder under `runs/` with:

- `sources.json`: normalized evidence items using the shared `EvidenceItem` shape.
- `scorecard.json`: ranked topic or angle candidates.
- `metadata.json`: category, enabled sources, skipped sources, deep-source suggestions, and errors.
- `brief.md`: the editor-ready research brief.
- `writing_packet.json`: the category-profile × article-type handoff for the orchestrating agent.
- `article.md`: the agent-written article, produced during the handoff and validated with `--validate-run`.
- `quality/`: local analyze, SEO, fact-check, writing-compliance, and humanizer reports.

## Category Routing

The source matrix lives in `references/topic-sources.json`. Read `references/source-routing.md` when changing categories or deciding which source families should support a theme. Read `references/claude-blog-integration.md` before changing final article generation.

The CLI supports:

- `--category`: explicitly choose one of the configured writing themes.
- `--writer`: retained for compatibility; the only mode is `agent-packet`, the typed Agent handoff (also the default).
- `--article-type`: explicitly select one of 12 article types; otherwise infer it from the topic and selected angle.
- `--min-length` and `--max-length`: jointly override the selected article type's effective Chinese length range.
- `--validate-run`: validate an Agent-written `article.md` in an existing run directory.
- `--language`: final article language, default `zh-CN`.
- `--strict-delivery`: with `--validate-run`, run the heavier delivery scripts after `article.md` exists.
- automatic category inference: if `--category` is omitted, infer from `--topic`; if `--auto` has no category, use the default category.
- graceful degradation: missing credentials, missing CLI tools, manual-only sources, and failed requests are recorded in `metadata.json` and `brief.md` instead of aborting the workflow.

Configured writing themes:

- AI与智能体相关
- Web3相关
- 经济主题
- 个人成长与认知
- 产品思维
- 互联网与科技趋势
- 投资相关
- 职业发展
- 商业与创业
- 技术分享
- 哲学与思辨
- 社会观察
- 生活方式
- 审美与文化
- 旅行与城市
- 教育与学习系统
- 案例分析

## Workflow

### 1. Route The Request

- If the user provides a topic, run topic mode with `--topic`.
- If the user asks the agent to find a topic, run auto mode with `--auto`; prefer passing `--category` when the desired writing theme is known.
- If the category is ambiguous, use the script's inferred category but check `category_confidence` in `metadata.json`.
- If the article needs source depth beyond automatic collection, use the `建议深挖源` section in `brief.md`.

### 2. Build A Research Brief

Use `scripts/blog_workflow.py` as the default aggregator. It automatically runs available no-credential or credential-detected sources and suggests manual/deep sources.

Automatic or credential-detected sources include:

- `hackernews`
- `arxiv`
- `ai-newsletters`
- `ai-products`
- `techmeme`
- `producthunt-rss`
- `github-trending`
- `global-search`, `zhihu-search`, `hot-list` when `ZHIHU_ACCESS_SECRET` is set
- `producthunt-api` when `PRODUCTHUNT_ACCESS_TOKEN` is set, or when `PRODUCTHUNT_API_KEY` and `PRODUCTHUNT_API_SECRET` are set for client-credentials token exchange
- `blockbeats-skill`, `blockbeats-market`, `blockbeats-macro` when `BLOCKBEATS_API_KEY` is set
- `folo` when `npx` is available and either `folocli login` has completed or `FOLO_TOKEN` is set

Manual or deep sources include:

- `last30days`
- `twitter-cli`
- `blogwatcher`
- `xiaohongshu`
- `youtube-content`
- `watch`
- `wechat-article-extractor`
- `mptext-wechat-article-fetcher`
- `read-arxiv-paper`
- `research`

### 3. Select The Angle

Choose the angle with the strongest combination of:

- Clear recent trigger.
- Multiple independent evidence items.
- Practical stakes for a specific reader.
- A tension, misconception, market variable, or decision the article can resolve.
- Enough source quality to support claims without speculation.

Do not choose a topic only because it has a high score. Prefer a slightly smaller topic with a clearer reader payoff.

### 4. Build A Typed Agent Writing Packet

For finished articles, the script prepares a typed Agent handoff (`--writer agent-packet`, the default). It combines two independent dimensions:

- **Category profile**: one of the 17 writing themes. It controls audience, voice, evidence requirements, analytical moves, prohibited moves, action style, and risk disclosure.
- **Article type**: one of `how-to-guide`, `listicle`, `case-study`, `comparison`, `pillar-page`, `product-review`, `thought-leadership`, `roundup`, `tutorial`, `news-analysis`, `data-research`, or `faq-knowledge`. It controls structure, required elements, visuals, FAQ style, and conclusion style.

The category profiles and article-type requirements live in `references/writing-profiles.json`. Article type precedence is explicit `--article-type`, automatic intent inference, then `thought-leadership` fallback.

Each article type also defines a Chinese effective-length range. The defaults are:

| Article type | Minimum | Recommended maximum |
| --- | ---: | ---: |
| `news-analysis` | 1,200 | 2,000 |
| `faq-knowledge` | 1,800 | 3,000 |
| `listicle`, `product-review`, `roundup` | 2,000 | 3,200 |
| `case-study`, `comparison` | 2,200 | 3,500 |
| `thought-leadership` | 2,200 | 3,800 |
| `how-to-guide` | 2,500 | 4,000 |
| `tutorial`, `data-research` | 2,800 | 4,500 |
| `pillar-page` | 3,500 | 6,000 |

Effective length counts each Chinese character, English word, or number sequence as one unit. It excludes frontmatter, code, URLs, comments, placeholders, and the source-record section. The minimum is a non-blocking quality requirement; the maximum is guidance only.

After the script creates `writing_packet.json`, the orchestrating Agent must:

1. Read `writing_packet.json`, `brief.md`, `sources.json`, and the referenced claude-blog template in full.
2. Write one evidence-backed thesis and produce an initial `article.md` grounded in the collected evidence.
3. Read the `humanizer.skill_path` file in full and apply `humanizer-zh` to `article.md` before validation.
4. Preserve frontmatter, links, verified numbers, dates, quotations, code, names, and evidence strength exactly while humanizing. Never invent first-person experience, tests, interviews, or emotions.
5. Write `quality/humanizer-review.md` with `状态: completed`, a short list of major edits, and the required fact-preservation checklist. Do not add a subjective numeric score.
6. Treat the category profile and evidence truth as higher priority than template SEO, length, statistic, or stylistic requests. Never pad an article with repetition, filler, or unsupported material to reach the minimum.
7. Run `python3 scripts/blog_workflow.py --validate-run <run-dir>`. Length is counted from the final, humanized `article.md`; a short article is reported as `needs_work` without blocking normal delivery.

Missing category evidence, structure, or humanizer review is report-only in normal validation. It appears in `quality/writing-compliance.md` or `quality/humanizer-check.md` with `needs_work` and does not make validation exit non-zero.

### 5. Quality Reports And Delivery

The writer must not fabricate statistics. If the collected evidence does not contain a verified number, write it as a source signal with date, source, title, and URL instead of turning it into a statistic.

`--validate-run` populates the `quality/` folder:

- `analyze.json`: output from `claude-blog/scripts/analyze_blog.py` when available.
- `writing-compliance.md`: category and article-type compliance report for Agent-written articles.
- `humanizer-review.md`: Agent-authored record of the required `humanizer-zh` editing pass, major changes, and fact-preservation checklist.
- `humanizer-check.md`: local heuristic scan for common AI-writing patterns and validation of the review record.

Use `--strict-delivery` with `--validate-run` when you want the heavier local delivery scripts to run. This tries `generate_hero.py`, `blog_render.py`, and `blog_preflight.py` from `/Users/deepwisdom/project/information/claude-blog/scripts`. If a gate blocks, the workflow preserves artifacts, records the block in `metadata.json`, and exits non-zero.

Use the brief to write a finished article, not a link digest. Every factual claim that depends on current or external information should be supported by an inline Markdown link. Separate what happened, why it matters, and what the reader should do next.

Use `references/article-playbook.md` when the article needs stronger framing, evidence thresholds, voice, or quality checks.

## Multi-Agent Pattern

For larger pieces, split work across agents:

- **Scout agents**: one per source family, each returns 5-10 evidence items with links and a short relevance note.
- **Editor agent**: merges evidence, selects the angle, and writes the brief.
- **Skeptic agent**: checks unsupported claims, stale dates, duplicated evidence, and missing counterarguments.
- **Writer agent**: produces the final article from the approved brief.

Keep the brief as the shared contract between agents.
