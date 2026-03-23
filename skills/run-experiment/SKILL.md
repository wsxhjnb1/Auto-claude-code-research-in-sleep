---
name: run-experiment
description: Deploy and run ML experiments on local or remote GPU servers. Capture structured runtime evidence for debate loops in addition to launching the job. Use when user says "run experiment", "deploy to server", "跑实验", or needs to launch training jobs.
argument-hint: [experiment-description]
allowed-tools: Bash(*), Read, Grep, Glob, Edit, Write, Agent
---

# Run Experiment

Deploy and run ML experiment: $ARGUMENTS

This skill is the execution side of Workflow 1.5. In v1 it must do two things:
- launch the experiment correctly
- write parseable runtime evidence to `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RUNTIME.json`

It now also owns the **long-run resume contract**:
- any run that is multi-step or likely to exceed roughly 10 minutes is a **long run**
- long runs must be checkpointed and resumable
- the next launch must auto-resume from the latest valid checkpoint without a manually edited command

## Research Workspace

Resolve the active research workspace before launch:

```bash
RESEARCH_ROOT="$(python3 tools/aris_research_workspace.py ensure --stage run-experiment --arguments "$ARGUMENTS" --print-path)"
echo "Using research workspace: $RESEARCH_ROOT"
PROJECT_CLAUDE="$(python3 tools/aris_claude_file.py ensure --workspace-root "$RESEARCH_ROOT" --print-path)"
echo "Using project CLAUDE.md: $PROJECT_CLAUDE"
```

Use `$RESEARCH_ROOT/CLAUDE.md` as the canonical project file. If repo-root `CLAUDE.md` exists, only use it as shared defaults and fallback for missing shared fields such as server, code sync, W&B, or paper-library configuration. Never inherit `## Pipeline Status` from the repo root.

All experiment artifacts belong under that workspace:

- runtime artifact: `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RUNTIME.json`
- run outputs: `$RESEARCH_ROOT/results/<run_name>/`
- per-run state: `$RESEARCH_ROOT/results/<run_name>/RUN_STATE.json`

Repo-level runtime such as `.venv/`, `.claude/`, and repo-level sync/browser state remains at the repo root.

## Workflow

### Step 1: Detect Environment

Read the active research workspace `CLAUDE.md` (`$RESEARCH_ROOT/CLAUDE.md`) to determine the experiment environment. Only if a shared field is missing there should you fall back to repo-root `CLAUDE.md`:

- **Local GPU**: look for local CUDA / MPS setup info
- **Remote server**: look for SSH alias, conda env, code directory
- **Profiling hints**: look for profiler guidance or restrictions

If no server info is found in either location, ask the user.

### Step 2: Pre-flight Check

Check GPU availability on the target machine:

**Remote:**
```bash
ssh <server> nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader
```

**Local:**
```bash
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader
# or for Mac MPS:
python -c "import torch; print('MPS available:', torch.backends.mps.is_available())"
```

Free GPU = memory.used < 500 MiB.

Record the selected device and environment summary for the runtime artifact.

Classify the launch before touching the target machine:
- **Long run** = clearly iterative (training / finetuning / search / long batched generation or evaluation) or likely to exceed roughly 10 minutes
- **Short one-shot run** = stateless and below that threshold

If a run is long, it is not launchable until the code exposes:
- a stable `output_dir`
- a canonical `checkpoint_dir`
- a parseable run-state file
- an auto-resume path from the latest valid checkpoint

### Step 3: Sync Code (Remote Only)

Check the active research workspace `CLAUDE.md` for a `code_sync` setting, then fall back to repo-root `CLAUDE.md`. If not specified, default to `rsync`.

#### Option A: rsync (default)

Only sync necessary files — NOT data, checkpoints, or large files:
```bash
rsync -avz --include='*.py' --exclude='*' <local_src>/ <server>:<remote_dst>/
```

#### Option B: git (when `code_sync: git` is set in the project-level `CLAUDE.md`)

Push local changes to remote repo, then pull on the server:
```bash
# 1. Push from local
git add -A && git commit -m "sync: experiment deployment" && git push

# 2. Pull on server
ssh <server> "cd <remote_dst> && git pull"
```

Benefits: version-tracked, multi-server sync with one push, no rsync include / exclude rules needed.

### Step 3.5: W&B Integration (when `wandb: true` in the project-level `CLAUDE.md`)

**Skip this step entirely if `wandb` is not set or is `false` in the project-level `CLAUDE.md` (or repo fallback).**

Before deploying, ensure the experiment scripts have W&B logging:

