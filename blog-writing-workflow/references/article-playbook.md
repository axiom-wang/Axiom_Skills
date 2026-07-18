# Article Playbook

Use this reference after `brief.md` exists and the next step is to write a polished article.

## Article Types

The writing model has two independent dimensions. The category selects the writing profile; the article type selects the structure. The machine-readable source of truth is `writing-profiles.json`.

Available types are `how-to-guide`, `listicle`, `case-study`, `comparison`, `pillar-page`, `product-review`, `thought-leadership`, `roundup`, `tutorial`, `news-analysis`, `data-research`, and `faq-knowledge`.

Explicit `--article-type` wins. Otherwise infer from topic and angle, falling back to `thought-leadership`. Always load the matching file from `claude-blog/skills/blog/templates/`, but category rules and evidence truth override template SEO or statistic requests.

## Writing Rules

- Write one thesis sentence before drafting. If no thesis emerges, collect more evidence.
- Open with the reader's decision or surprise, not with "recently".
- Use exact dates for current events.
- Attribute claims with inline links at first mention.
- Avoid laundering weak evidence through confident language. Use "suggests", "early signal", or "one example" when evidence is thin.
- Turn evidence into judgment. Do not summarize every source in order.
- Include a "what to do next" section unless the piece is purely analytical.
- After the initial draft, apply `humanizer-zh` before fact-checking. Preserve citations, verified facts, dates, code, and epistemic boundaries exactly; do not invent a personal voice through fabricated experience.
- Validate the final humanized article against its type-specific effective-length range. Treat the minimum as a non-blocking revision signal and the recommended maximum as guidance; never add unsupported material merely to reach a number.

## Headline Patterns

- `X is becoming Y: what builders should watch`
- `The quiet shift from X to Y`
- `Why X matters less than the workflow around it`
- `A practical map of X after Y`
- `What X tells us about the next phase of Y`

## Quality Checklist

- The first three paragraphs state the topic, the change, and the stakes.
- Every section advances the thesis.
- The article contains at least three source-linked facts.
- At least one paragraph addresses limitations or counterevidence.
- The conclusion gives a concrete next step, question, or watchlist.
- The article can stand alone if links are not opened.

## Evidence Requirements By Theme

Use the theme from `metadata.json` to decide the minimum evidence standard before publishing:

| Theme type | Minimum evidence |
| --- | --- |
| AI/tech/research | One primary technical source or paper, one community/product signal, and one caveat about limits or adoption. |
| Web3/investment/economy | One market/data source, one news or policy source, and one risk/counter-signal. Do not turn this into financial advice. |
| Product/business/startup | One product/company source, one user/community signal, and one competitor or market-context source. |
| Career/growth/learning | One community discussion source, one practical example, and one first-person or interview-based detail when available. |
| Society/lifestyle/culture/travel | One Chinese social/context source when available, one broader analysis source, and one example that grounds the observation. |
| Case analysis | One primary case artifact, one external interpretation, and one measurable outcome or failure mode. |

If automatic sources are thin, use the `建议深挖源` section in `brief.md` before drafting the final article.

## Final article.md Requirements

`article.md` is the canonical agent-written draft. Write it directly from `writing_packet.json`, `brief.md`, and `sources.json`.

Minimum structure:

- YAML frontmatter with title, description, date, tags, category, and selected template.
- A short Key Takeaways box after the introduction.
- H2 sections that open with a direct answer and a linked evidence signal.
- Citation capsules in major sections.
- FAQ section with concise answers.
- Visual placeholders such as `[CALLOUT]`, `[CHART]`, or `[IMAGE]`.
- `[INTERNAL-LINK: ...]` placeholders for later site integration.
- `## 来源记录` with publisher, title, retrieval date, and URL.

Quality reports live under `quality/` after `--validate-run`:

- `analyze.json`: claude-blog analyzer output when the script is available.

Evidence truth takes priority over the template's ideal SEO pattern. If the workflow did not collect verified statistics, do not invent numbers to satisfy the template. Use source-linked signals and mark evidence gaps instead.

Use `--strict-delivery` with `--validate-run` for heavier delivery validation. A blocked strict run is a quality signal, not a failed research run; inspect `metadata.json`, `review.md`, and `preflight-report.json` before deciding whether to iterate or bypass.

## Source Citation Pattern

Use natural inline links:

```markdown
Hacker News discussion around [the launch](https://example.com) focused less on the announcement and more on deployment friction.
```

Avoid a trailing source dump unless the publication format requires references. If references are needed, keep them short and deduplicated.
