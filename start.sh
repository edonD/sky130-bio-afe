#!/bin/bash
# ============================================================
# start.sh — Launch an autonomous bio-AFE design agent in tmux
#
# Usage (run from project root):
#   bash start.sh <block>
#
# Examples:
#   bash start.sh bandgap
#   bash start.sh inamp
#   bash start.sh adc
#   bash start.sh pga
#   bash start.sh filter
#
# The agent runs in a detached tmux session.
#   To watch:   tmux attach -t <block>
#   To detach:  Ctrl+B, D
#   To stop:    tmux kill-session -t <block>
# ============================================================

BLOCK="${1:?Usage: bash start.sh <block_name>}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BLOCK_DIR="$PROJECT_DIR/blocks/$BLOCK"

echo ""
echo "================================================"
echo "  Bio-AFE Agent: $BLOCK"
echo "  Block dir:     $BLOCK_DIR"
echo "  $(date)"
echo "================================================"
echo ""

# Verify block exists
if [ ! -f "$BLOCK_DIR/program.md" ] || [ ! -f "$BLOCK_DIR/specs.json" ]; then
    echo "ERROR: $BLOCK_DIR/program.md or specs.json not found."
    echo "Available blocks:"
    ls "$PROJECT_DIR/blocks/"
    exit 1
fi

# Verify tools
echo "Checking tools..."
for tool in ngspice python3 claude git tmux; do
    if command -v $tool &>/dev/null; then
        echo "  $tool: OK"
    else
        echo "  $tool: MISSING!"
        exit 1
    fi
done
echo ""

# Kill existing session if any
tmux kill-session -t "$BLOCK" 2>/dev/null || true

# Write the prompt to a file (avoids quoting hell with tmux + bash)
cat > "/tmp/prompt_${BLOCK}.txt" << 'PROMPT_EOF'
You are an autonomous analog circuit designer. You will work indefinitely until manually stopped. You are running with --dangerously-skip-permissions so you can execute any tool without asking.

FIRST — Read these files in order. Do not skip any.

1. Read ../../program.md — the global mission, experiment loop, self-evaluation doctrine, Phase A/B structure, and git discipline. This is the controlling document.
2. Read program.md — everything about THIS block: purpose, evaluated parameters, testbenches with pass/fail criteria, plot analysis checklist, experiment loop specifics, logging format, and design freedom.
3. Read specs.json — your pass/fail targets. NEVER modify this file.
4. Read ../../interfaces.md — signal contracts between blocks and biosignal characteristics.
5. Read ../../master_spec.json — system-level context and block dependency graph.

THEN — Begin the autonomous experiment loop as defined in program.md:

1. Research the circuit topology (web search for SKY130 examples, textbook designs, ISSCC papers).
2. Create design.cir (parametric SPICE netlist), parameters.csv, and evaluate.py.
3. Run evaluate.py, study the plots, keep or discard, log in results.tsv.
4. Repeat forever. Each iteration: one change, one commit, one run, one decision.

CRITICAL RULES:
- NEVER STOP. Loop forever. The human is away and expects you to keep working.
- After EVERY run, study the plots. If the waveforms look wrong, the design is wrong regardless of what the score says.
- Never game the evaluation by modifying PDK models or fabricating results.
- Be honest. If something looks weird in a plot, show it in README.md and explain it.
- Commit and push after every keeper. Revert losers with git reset --hard HEAD~1.
- README.md is your final deliverable. Update it after every improvement with plots and analysis.
- Log every run in results.tsv (tab-separated, not committed).
- Phase A: meet all specs (score = 1.0). Phase B: PVT corners, Monte Carlo, margin improvement, all plots.

IMPORTANT NGSPICE NOTES FOR SKY130:
- Devices are subcircuits: use X prefix (X1 ... sky130_fd_pr__nfet_01v8), NOT M prefix.
- Models are at: /home/ubuntu/workspace/sky130_models/ (symlinked as sky130_models/ in this directory).
- Use: .lib "sky130_models/sky130.lib.spice" tt
- Run ngspice from THIS block directory (not from /tmp).
- PNP BJTs available: sky130_fd_pr__pnp_05v5_w3p40l3p40 (c b e s — 4 terminals).
- Poly resistors: sky130_fd_pr__res_xhigh_po_0p69 (r0 r1 b — 3 terminals).
- MIM caps: sky130_fd_pr__cap_mim_m3_1 (c0 c1 — with w and l parameters).

START NOW. Read the files, then begin designing.
PROMPT_EOF

# Start in detached tmux
tmux new-session -d -s "$BLOCK" \
    "cd '$BLOCK_DIR' && claude --dangerously-skip-permissions -p \"\$(cat /tmp/prompt_${BLOCK}.txt)\""

sleep 2

# Verify it launched
if tmux has-session -t "$BLOCK" 2>/dev/null; then
    echo "================================================"
    echo "  AGENT STARTED: $BLOCK"
    echo "================================================"
    echo ""
    tmux ls
    echo ""
    echo "  To watch:   tmux attach -t $BLOCK"
    echo "  To detach:  Ctrl+B, D"
    echo "  To stop:    tmux kill-session -t $BLOCK"
    echo "  Progress:   cat $BLOCK_DIR/README.md"
    echo "  Git log:    cd $BLOCK_DIR && git log --oneline -5"
    echo ""
else
    echo "ERROR: tmux session failed to start!"
    echo "Try manually: cd $BLOCK_DIR && claude --dangerously-skip-permissions"
fi
