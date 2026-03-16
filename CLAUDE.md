# SKY130 Bio-AFE — Autonomous Chip Design Agent

This is an experiment to have the LLM autonomously design a complete biomedical analog front-end chip.

## Setup

To set up a new design run, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar16`). The branch `autodesign/<tag>` must not already exist — this is a fresh run.
2. **Create the branch**: `git checkout -b autodesign/<tag>` from current master.
3. **Read the in-scope files**: Read these files for full context:
   - `master_spec.json` — system-level specs and block dependency graph
   - `interfaces.md` — signal contracts between blocks, biosignal characteristics, technology constants
   - `orchestrate.py` — build status and dependency management
   - For the block you're about to work on: `specs.json`, `program.md`
4. **Verify SKY130 PDK**: Check that ngspice works and SKY130 models are accessible. Run `ngspice -b -r /dev/null -o /dev/null` to verify. If models are missing, tell the human.
5. **Initialize results.tsv**: Create `results.tsv` in the block directory with just the header row.
6. **Run `python orchestrate.py --launch`** to see which blocks are ready.
7. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experiment loop.

## Block Selection

The orchestrator defines a dependency graph:

```
Phase 1 (all parallel — no dependencies):
  bandgap, inamp, pga, filter, adc

Phase 2 (waits for ALL of Phase 1):
  integration
