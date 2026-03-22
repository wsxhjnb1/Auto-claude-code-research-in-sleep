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
- write parseable runtime evidence to `refine-logs/EXPERIMENT_RUNTIME.json`

## Workflow

### Step 1: Detect Environment

Read the project's `CLAUDE.md` to determine the experiment environment:

- **Local GPU**: look for local CUDA / MPS setup info
- **Remote server**: look for SSH alias, conda env, code directory
- **Profiling hints**: look for profiler guidance or restrictions

If no server info is found in `CLAUDE.md`, ask the user.

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

### Step 3: Sync Code (Remote Only)

Check the project's `CLAUDE.md` for a `code_sync` setting. If not specified, default to `rsync`.

#### Option A: rsync (default)

Only sync necessary files — NOT data, checkpoints, or large files:
```bash
rsync -avz --include='*.py' --exclude='*' <local_src>/ <server>:<remote_dst>/
```

#### Option B: git (when `code_sync: git` is set in CLAUDE.md)

Push local changes to remote repo, then pull on the server:
```bash
# 1. Push from local
git add -A && git commit -m "sync: experiment deployment" && git push

# 2. Pull on server
ssh <server> "cd <remote_dst> && git pull"
```

Benefits: version-tracked, multi-server sync with one push, no rsync include / exclude rules needed.

### Step 3.5: W&B Integration (when `wandb: true` in CLAUDE.md)

**Skip this step entirely if `wandb` is not set or is `false` in `CLAUDE.md`.**

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

> The W&B project name and API key come from `CLAUDE.md`. The experiment name is auto-generated from the script name + timestamp.

### Step 4: Prepare Runtime Evidence Capture

Before launch, create or refresh `refine-logs/EXPERIMENT_RUNTIME.json`.

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
- exit code
- wall time
- GPU memory sample(s)
- throughput if available
- log file path
- metrics file path if available
- `failure_signatures`: array of matched runtime issues (`oom`, `nan`, `inf`, `missing_metrics`, `malformed_output`, `slowdown`, `timeout`, `unknown`)

### Step 5: Optional Light Profiling

If the caller requested `LIGHT_PROFILE = true` and the stack exposes a clean profiler, collect a short sample during the sanity run:

- **PyTorch**: a short `torch.profiler` sample is acceptable if it can be added without destabilizing the run
- **CUDA tooling**: use a lightweight, already-available profiler only if it is straightforward and does not require new infrastructure
- **Otherwise**: fall back to coarse evidence only (wall time, throughput, memory, GPU allocation, idle / busy clues from logs)

The core path must remain framework-agnostic. If profiling would require invasive setup, skip it and record `"profile_mode": "coarse"`.

### Step 6: Deploy

#### Remote (via SSH + screen)

For each experiment, create a dedicated screen session with GPU binding. Wrap the command so runtime evidence is captured:

```bash
ssh <server> "screen -dmS <exp_name> bash -c '\
  eval \"\$(<conda_path>/conda shell.bash hook)\" && \
  conda activate <env> && \
  START_TS=\$(date -Iseconds) && \
  /usr/bin/time -f \"WALL=%e\" sh -c \"CUDA_VISIBLE_DEVICES=<gpu_id> python <script> <args> 2>&1 | tee <log_file>\"; \
  EXIT_CODE=\$?; \
  END_TS=\$(date -Iseconds); \
  # update refine-logs/EXPERIMENT_RUNTIME.json with exit code, wall time, and failure signatures \
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

After launch (and again after completion for background jobs), update `refine-logs/EXPERIMENT_RUNTIME.json` with:

- `status`: `running`, `completed`, or `failed`
- selected GPU / device
- wall time
- peak or sampled GPU memory if available
- throughput if available
- metrics artifact location if available
- failure signatures derived from logs

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
- `refine-logs/EXPERIMENT_RUNTIME.json` is populated with a usable run record

### Step 9: Feishu Notification (if configured)

After deployment is verified, check `~/.claude/feishu.json`:
- send `experiment_done`: which experiments launched, which GPUs, estimated time
- if config absent or mode `"off"`: skip entirely

## Output Contract for Debate Loops

`experiment-bridge` assumes this skill leaves behind a usable runtime artifact. Do not finish with only terminal logs.

Minimum contract:
- `refine-logs/EXPERIMENT_RUNTIME.json` exists
- the latest run has `command`, `environment`, `exit_code` or `status`, `wall_time` if finished, and `failure_signatures`
- log file path is recorded
- throughput / GPU memory are included when available, not fabricated when unavailable

## Key Rules

- ALWAYS check GPU availability first — never blindly assign GPUs
- ALWAYS write `refine-logs/EXPERIMENT_RUNTIME.json` — debate loops depend on it
- Each experiment gets its own screen session + GPU (remote) or background process (local)
- Use `tee` to save logs for later inspection
- Capture structured failure signatures, not just free-form notes
- Use light profiling only when it is straightforward; otherwise record coarse runtime evidence and move on
- Report back: which GPU, which screen / process, what command, estimated time, and where the runtime artifact was written
- If multiple experiments run in parallel, keep separate run records inside the same runtime artifact

## CLAUDE.md Example

Users should add their server info to their project's `CLAUDE.md`:

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

> **W&B setup**: Run `wandb login` on your server once (or set `WANDB_API_KEY` env var). The skill reads project / entity from `CLAUDE.md` and adds `wandb.init()` + `wandb.log()` to your training scripts automatically. Dashboard: `https://wandb.ai/<entity>/<project>`.
