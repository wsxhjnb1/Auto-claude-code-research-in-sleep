---
name: "monitor-experiment"
description: "Monitor running experiments, check progress, collect results. Use when user says \"check results\", \"is it done\", \"monitor\", or wants experiment output."
---

# Monitor Experiment Results

Monitor: $ARGUMENTS

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

Read `refine-logs/EXPERIMENT_RUNTIME.json` when it exists. For each active or recent run, extract:
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

After results are collected, check `~/.codex/feishu.json`:
- Send `experiment_done` notification: results summary table, delta vs baseline
- If config absent or mode `"off"`: skip entirely (no-op)

## Key Rules
- Always show raw numbers before interpretation
- Compare against the correct baseline (same config)
- Note if experiments are still running (check progress bars, iteration counts)
- Distinguish `interrupted` from `failed`; if resume metadata exists, say exactly where the next launch would continue from
- If results look wrong, check training logs for errors before concluding
