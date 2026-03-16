# SKY130 Bio-AFE Autoresearch

This is an experiment in autonomous analog circuit design.

The original `autoresearch` idea was about an LLM improving an AI training run under a fixed evaluator. The same pattern applies here, but the object of optimization is not a model checkpoint. It is a physically credible analog circuit in SKY130 that survives hard simulation, realistic signal conditions, and hostile self-evaluation.

Your job is not to produce a pretty README or a suspiciously good scalar. Your job is to design circuits that would still look defensible to an analog designer reading the netlist, the plots, the operating points, and the corner data.

## Mission

Design the full biomedical analog front-end in this repository by running an indefinite autonomous design loop across the block directories:

- `blocks/bandgap`
- `blocks/inamp`
- `blocks/pga`
- `blocks/filter`
- `blocks/adc`
- `blocks/integration`

Every block has a local `program.md` and `specs.json`. The local file defines the block objective, testbenches, and deliverables. This root file defines the operating doctrine: how to run, how to evaluate, how to keep or discard work, and what "good engineering" means.

## Core Doctrine

Be rigid about truth, flexible about method.

- Be ruthless about evaluation design. The evaluator should try to prove the circuit is broken.
- Be flexible about circuit design. Topology, sizing, biasing, compensation, optimization method, measurement flow, and netlist structure are all open.
- A passing scalar is necessary but not sufficient. If the waveform shape, bias point, operating region, margin, startup, or corner behavior looks wrong, the run is not a keeper.
- Never make the testbench easier just to get a better score. If a metric improves because the evaluation got weaker, the result is invalid.
- Never fake realism. Do not hard-code outputs, edit PDK files, ignore convergence warnings, or report impossible numbers without proving them.

Think like a hostile reviewer:

- "Where could this circuit be fooling me?"
- "What would fail first in silicon?"
- "Does this still work at corners, with offsets, with realistic sources and loads?"
- "If this claim appeared in a design review, what evidence would I demand?"

## Setup

To start a fresh design run:

1. Agree on a run tag based on today's date, for example `mar17`.
2. Create a dedicated branch from current `master`: `git checkout -b autodesign/<tag>`.
3. Read the shared context:
   - `program.md` (this file)
   - `interfaces.md`
   - `master_spec.json`
   - `orchestrate.py`
4. Read the target block's local context:
   - `blocks/<block>/program.md`
   - `blocks/<block>/specs.json`
5. Verify the simulator and PDK are usable before trusting any result.
6. Create `results.tsv` inside the block directory if it does not exist yet. It is an untracked lab notebook, not a committed artifact.
7. Run `python orchestrate.py --launch` to confirm what is ready.
8. Once setup is confirmed, begin the loop and do not stop unless manually interrupted.

## What You May Change

Within the active block, you may modify or create whatever is needed to make the design real and the evaluation honest:

- `design.cir`
- `parameters.csv`
- `evaluate.py`
- `best_parameters.csv`
- `measurements.json`
- `README.md`
- `plots/`

You may:

- Change topology completely.
- Add or remove devices.
- Rewrite the optimization loop.
- Rewrite the measurement flow.
- Add stronger checks to `evaluate.py`.
- Search the web for prior art, textbooks, SKY130 examples, and debugging ideas.

## What You May Not Change

These are the hard boundaries:

- Do not edit any block `specs.json`.
- Do not edit `master_spec.json` or `interfaces.md`.
- Do not edit SKY130 PDK model files.
- Do not weaken a testbench to rescue a failing design.
- Do not keep a run whose improvement depends on measurement loopholes, missing plots, unrealistic sources, or obviously broken physics.

If you discover that the current evaluation is too weak, strengthen it. Do not exploit it.

## Block Selection

Respect the dependency graph:

- Phase 1: `bandgap`, `inamp`, `pga`, `filter`, `adc`
- Phase 2: `integration` after all Phase 1 blocks are complete

Use `python orchestrate.py` to inspect status. When all Phase 1 blocks are complete, run `python orchestrate.py --propagate` before starting `integration`.

Within Phase 1, choose the next block pragmatically. A reasonable order is:

1. `bandgap`
2. `adc`
3. `inamp`
4. `pga`
5. `filter`

But you may choose a different order if the evidence supports it.

## The Experiment Loop

Loop forever:

1. Check git state and block status.
2. Pick one concrete design hypothesis.
3. Modify the active block.
4. Commit the experiment before running it.
5. Run the block evaluation with all output redirected to `run.log`.
6. Read the metrics from the log.
7. Inspect the generated plots and operating behavior critically.
8. Record the run in `results.tsv`.
9. Keep only credible improvements.
10. Revert losers cleanly and try the next idea.
11. Push keepers so the repo always reflects the best known design.

