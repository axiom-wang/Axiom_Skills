# claude-blog Integration

Use this reference when changing the final writing stage of `blog-writing-workflow`.

## Agent Writer

`--writer agent-packet` is the only writer and the default. It creates `writing_packet.json`, which combines the selected category profile with one of 12 claude-blog article types. The Agent reads the referenced template, writes an initial `article.md`, applies the required `humanizer-zh` pass, then runs `--validate-run <run-dir>`.

The script does not call an external model or dispatch an Agent by itself. Standalone `agent-packet` runs intentionally stop after preparing the handoff.

## Typed Writing Packet

`writing_packet.json` adds these fields to the source-grounded packet:

- `category_profile`: voice, evidence requirements, required/prohibited moves, action style, risk disclosure, and validation checks.
- `article_type`, `type_selection_reason`, `article_type_confidence`, and `article_type_explicit`.
- `template_path` and `article_type_requirements` for the selected claude-blog template.
- `length_requirement`: effective-length unit, minimum, recommended maximum, default or CLI-override source, exclusions, and non-blocking enforcement behavior.
- `evidence_coverage`, `unmet_requirements`, and `global_writing_rules`.
- `agent_handoff`: article path, writing instructions, and validation command.
- `humanizer`: the `humanizer-zh` skill path, execution stage, fact-preservation rules, review path, and checklist schema.

Category evidence gaps are non-blocking. They must be disclosed or written as limited signals and are reported in `quality/writing-compliance.md`.

## Effective Chinese Length

Every article type defines `minimum_length` and `recommended_max_length` in `writing-profiles.json`. `--min-length` and `--max-length` may override both values for one `agent-packet` run; they must be positive, provided together, and satisfy minimum <= maximum.

Validation counts the final `article.md` after the Humanizer pass. Each Chinese character, English word, or numeric sequence counts as one unit. Frontmatter, fenced and inline code, URLs, HTML comments, placeholder lines, punctuation, Markdown syntax, and the `## 来源记录` section are excluded; Markdown link anchor text remains countable.

Falling below the minimum adds `minimum_length` to `writing-compliance.md` as `needs_work` but does not change the normal exit code. Exceeding the recommended maximum is informational and always passes. Evidence truth takes priority: never pad with repetition, filler, or unsupported claims.

## Humanizer Pass

The Agent must read the `humanizer.skill_path` file in full after the first draft and before validation. Humanization is an editorial rewrite, not a regex cleanup. It removes filler, promotional language, vague attribution, formulaic contrasts, mechanical three-part lists, excessive dashes, and chatbot traces while restoring natural rhythm and a category-appropriate voice.

The pass must not alter frontmatter, URLs, verified numbers, dates, names, quotations, code, commands, or the distinction between fact and inference. First-person experience is allowed only when the user or a cited source supplied it.

The Agent writes `quality/humanizer-review.md` with `状态: completed`, a concise `主要修改` list, and checked fact-preservation items for links, numbers/dates, quotations/code, and fabricated experience. Numeric self-scoring is intentionally omitted because it adds false precision without independent review. `--validate-run` then creates `quality/humanizer-check.md`; a missing review, incomplete checklist, or heuristic pattern findings are non-blocking `needs_work` results.

## Source-Grounded Base Packet

`writing_packet.json` builds on a source-grounded base packet (the same fields the research stage produces). It includes:

- `topic`, `title`, `category`, `angle`, `template`, `language`
- `target_audience`, `primary_keyword`, `secondary_keywords`
- `source_coverage`: item count, source count, and source names
- `evidence`: top evidence items rewritten as source-linked facts
- `faq_plan`, `visual_plan`, `internal_link_zones`
- `source_records`: publisher, title, retrieval date, and URL
- `quality_constraints`: rules the writer must respect

The packet must not contain secrets. Environment variable names may appear in skipped-source reasons, but token values must never be written.

## Article Rules

`article.md` should follow claude-blog's public-writing conventions while staying source-grounded:

- frontmatter for publishing metadata
- Key Takeaways box
- answer-first H2 sections
- citation capsules
- FAQ section
- visual placeholders
- internal-link placeholders
- source records

Do not fabricate statistics. If a source item contains no verified number, describe it as a signal with date, source, title, and URL.

## Quality Checks

Default checks are non-blocking:

- `quality/analyze.json`: runs `/Users/deepwisdom/project/information/claude-blog/scripts/analyze_blog.py` when available.
- `quality/writing-compliance.md`: category, article-type structure, and evidence-coverage report for `agent-packet` runs.
- `quality/humanizer-review.md`: Agent-authored audit record for the `humanizer-zh` pass.
- `quality/humanizer-check.md`: review validation plus a local heuristic scan for common AI-writing patterns.

Non-blocking means the workflow still exits 0 when article generation succeeds, even if quality reports say the article needs work.

## Strict Delivery

`--strict-delivery`, passed together with `--validate-run`, runs the heavier claude-blog delivery scripts from `/Users/deepwisdom/project/information/claude-blog/scripts`:

1. `generate_hero.py`
2. `blog_render.py`
3. `blog_preflight.py --strict --json`

If strict delivery blocks, the workflow preserves all artifacts, records the block under `metadata.json.strict_delivery`, prints the run result, and exits non-zero.

The script cannot dispatch the actual `blog-reviewer` agent by itself. In strict mode it writes a nonce-bound `review.md` that blocks delivery with a clear message unless a real reviewer pass replaces it.
