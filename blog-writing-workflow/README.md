# blog-writing-workflow

从选题到证据采集、角度评分、写作包与校验的博客生产流水线。

## 安装

把本目录完整复制到：

- Cursor：`~/.cursor/skills/blog-writing-workflow/`
- Claude Code：`~/.claude/skills/blog-writing-workflow/`

或放到项目内的 `.cursor/skills/` / `.agents/skills/` / `.claude/skills/`。

## 快速试跑

```bash
cd blog-writing-workflow
python scripts/blog_workflow.py --list-categories
python scripts/blog_workflow.py --topic "你的选题" --days 14
```

## 使用

对话中输入 `/blog-writing-workflow`，或描述「用博客写作工作流帮我做一篇关于 X 的文章」。

完整说明见仓库根目录 [README.md](../README.md)。
