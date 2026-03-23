# skills-codex-claude-review 说明

这是一个**薄覆盖层**，适用于想采用以下组合的用户：

- **Codex** 作为主执行者
- **Claude Code** 作为审稿人
- 用本地 `claude-review` MCP bridge 替代“第二个 Codex reviewer”

它不是新造一套完整技能包，而是叠加在当前 repo 本地的 `skills/skills-codex/` 之上。

## 这个包包含什么

- 只包含需要切换 reviewer backend 的 review-heavy skill 覆盖文件
- 不重复打包模板和资源目录
- 不替代基础的 `skills/skills-codex/` 安装

当前覆盖的技能：

- `research-review`
- `novelty-check`
- `research-refine`
- `experiment-bridge`
- `auto-review-loop`
- `paper-plan`
- `paper-figure`
- `paper-write`
- `auto-paper-improvement-loop`

## 工作区配置

1. 保留当前 repo 内的基础 Codex skill tree：

`skills/skills-codex/`

2. 再叠加当前 repo 内的 Claude-review 覆盖层：

`skills/skills-codex-claude-review/`

3. 注册本地 reviewer bridge：

```bash
codex mcp add claude-review -- python3 /ABS/PATH/TO/Auto-claude-code-research-in-sleep/mcp-servers/claude-review/server.py
```

如果你的 Claude 依赖 `claude-aws` 之类的 shell helper，再改用 wrapper：

```bash
chmod +x mcp-servers/claude-review/run_with_claude_aws.sh
codex mcp add claude-review -- /ABS/PATH/TO/Auto-claude-code-research-in-sleep/mcp-servers/claude-review/run_with_claude_aws.sh
```

## 为什么需要这个包

上游 `skills/skills-codex/` 已经支持 Codex 原生执行，并通过 `spawn_agent` 使用第二个 Codex 做 reviewer。

这个覆盖层新增的是另一种分工：

- 执行者：Codex
- 审稿人：Claude Code CLI
- 传输层：`claude-review` MCP

对于长论文和长 review prompt，这条 reviewer 路径会改用：

- `review_start`
- `review_reply_start`
- `review_status`

这样可以绕开 Codex 宿主下，本地 Claude bridge 同步等待时更容易出现的超时问题。
