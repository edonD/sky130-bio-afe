# Bio-AFE — Runbook

Step-by-step instructions from setup to a complete 4-channel biomedical AFE chip.

---

## Prerequisites

- `ngspice` installed and in PATH
- `claude` CLI installed with valid API key
- `tmux` installed (for persistent agent sessions)
- `python3` with numpy, scipy, matplotlib
- Git repo initialized with a remote (for push)

---

## Phase 1: Parallel Block Design (5 agents)

All 5 analog blocks have no dependencies and can run simultaneously.

### Launch all Phase 1 agents

```bash
cd sky130-bio-afe

# Launch all 5 in parallel (each runs in its own tmux session)
bash start.sh bandgap
bash start.sh inamp
bash start.sh pga
bash start.sh filter
bash start.sh adc
```

Or launch just one at a time if running on a single machine:
```bash
bash start.sh bandgap
# Wait for it to complete, then:
bash start.sh adc
# etc.
```

### Monitor progress

```bash
# Check which agents are running
tmux ls

# Watch a specific agent
tmux attach -t bandgap    # Ctrl+B, D to detach

# Quick status check (from another terminal)
python orchestrate.py

# Check a block's README for latest results
cat blocks/bandgap/README.md

# Check git log for commits
git log --oneline -10
```

### What each agent does

Each agent autonomously:
1. Reads program.md and specs.json
2. Researches the circuit topology (web search)
3. Creates design.cir, parameters.csv, evaluate.py
4. Runs the experiment loop: design → simulate → evaluate plots → keep/revert → repeat
5. Phase A: iterates until score = 1.0 (all specs pass)
6. Phase B: PVT corners, Monte Carlo, margin improvement, all plots
7. Updates README.md after every improvement
8. Commits and pushes progress

### Expected duration

| Block | Difficulty | Estimated time |
|-------|-----------|---------------|
| bandgap | Medium | 2-4 hours |
| adc | Medium | 3-5 hours |
| pga | Medium | 2-4 hours |
| filter | Medium-Hard | 3-5 hours |
| inamp | Hard | 4-8 hours |

### When a block is done

The agent will keep running (improving margins, deepening PVT analysis) until you stop it. Check completion with:

```bash
python orchestrate.py
# A block shows [DONE] when measurements.json exists with score >= 0.8
```

To stop an agent:
```bash
tmux kill-session -t bandgap
```

---

## Between Phase 1 and Phase 2

### Pull results and check status

```bash
cd sky130-bio-afe
git pull   # if agents pushed to remote

python orchestrate.py
# Expected: all 5 Phase 1 blocks show [DONE]
```

### Propagate measurements downstream

```bash
python orchestrate.py --propagate
# This writes upstream_config.json into blocks/integration/
# with actual measured values from all 5 upstream blocks

git add -A && git commit -m "Propagate Phase 1 measurements to integration" && git push
```

---

## Phase 2: System Integration (1 agent)

### Launch

```bash
bash start.sh integration
```

### What the integration agent does

1. Reads measurements.json from all 5 upstream blocks
2. Connects the full signal chain: bandgap → inamp → PGA → filter → ADC
3. Runs system-level validation:
   - DC signal chain verification
   - Full-chain frequency response
   - System noise (RSS of all blocks)
   - System CMRR end-to-end
   - ECG acquisition with realistic signals (1 mV + 300 mV offset + 60 Hz interference)
   - EEG acquisition (50 µV signal)
   - Power budget verification
   - PVT system validation
4. Produces integration plots and system-level README

### Expected duration: 3-6 hours

### When done

```bash
python orchestrate.py
# All 6 blocks should show [DONE]
```

---

## Quick Reference

### Orchestrator commands

```bash
python orchestrate.py              # Show status of all blocks
python orchestrate.py --launch     # Show what's ready to start
python orchestrate.py --propagate  # Push measurements downstream
```

### Agent management

```bash
bash start.sh <block>             # Start an agent
tmux attach -t <block>            # Watch a running agent
tmux kill-session -t <block>      # Stop an agent
tmux ls                           # List all running agents
```

### Emergency: kill everything

```bash
tmux kill-server   # Kills ALL tmux sessions
```

---

## Dependency Graph

```
Phase 1 (parallel, 5 agents):

    ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ Bandgap  │  │  InAmp   │  │   PGA    │  │  Filter  │  │   ADC    │
    │ (V_REF)  │  │ (50x,    │  │ (1-128x) │  │(0.5-150  │  │ (12-bit) │
    │          │  │  CMRR)   │  │          │  │   Hz)    │  │          │
    └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
         │              │              │              │              │
         └──────────────┴──────────────┴──────┬───────┴──────────────┘
                                              │  propagate
                                              ▼
Phase 2 (1 agent):
    ┌─────────────────────────────────────────────────┐
    │              Integration                         │
    │  Full signal chain: ECG/EEG acquisition          │
    │  4-channel system validation                     │
    └─────────────────────────────────────────────────┘
```
