---
name: monitor-experiment
description: Monitor running experiments, check progress, collect results. Use when user says "check results", "is it done", "monitor", or wants experiment output.
argument-hint: [server-alias or screen-name]
allowed-tools: Bash(ssh *), Bash(echo *), Read, Write, Edit
---

# Monitor Experiment Results

Monitor: $ARGUMENTS

## Research Workspace

Resolve the active research workspace before collecting artifacts:

```bash
RESEARCH_ROOT="$(python3 tools/aris_research_workspace.py ensure --stage monitor-experiment --arguments "$ARGUMENTS" --print-path)"
echo "Using research workspace: $RESEARCH_ROOT"
PROJECT_CLAUDE="$(python3 tools/aris_claude_file.py ensure --workspace-root "$RESEARCH_ROOT" --print-path)"
echo "Using project CLAUDE.md: $PROJECT_CLAUDE"
```

Use `$RESEARCH_ROOT/CLAUDE.md` as the canonical project file. Repo-root `CLAUDE.md`, when present, only supplies shared defaults and fallback for missing shared fields such as W&B configuration.

Treat runtime artifacts and run outputs as relative to `$RESEARCH_ROOT`, especially:

- `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RUNTIME.json`
- `$RESEARCH_ROOT/results/<run_name>/RUN_STATE.json`

## Workflow

### Step 1: Check What's Running
```bash
ssh <server> "screen -ls"
```

### Step 2: Collect Output from Each Screen
For each screen session, capture the last N lines:
```bash
ssh <server> "screen -S <name> -X hardcopy /tmp/screen_<name>.txt && tail -50 /tmp/screen_<name>.txt"
```

If hardcopy fails, check for log files or tee output.

### Step 3: Check for JSON Result Files
```bash
ssh <server> "ls -lt <results_dir>/*.json 2>/dev/null | head -20"
```

If JSON results exist, fetch and parse them:
```bash
ssh <server> "cat <results_dir>/<latest>.json"
```

### Step 3.2: Inspect Runtime Artifact and Resume State

Read `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RUNTIME.json` when it exists. For each active or recent run, extract:
- `status`
- `resume_capable`
- `resume_policy`
- `output_dir`
- `checkpoint_dir`
- `run_state_path`
- `latest_checkpoint`
- `progress_marker`
- `resume_command`

If a run-state file exists, fetch it too:
```bash
ssh <server> "cat <output_dir>/RUN_STATE.json"
```

Use it to answer:
- what was the last completed epoch / step / iteration?
- is a valid checkpoint available right now?
- if the run stopped, can it resume automatically or not?

### Step 3.5: Pull W&B Metrics (when `wandb: true` in the project-level `CLAUDE.md`)

**Skip this step entirely if `wandb` is not set or is `false` in `$RESEARCH_ROOT/CLAUDE.md`, falling back to repo-root `CLAUDE.md` only for missing shared fields.**

Pull training curves and metrics from Weights & Biases via Python API:

```bash
# List recent runs in the project
ssh <server> "python3 -c \"
import wandb
api = wandb.Api()
runs = api.runs('<entity>/<project>', per_page=10)
for r in runs:
    print(f'{r.id}  {r.state}  {r.name}  {r.summary.get(\"eval/loss\", \"N/A\")}')
\""

# Pull specific metrics from a run (last 50 steps)
ssh <server> "python3 -c \"
import wandb, json
api = wandb.Api()
run = api.run('<entity>/<project>/<run_id>')
history = list(run.scan_history(keys=['train/loss', 'eval/loss', 'eval/ppl', 'train/lr'], page_size=50))
print(json.dumps(history[-10:], indent=2))
\""

# Pull run summary (final metrics)
ssh <server> "python3 -c \"
import wandb, json
api = wandb.Api()
run = api.run('<entity>/<project>/<run_id>')
print(json.dumps(dict(run.summary), indent=2, default=str))
\""
```

**What to extract:**
- **Training loss curve** — is it converging? diverging? plateauing?
- **Eval metrics** — loss, PPL, accuracy at latest checkpoint
- **Learning rate** — is the schedule behaving as expected?
- **GPU memory** — any OOM risk?
- **Run status** — running / finished / crashed?

**W&B dashboard link** (include in summary for user):
```
https://wandb.ai/<entity>/<project>/runs/<run_id>
```

> This gives the auto-review-loop richer signal than just screen output — training dynamics, loss curves, and metric trends over time.

### Step 4: Summarize Results

Present results in a comparison table:
```
| Experiment | Metric | Delta vs Baseline | Status | Resume |
|-----------|--------|-------------------|--------|--------|
| Baseline  | X.XX   | —                 | done   | yes (epoch 2 / step 1400) |
| Method A  | X.XX   | +Y.Y              | interrupted | yes (latest ckpt: step_2800) |
```

### Step 5: Interpret
- Compare against known baselines
- Flag unexpected results (negative delta, NaN, divergence)
- Suggest next steps based on findings

### Step 6: Feishu Notification (if configured)

After results are collected, check `~/.claude/feishu.json`:
- Send `experiment_done` notification: results summary table, delta vs baseline
- If config absent or mode `"off"`: skip entirely (no-op)

## Key Rules
- Always show raw numbers before interpretation
- Compare against the correct baseline (same config)
- Note if experiments are still running (check progress bars, iteration counts)
- Distinguish `interrupted` from `failed`; if resume metadata exists, say exactly where the next launch would continue from
- If results look wrong, check training logs for errors before concluding