```

Pick a Phase 1 block and work it to completion (score ≥ 1.0 with PVT validation). Then move to the next. When all Phase 1 blocks are COMPLETE, run `python orchestrate.py --propagate` and start Phase 2.

Within Phase 1, you choose the order. A reasonable strategy: start with `bandgap` (foundational, other blocks need its reference), then `adc` (well-understood SAR architecture), then `inamp` (hardest — noise and CMRR), then `pga` and `filter`.

## Working on a Block

When you start a block, you need to create the working files that don't exist yet:

- `design.cir` — parametric SPICE netlist (your circuit design)
- `parameters.csv` — parameter names with min/max/scale bounds
- `evaluate.py` — simulation runner that calls ngspice, parses results, scores against specs.json
- `README.md` — design documentation (update after every keeper)

Read `program.md` and `specs.json` to understand what testbenches to implement and what specs to meet. The agent has **full freedom** on circuit topology, optimization method, and design approach. The only constraint is `specs.json`.

## The Experiment Loop

LOOP FOREVER:

1. **Check state**: `python orchestrate.py` to see where things stand. Pick the next block to work on (or continue the current one).

2. **If starting a new block**:
   - Read its `program.md` and `specs.json`
   - Research the circuit topology (web search for prior art, textbook approaches, SKY130 examples on GitHub)
   - Create `design.cir` with a parametric initial design
   - Create `parameters.csv` with parameter ranges
   - Create `evaluate.py` implementing the testbenches from `program.md`
   - Git commit: `git add -A && git commit -m "block_name: initial design"`

3. **Run the evaluation**:
   ```bash
   cd blocks/<block_name>
   python evaluate.py > run.log 2>&1
   ```
   Redirect everything — do NOT let output flood your context.

4. **Read the results**:
   ```bash
   grep "score\|PASS\|FAIL\|Error" run.log | head -20
   ```
   If grep is empty, the run crashed. Run `tail -n 50 run.log` to see the error.

5. **Log results** to `results.tsv` in the block directory (tab-separated, untracked by git):
   ```
   step	commit	score	specs_met	description
   0	a1b2c3d	0.45	2/6	initial bandgap design from textbook
   1	b2c3d4e	0.72	4/6	increased mirror ratio for better PSRR
   ```

6. **CRITICAL — Study the plots and waveforms.** This is the step most agents skip, and it's the most important. See "Self-Evaluation After Every Run" below.

7. **Decide: keep or revert.**
   - If score improved AND the waveforms look physically correct → **keep**. Update `README.md` and `best_parameters.csv`. Commit and push.
   - If score improved BUT something looks wrong in the plots (ringing, saturation, unrealistic values) → **investigate before keeping**. A passing number from a broken circuit is worthless.
   - If score is equal or worse → `git reset --hard HEAD~1` to revert.

8. **Form the next hypothesis.** Based on what you saw in the plots and which specs failed, decide what single change to try next. Each iteration should try ONE thing — don't change everything at once.

9. **Repeat.** Go back to step 3.

10. **When score = 1.0** → enter Phase B (see below).

11. **When all Phase 1 blocks are COMPLETE**:
    - Run `python orchestrate.py --propagate`
    - Start the `integration` block

## Self-Evaluation After Every Run

**After EVERY run (not just keepers), you MUST study the output critically.** This is what separates a working chip from a number that happens to pass.

### Plot the Waveforms

`evaluate.py` should generate plots for each testbench defined in `program.md`. After each run:

1. **Look at every plot.** Don't just check the extracted number — look at the actual waveform shape.
2. **Save plots to `plots/`** with clear filenames matching the testbench names in `program.md`.

### Ask Yourself These Questions (for every plot)

- **"Does this look like what the textbook says it should?"** A bandgap V_REF vs temperature should show a bow shape. An AC response should be smooth, not jagged. A SAR ADC should show clean successive approximation steps. If the shape is wrong, the circuit is wrong regardless of what the number says.

- **"Are the voltage levels correct?"** Outputs should be within the rail-to-rail range. Bias points should be in saturation (not triode, not cutoff). If a node is sitting at VDD or VSS, something is railed.

- **"Is there ringing, overshoot, or oscillation?"** These indicate stability problems. A circuit that oscillates in simulation will definitely oscillate in silicon. Check phase margin.

- **"Is the signal settling before it's measured?"** If the transient simulation is too short, you're measuring the settling transient, not the final value. Look at the tail of every waveform.

- **"Are there any glitches or discontinuities?"** Sharp spikes could be charge injection, clock feedthrough, or convergence artifacts. Identify the cause.

- **"If data is NaN, zero, or suspiciously perfect"** — don't ignore it. A measurement of exactly 0.000 noise or infinite CMRR means the simulation is set up wrong.

### System-Level Check

Remember this block is part of a signal chain. After each evaluation, ask:

- **Bandgap:** "Will V_REF be stable enough for a 12-bit ADC? A 1% drift = 40 LSB error."
- **InAmp:** "With ±300 mV electrode offset, does the output stay in the PGA's input range?"
- **PGA:** "At gain=128, does the bandwidth still exceed 150 Hz? Does the output stay within 0.2-1.6V?"
- **Filter:** "Does the 0.5 Hz high-pass actually reject DC, or does it just attenuate by 3 dB?"
- **ADC:** "With a slowly-varying input from the filter (max 150 Hz), is the sampling clock fast enough? Is the input impedance compatible?"
- **Integration:** "Does the noise from all blocks RSS to less than 1 µVrms? Does the gain chain saturate at any point?"

### What to Write in README.md After a Keeper

The README is how the human monitors progress. After every keeper, update it with:

1. **Status banner** — which specs pass/fail, current score
2. **Spec table** — measured vs target, margin %, pass/fail for each
3. **Key plots** — embedded as `![description](plots/filename.png)` with one-line analysis:
   - What the plot shows
   - What "good" looks like
   - If anything is anomalous, explain it
4. **Design rationale** — why this topology, why these sizes (engineering reasoning, not "optimizer picked this")
5. **What was tried and rejected** — prevents repeating dead ends
6. **Known limitations** — honest assessment of weak points
7. **Experiment history** — summary table of runs

**If a plot shows unexpected behavior, don't hide it.** Show it, annotate the anomaly, explain your hypothesis. Honest reporting > clean-looking results.

## Phase A: Meet All Specs

First priority: get ALL specs to pass (score = 1.0).

- Focus on the highest-weight failing spec first
- Try obvious things first: textbook topology, sensible sizing
- If a spec is way off, rethink the topology — don't just tweak parameters
- When stuck, look at the waveforms. The circuit is telling you what's wrong.
- Even during Phase A, plot waveforms after every run. Numbers alone are not enough.

## Phase B: Deep Verification (after score = 1.0)

Once all specs pass, the real engineering begins. You are no longer hitting targets — you are proving this circuit works in the real world.

### B.1 — PVT Corner Analysis (MANDATORY)

Sweep: [tt, ss, ff, sf, fs] × [-40, 27, 125°C] × [1.62, 1.8, 1.98V] = 45 corners minimum.

- ALL specs must pass at ALL corners (or with documented relaxation)
- If a spec fails at a corner, go back to the design loop and fix it
- Plot worst-case overlay: e.g., V_REF(T) for all 5 process corners on one graph
- **Plot:** `plots/pvt_summary.png`

### B.2 — Monte Carlo Mismatch (if models available)

- 200 samples minimum
- Report mean, std, worst-case
- 3σ spread should still meet specs
- **Plot:** `plots/monte_carlo_histogram.png`

### B.3 — Margin Improvement

After PVT and MC pass:
- Reduce power where possible (lower bias currents if noise margin allows)
- Simplify the circuit (fewer transistors, smaller sizes)
- A design with 40% margin on every spec is better than one barely passing
- Try removing something — if you can delete a transistor and still pass, that's a win

### B.4 — Verification Completeness

Go through every testbench listed in `program.md`. For each:
1. Run the simulation
2. Generate the plot (saved to `plots/` with the name from program.md)
3. Add to README.md with analysis
4. If it reveals a problem, fix the design

Do NOT consider Phase B complete until every testbench has been run and every plot generated.

### B.5 — Move to Next Block

Once Phase B is complete (all PVT corners pass, all plots generated, margins documented):
1. Final update to README.md
2. Commit and push
3. Run `python orchestrate.py` to verify COMPLETE status
4. Pick the next block and start over

## What You CAN Modify

Per block:
- `design.cir` — circuit netlist, topology, transistor sizes, everything
- `parameters.csv` — parameter ranges and scales
- `evaluate.py` — simulation strategy, testbench implementation, optimization loops
- `README.md` — documentation
- `best_parameters.csv` — optimized values
- `measurements.json` — generated by evaluate.py

## What You CANNOT Modify

- `specs.json` in any block — these are the ground truth targets
- `master_spec.json` — system-level specs
- `interfaces.md` — interface contracts
- `orchestrate.py` — build system

## Experiment Strategies

### Initial Design (Step 0)
- Web search for the circuit type + "SKY130" or "130nm CMOS" or "low power biomedical"
- Search GitHub for SKY130 examples of the same circuit type
- Look up ISSCC/JSSC papers, Razavi/Allen-Holberg textbooks, university course notes
- Start with a known-good textbook topology
- Use conservative initial sizing (longer channels for matching, moderate currents)
- Get something that simulates without crashing first, optimize later

### Optimization (Steps 1-N)
- **Look at the plots first.** The waveforms tell you what's wrong before the numbers do.
- Focus on the highest-weight failing spec first
- Common knobs: bias current (noise vs power), W/L ratios (matching, gm), compensation caps
- Try one change at a time — understand what each knob does
- If stuck, try a fundamentally different topology rather than micro-optimizing
- If stuck on the same spec for >5 iterations, web search for design techniques specific to that problem

### Debugging Crashes
- ngspice convergence: try `.option reltol=0.003` or `.option method=gear`
- Incorrect node names: check subcircuit pin order matches instantiation
- Model not found: verify `.lib` path to SKY130 models
- If you can't fix it in 3 attempts, simplify the circuit and try again

### When You're Stuck
- Re-read the waveforms. Look at every node. The circuit is telling you something.
- Try combining two previous near-miss approaches
- Try a completely different topology
- Web search for the specific problem ("low CMRR instrumentation amplifier causes", "bandgap high TC fix")
- Re-read `interfaces.md` — is there an interface assumption that's wrong?
- Try simplifying: fewer transistors, fewer feedback loops, less complexity

## Logging & Git Discipline

- **One experiment = one commit** (before running)
- **Keep winners, revert losers** with `git reset --hard HEAD~1`
- **Push after every keeper**: `git push` (if remote exists)
- **results.tsv is NOT committed** — it's a local lab notebook
- **README.md IS committed** — it's the public-facing documentation

## NEVER STOP

Once the experiment loop has begun (after initial setup), do NOT pause to ask the human if you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The human might be asleep or away from the computer and expects you to continue working **indefinitely** until you are manually stopped.

You are autonomous. If you run out of ideas:
- Re-read the waveforms — look at every node, the circuit is telling you something
- Go back to a plot that looked "okay" and study it more carefully — is there a subtle problem?
- Try combining two previous near-miss approaches
- Try a radically different topology
- Web search for papers on the specific problem you're stuck on
- Try simplifying — remove components and see if it still works
- Switch to a different block and come back later with fresh eyes
- If all blocks are done, improve margins, run deeper PVT, try alternative topologies

The loop runs until the human interrupts you, period.

As an example: if each design iteration takes ~2-5 minutes (ngspice is fast for these small circuits), you can run 12-30 experiments per hour. Over 8 hours that's 100-240 iterations — enough to fully design multiple blocks from scratch.