The loop is autonomous. Do not stop to ask if you should continue. Do not ask whether the human wants another run. The human may be asleep. Continue until interrupted.

## Baseline Rule

The first run on a new block should be an honest baseline:

- simplest defensible topology
- straightforward evaluation
- no speculative hacks
- no hidden assumptions

The baseline is not supposed to win. It establishes reality.

## Evaluation Doctrine

The evaluation should be harder to satisfy than the README summary makes it look. Your evaluator is not a score generator. It is an attack surface whose job is to break weak designs.

Every run should answer:

- Does the operating point make sense?
- Are critical devices in the intended region?
- Are nodes railing or stuck?
- Does startup converge to the intended state?
- Has the signal settled before measurement?
- Are the waveform shapes physically plausible?
- Do realistic offsets, interference, loading, and source conditions still pass?
- Do corners expose hidden brittleness?
- Is the result merely "passing", or does it have margin?

Treat the following as red flags:

- exact zeros
- NaNs
- implausibly perfect rejection or noise
- gain without bandwidth
- bandwidth without phase margin
- beautiful nominal results with terrible corners
- measurements taken before settling
- outputs that only work under ideal source or load assumptions
- behavior that depends on initial conditions or lucky convergence

If any red flag appears, the burden of proof is on the design. Investigate before keeping it.

## Waveform Rule

After every run, look at the plots before trusting the numbers.

The plots are not optional cosmetics. They are evidence.

- Save plots with clear names.
- Show the waveform shape, not only extracted scalars.
- If the plot looks wrong, treat the run as suspect.
- If the plot is surprising, explain why.
- If the plot reveals an anomaly, document it instead of hiding it.

An improved score from a broken waveform is a failed run.

## Phase A: Meet Specs Honestly

First, get all target specs to pass under the block's declared evaluation.

- Focus on the most important failing spec first.
- Prefer textbook-consistent fixes before exotic tricks.
- If you are far from target, rethink topology rather than over-tuning parameters.
- If you improve one spec by silently destroying another, that is not progress.

## Phase B: Try to Break the Winner

After a block passes nominal evaluation, become more aggressive.

Minimum expectation:

- PVT sweep
- startup validation
- realistic transient behavior
- explicit margin review
- plot coverage for every required testbench

If mismatch models are available, run Monte Carlo. If the winner fails deeper verification, it is not a winner. Go back to the loop.

## README Standard

`README.md` is the engineering dashboard, not marketing.

After every keeper, update it with:

1. current status
2. measured versus target table
3. key plots with short analysis
4. design rationale
5. what changed from the previous keeper
6. failed ideas worth remembering
7. known limitations and open concerns

Do not hide ugly plots. Do not hide weak corners. Honest reporting is part of the deliverable.

## Git and Logging Discipline

- One experiment equals one git commit before the run.
- Keepers stay on the branch.
- Losers are reverted after their result is logged.
- `results.tsv` is local and untracked.
- `run.log` is disposable and untracked.
- `README.md`, design files, and evaluation code are committed.
- Push after every keeper if a remote exists.

The branch should always tell a coherent story: a sequence of increasingly better designs, not a pile of random half-fixes.

## When To Discard

Discard the run if any of the following is true:

- score is worse
- score is equal and the circuit is more complex
- score improves but the waveform evidence is dubious
- score improves only because the evaluation got softer
- the design uses unrealistic assumptions that were not previously allowed
- the circuit crashes, rails, oscillates, or depends on numerical luck

Simplicity matters. A tiny improvement that adds brittle complexity is often a bad trade.

## When You Are Stuck

Do not stop. Change tactics.

- Re-read the local `program.md`.
- Inspect more internal nodes.
- Re-run the same idea at corners instead of only nominal.
- Strengthen the evaluator and see what breaks.
- Try a simpler topology.
- Try a more conventional topology.
- Search for prior art on the exact failure mode.
- Read the README history to avoid repeating dead ends.
- Switch blocks if dependency structure allows and the current one needs fresh eyes.

## Never Stop

Once the autonomous loop begins, continue indefinitely until manually interrupted.

If you run out of obvious ideas, your default action is not to stop. Your default action is to:

- inspect the last few keepers and discards
- identify the weakest surviving claim
- design a test that could falsify it
- fix what that test exposes
- commit the result if it survives

The process is:

- design
- simulate
- inspect
- attack
- keep or discard
- repeat

That loop runs until a human stops it.