1. **Check if wandb is already in the script** — look for `import wandb` or `wandb.init`. If present, skip to Step 4.
2. **If not present, add W&B logging** to the training script:
   ```python
   import wandb
   wandb.init(project=WANDB_PROJECT, name=EXP_NAME, config={...hyperparams...})

   # Inside training loop:
   wandb.log({"train/loss": loss, "train/lr": lr, "step": step})

   # After eval:
   wandb.log({"eval/loss": eval_loss, "eval/ppl": ppl, "eval/accuracy": acc})

   # At end:
   wandb.finish()
   ```
3. **Metrics to log** (add whichever apply to the experiment):
   - `train/loss`
   - `train/lr`
   - `eval/loss`, `eval/ppl`, `eval/accuracy`
   - `gpu/memory_used`
   - `speed/samples_per_sec`
   - any custom metrics the experiment already computes
4. **Verify wandb login on the target machine:**
   ```bash
   ssh <server> "wandb status"
   # If not logged in:
   ssh <server> "wandb login <WANDB_API_KEY>"
   ```

> The W&B project name and API key come from the project-level `CLAUDE.md` first, then repo-root fallback if needed. The experiment name is auto-generated from the script name + timestamp.

### Step 4: Prepare Runtime Evidence Capture

Before launch, create or refresh `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RUNTIME.json`.

For newly written experiment code, prefer this default layout:

```text
$RESEARCH_ROOT/results/<run_name>/
├── checkpoints/
├── RUN_STATE.json
├── metrics.json   # or project-native results file
└── train.log      # or tee output
```

Project-native layouts are allowed, but the runtime artifact must still record the concrete `output_dir`, `checkpoint_dir`, and run-state path.

The artifact must include, at minimum:

```json
{
  "status": "launching",
  "command": "python train.py ...",
  "environment": {
    "host": "local-or-ssh-alias",
    "device": "cuda:0",
    "conda_env": "research",
    "workdir": "/path/to/code"
  },
  "started_at": "2026-03-22T21:00:00",
  "runs": []
}
```

For each launched run, append or update a run record with:
- run name / screen session / PID if available
- command
- resume classification (`resume_capable`, `resume_policy`)
- `output_dir`
- `checkpoint_dir`
- `run_state_path`
- `latest_checkpoint`
- `progress_marker`
- `resume_command`
- exit code
- wall time
- GPU memory sample(s)
- throughput if available
- log file path
- metrics file path if available
- `failure_signatures`: array of matched runtime issues (`oom`, `nan`, `inf`, `missing_metrics`, `malformed_output`, `slowdown`, `timeout`, `unknown`)

For long runs, maintain a parseable run-state file at the canonical path (default: `<output_dir>/RUN_STATE.json`) with at least:

```json
{
  "run_name": "baseline_seed1",
  "status": "running",
  "output_dir": "results/baseline_seed1",
  "checkpoint_dir": "results/baseline_seed1/checkpoints",
  "latest_checkpoint": "results/baseline_seed1/checkpoints/step_1400.pt",
  "progress_marker": {
    "epoch": 2,
    "step": 1400,
    "updated_at": "2026-03-22T21:15:00"
  },
  "resume_command": "python train.py --output_dir results/baseline_seed1 --resume auto",
  "updated_at": "2026-03-22T21:15:00"
}
```

Use the progress fields that make sense for the codebase (`epoch`, `step`, `iteration`, `sample_count`, etc.), but record at least one monotonically increasing progress marker plus `updated_at`.

### Step 5: Optional Light Profiling

If the caller requested `LIGHT_PROFILE = true` and the stack exposes a clean profiler, collect a short sample during the sanity run:

- **PyTorch**: a short `torch.profiler` sample is acceptable if it can be added without destabilizing the run
- **CUDA tooling**: use a lightweight, already-available profiler only if it is straightforward and does not require new infrastructure
- **Otherwise**: fall back to coarse evidence only (wall time, throughput, memory, GPU allocation, idle / busy clues from logs)

The core path must remain framework-agnostic. If profiling would require invasive setup, skip it and record `"profile_mode": "coarse"`.

### Step 6: Deploy

#### Remote (via SSH + screen)

For each experiment, create a dedicated screen session with GPU binding. Wrap the command so runtime evidence is captured and long runs auto-resume:

```bash
ssh <server> "screen -dmS <exp_name> bash -c '\
  eval \"\$(<conda_path>/conda shell.bash hook)\" && \
  conda activate <env> && \
  # inspect RUN_STATE.json / checkpoint_dir and construct the exact resume command when a valid checkpoint exists \
  START_TS=\$(date -Iseconds) && \
  /usr/bin/time -f \"WALL=%e\" sh -c \"CUDA_VISIBLE_DEVICES=<gpu_id> python <script> <args> 2>&1 | tee <log_file>\"; \
  EXIT_CODE=\$?; \
  END_TS=\$(date -Iseconds); \
  # update $RESEARCH_ROOT/refine-logs/EXPERIMENT_RUNTIME.json with exit code, wall time, failure signatures, latest checkpoint, and progress marker \
  exit \$EXIT_CODE'"
```

