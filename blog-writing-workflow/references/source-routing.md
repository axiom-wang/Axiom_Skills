# Source Routing

Use this reference when updating source routing, reading `brief.md`, or manually expanding a run beyond automatic collection.

## Configuration

The source matrix is defined in `topic-sources.json`.

- `sources`: source registry with source id, display name, kind, collector, credential/CLI requirements, and description.
- `categories`: writing themes with keywords, query expansions, primary sources, secondary sources, and deep sources.

Source kinds:

- `auto`: no credential required; the script should try it automatically.
- `credentialed`: run only when required env vars and CLI tools are available.
- `manual`: requires an external URL, login flow, MCP service, or human-selected target.
- `deep`: useful after the first brief identifies a narrower target.
- `helper`: reserved for legacy configs only. The default final writer is configured by CLI, not by the source matrix.

## Trigger Modes

| Mode | Command | Behavior |
| --- | --- | --- |
| User topic | `--topic "..."` | Infer category unless `--category` is provided, then collect category-specific evidence. |
| Auto discovery | `--auto --category "..."` | Use the category source matrix to discover candidate topics. |
| Category inventory | `--list-categories` | Print all categories with primary, secondary, and deep sources. |

## Source Selection Rules

- Start from the configured category; do not hand-pick unrelated sources unless the first run returns thin evidence.
- Run `primary` and `secondary` sources when they are `auto` or credential requirements are satisfied.
- Record missing credentials and missing CLI tools as skipped sources.
- Put `manual` and `deep` sources into the brief as follow-up recommendations.
- Do not route final article writing through source helpers. The final writer is `--writer agent-packet` (the default), which prepares the typed Agent handoff.
- Use fallback public tech sources only when a category has no enabled automatic source or returns no evidence.
- Treat RSS summaries as leads, not proof. Follow the linked source before making a strong claim.

## Topic Matrix

| Theme | Primary sources | Secondary/deep sources |
| --- | --- | --- |
| AI与智能体相关 | AI newsletters, AI products, HN, arXiv, Techmeme | Product Hunt, GitHub Trending, YouTube, last30days, read-arxiv-paper, X, Blogwatcher |
| Web3相关 | BlockBeats, last30days, X | HN, Product Hunt, Techmeme, Polymarket, Hyperliquid/on-chain |
| 经济主题 | Techmeme, BlockBeats macro, global-search, hot-list | last30days, Folo, Blogwatcher, X, Zhihu |
| 个人成长与认知 | Zhihu, global-search, Xiaohongshu, YouTube | Folo, Blogwatcher, last30days |
| 产品思维 | Product Hunt, AI products, HN, Zhihu | YouTube, last30days, Xiaohongshu, Product Hunt comments, X |
| 互联网与科技趋势 | HN, Techmeme, GitHub Trending, AI newsletters | global-search, hot-list, Folo, Blogwatcher, last30days, X |
| 投资相关 | BlockBeats market/macro, Techmeme, global-search | last30days, Zhihu, Folo, X, Polymarket |
| 职业发展 | Zhihu, global-search, HN, YouTube | Xiaohongshu, last30days, Folo |
| 商业与创业 | Product Hunt, Techmeme, HN, global-search | AI products, Zhihu, Folo, Product Hunt API, X, Blogwatcher |
| 技术分享 | HN, GitHub Trending, arXiv, YouTube | Blogwatcher, Folo, global-search, read-arxiv-paper, watch |
| 哲学与思辨 | global-search, Zhihu, YouTube, Folo | Blogwatcher, last30days, WeChat, MPText |
| 社会观察 | hot-list, global-search, Zhihu, Xiaohongshu | last30days, Folo, YouTube, WeChat, X |
| 生活方式 | Xiaohongshu, Zhihu, global-search, YouTube | Folo, last30days, WeChat |
| 审美与文化 | Xiaohongshu, YouTube, global-search, Zhihu | Folo, Blogwatcher, WeChat, MPText |
| 旅行与城市 | Xiaohongshu, global-search, Zhihu, YouTube | hot-list, Folo, last30days, WeChat |
| 教育与学习系统 | arXiv, Zhihu, global-search, YouTube | HN, Folo, Blogwatcher, read-arxiv-paper, last30days |
| 案例分析 | global-search, HN, Techmeme, Product Hunt | Zhihu, last30days, Folo, Blogwatcher, YouTube, WeChat, MPText |

## Query Expansion

For user topic mode, build variants from:

- Literal topic phrase.
- Category query expansions from `topic-sources.json`.
- Synonyms and product names.
- Problem framing: why, migration, comparison, risk, workflow.
- Audience framing: developers, creators, teams, researchers, students.
- Chinese/English variants when relevant.

For auto discovery mode, cluster candidates by repeated entities, product names, or problems. Prefer topics appearing across more than one source family.

## Evidence Labels

Assign each evidence item one or more labels:

- `trigger`: explains why the topic matters now.
- `primary`: direct source, paper, product page, official post, repo, or API data.
- `community`: comments, forum posts, discussions, social posts.
- `analysis`: newsletter, media article, blog post, analyst write-up.
- `counterpoint`: caveat, criticism, failed adoption, or conflicting evidence.
- `actionable`: contains instructions, examples, benchmark, checklist, or decision criteria.

The final article should include at least one `trigger`, one `primary` when available, and one `counterpoint` for non-trivial topics.

## Final Writer Routing

The writing stage is separate from source routing:

- Default: `--writer agent-packet` creates `writing_packet.json` for the orchestrating agent; the agent then writes `article.md`.
- Validation: `--validate-run <run-dir>` validates the agent-written `article.md` and populates `quality/` reports.
- Strict delivery: `--strict-delivery` (with `--validate-run`) runs the local claude-blog scripts from `/Users/deepwisdom/project/information/claude-blog/scripts` and exits non-zero if a delivery gate blocks.

The source matrix should never include `personal-blog-writing-coach` as a default helper for this workflow. The agent-packet handoff plus the claude-blog templates own the final article structure and quality checks.

## Credential-Aware Fallbacks

- If `ZHIHU_ACCESS_SECRET` is missing, skip `global-search`, `zhihu-search`, and `hot-list`.
- If `PRODUCTHUNT_ACCESS_TOKEN` is missing, the script can also use `PRODUCTHUNT_API_KEY` + `PRODUCTHUNT_API_SECRET` to request a client-level token. If neither credential path is available, keep using Product Hunt RSS and skip Product Hunt API/comment follow-up.
- If `BLOCKBEATS_API_KEY` is missing, skip BlockBeats crypto, market, and macro endpoints.
- If Folo is not logged in and `FOLO_TOKEN` is missing, skip Folo. Prefer `npx --yes folocli@latest login` so the CLI stores a local session.
- If X/Twitter credentials are unavailable, do not block the workflow; recommend `twitter-cli` or `last30days` as a deep source.
- If a source fails, preserve the error in the run metadata and continue with remaining sources.

## Manual Multi-Agent Brief Contract

Each scout agent should return:

```markdown
## Source Family
- Scope:
- Queries used:
- Top evidence:
  - [Title](URL) - date - why it matters - label(s)
- Best angle:
- Missing evidence or caveats:
```

The editor agent should merge scout outputs into `brief.md` and remove duplicates before drafting.