#### Local

```bash
# Linux with CUDA
/usr/bin/time -f "WALL=%e" sh -c 'CUDA_VISIBLE_DEVICES=<gpu_id> python <script> <args> 2>&1 | tee <log_file>'

# Mac with MPS
/usr/bin/time -f "WALL=%e" sh -c 'python <script> <args> 2>&1 | tee <log_file>'
```

For local long-running jobs, use `run_in_background: true` to keep the conversation responsive.

### Step 7: Parse Runtime Evidence

After launch (and again after completion for background jobs), update `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RUNTIME.json` with:

- `status`: `running`, `completed`, or `failed`
- `resume_capable`: `true` / `false`
- `resume_policy`: `auto`, `not_applicable`, or an explicit project-native policy string
- `output_dir`, `checkpoint_dir`, `run_state_path`
- `latest_checkpoint`
- `progress_marker`
- `resume_command`
- selected GPU / device
- wall time
- peak or sampled GPU memory if available
- throughput if available
- metrics artifact location if available
- failure signatures derived from logs

Interrupted runs must be recorded distinctly from clean failures. Use `status: interrupted` when the run stopped after making valid resume state, so the next invocation knows to attempt resume first instead of treating it as a fresh failure.

Scan logs for at least these signatures:
- `CUDA out of memory`
- `out of memory`
- `nan`
- `inf`
- missing or unreadable metrics files
- malformed JSON / CSV outputs
- explicit timeout or hang markers

If throughput is unusually low relative to a comparable baseline or hardware expectation, add `slowdown` to `failure_signatures` even if the run technically completed.

### Step 8: Verify Launch / Completion

**Remote:**
```bash
ssh <server> "screen -ls"
```

**Local:**
Check that the process is running and the GPU is allocated.

A run is not considered healthy until both are true:
- the process launched successfully
- `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RUNTIME.json` is populated with a usable run record

### Step 9: Feishu Notification (if configured)

After deployment is verified, check `~/.claude/feishu.json`:
- send `experiment_done`: which experiments launched, which GPUs, estimated time
- if config absent or mode `"off"`: skip entirely

## Output Contract for Debate Loops

`experiment-bridge` assumes this skill leaves behind a usable runtime artifact. Do not finish with only terminal logs.

Minimum contract:
- `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RUNTIME.json` exists
- the latest run has `command`, `environment`, `exit_code` or `status`, `wall_time` if finished, and `failure_signatures`
- long runs also have `resume_capable`, `resume_policy`, `output_dir`, `checkpoint_dir`, `run_state_path`, `latest_checkpoint`, `progress_marker`, and `resume_command`
- log file path is recorded
- throughput / GPU memory are included when available, not fabricated when unavailable

## Key Rules

- ALWAYS check GPU availability first — never blindly assign GPUs
- ALWAYS write `$RESEARCH_ROOT/refine-logs/EXPERIMENT_RUNTIME.json` — debate loops depend on it
- NEVER launch a long run without a stable output root, checkpoint directory, run-state file, and auto-resume path
- Each experiment gets its own screen session + GPU (remote) or background process (local)
- Use `tee` to save logs for later inspection
- Capture structured failure signatures, not just free-form notes
- Record interruptions distinctly from failures so the next launch can resume instead of guessing
- Use light profiling only when it is straightforward; otherwise record coarse runtime evidence and move on
- Report back: which GPU, which screen / process, what command, estimated time, and where the runtime artifact was written
- If multiple experiments run in parallel, keep separate run records inside the same runtime artifact

## CLAUDE.md Example

Users should add their server info to the research workspace `CLAUDE.md` at `$RESEARCH_ROOT/CLAUDE.md`:

```markdown
## Remote Server
- SSH: `ssh my-gpu-server`
- GPU: 4x A100 (80GB each)
- Conda: `eval "$(/opt/conda/bin/conda shell.bash hook)" && conda activate research`
- Code dir: `/home/user/experiments/`
- code_sync: rsync          # default. Or set to "git" for git push/pull workflow
- wandb: false              # set to "true" to auto-add W&B logging to experiment scripts
- wandb_project: my-project # W&B project name (required if wandb: true)
- wandb_entity: my-team     # W&B team/user (optional, uses default if omitted)

## Local Environment
- Mac MPS / Linux CUDA
- Conda env: `ml` (Python 3.10 + PyTorch)
```

> **W&B setup**: Run `wandb login` on your server once (or set `WANDB_API_KEY` env var). The skill reads project / entity from `$RESEARCH_ROOT/CLAUDE.md` first, then repo-root fallback, and adds `wandb.init()` + `wandb.log()` to your training scripts automatically. Dashboard: `https://wandb.ai/<entity>/<project>`.
