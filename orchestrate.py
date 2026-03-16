#!/usr/bin/env python3
"""
Bio-AFE Build Orchestrator

Checks block completion status, manages dependencies, and propagates
upstream measurements to downstream blocks.

Usage:
    python orchestrate.py             # Show status of all blocks
    python orchestrate.py --launch    # Show which blocks can start now
    python orchestrate.py --propagate # Push upstream measurements downstream
"""

import json
import argparse
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
BLOCKS_DIR = PROJECT_DIR / "blocks"

# Block definitions with dependencies
BLOCKS = {
    "bandgap":     {"path": "blocks/bandgap",     "depends_on": [],          "phase": 1},
    "inamp":       {"path": "blocks/inamp",        "depends_on": [],          "phase": 1},
    "pga":         {"path": "blocks/pga",          "depends_on": [],          "phase": 1},
    "filter":      {"path": "blocks/filter",       "depends_on": [],          "phase": 1},
    "adc":         {"path": "blocks/adc",          "depends_on": [],          "phase": 1},
    "integration": {"path": "blocks/integration",  "depends_on": ["bandgap", "inamp", "pga", "filter", "adc"], "phase": 2},
}

REQUIRED_FILES = {
    "specs":        "specs.json",
    "program":      "program.md",
    "claude":       "CLAUDE.md",
    "design":       "design.cir",
    "evaluate":     "evaluate.py",
    "parameters":   "parameters.csv",
    "best_params":  "best_parameters.csv",
    "measurements": "measurements.json",
    "readme":       "README.md",
}


def get_block_status(name, block_def):
    """Determine the status of a block."""
    path = PROJECT_DIR / block_def["path"]
    status = {}

    for key, fname in REQUIRED_FILES.items():
        status[key] = (path / fname).exists()

    # Determine overall state
    if status["measurements"] and status["best_params"] and status["readme"]:
        # Check if measurements has a score
        try:
            with open(path / "measurements.json") as f:
                meas = json.load(f)
            if meas.get("score", 0) >= 0.8:
                return "COMPLETE", status
        except (json.JSONDecodeError, KeyError):
            pass
        return "READY", status
    elif status["design"] and status["evaluate"]:
        return "READY", status
    elif status["specs"] and status["program"]:
        return "SETUP", status
    else:
        return "EMPTY", status


def check_dependencies_met(name, block_def):
    """Check if all upstream dependencies are COMPLETE."""
    for dep in block_def["depends_on"]:
        dep_status, _ = get_block_status(dep, BLOCKS[dep])
        if dep_status != "COMPLETE":
            return False, dep
    return True, None


def show_status():
    """Display status of all blocks."""
    print("=" * 70)
    print("SKY130 Bio-AFE — Block Status")
    print("=" * 70)

    by_phase = {}
    for name, bdef in BLOCKS.items():
        phase = bdef["phase"]
        if phase not in by_phase:
            by_phase[phase] = []
        by_phase[phase].append(name)

    for phase in sorted(by_phase.keys()):
        parallel = "parallel" if phase == 1 else "sequential"
        print(f"\n  Phase {phase} ({parallel}):")
        for name in by_phase[phase]:
            bdef = BLOCKS[name]
            state, files = get_block_status(name, bdef)

            # Status emoji/marker
            markers = {"COMPLETE": "[DONE]", "READY": "[WORK]", "SETUP": "[SPEC]", "EMPTY": "[    ]"}
            marker = markers.get(state, "[????]")

            deps_met, missing_dep = check_dependencies_met(name, bdef)
            dep_str = ""
            if bdef["depends_on"] and not deps_met:
                dep_str = f"  (waiting on: {missing_dep})"

            # Score if available
            score_str = ""
            path = PROJECT_DIR / bdef["path"]
            if (path / "measurements.json").exists():
                try:
                    with open(path / "measurements.json") as f:
                        meas = json.load(f)
                    score_str = f"  score={meas.get('score', '?')}"
                except Exception:
                    pass

            print(f"    {marker} {name:<15s} {state:<10s}{score_str}{dep_str}")

            # Show file checklist for non-complete blocks
            if state not in ("COMPLETE",):
                missing = [k for k, v in files.items() if not v]
                if missing:
                    print(f"           missing: {', '.join(missing)}")


def show_launchable():
    """Show which blocks can be started now."""
    print("\nBlocks ready to launch:")
    any_found = False
    for name, bdef in BLOCKS.items():
        state, _ = get_block_status(name, bdef)
        if state == "COMPLETE":
            continue
        deps_met, _ = check_dependencies_met(name, bdef)
        if deps_met:
            print(f"  -> {name} (phase {bdef['phase']})")
            any_found = True
    if not any_found:
        print("  (none — all blocks complete or waiting on dependencies)")


def propagate_measurements():
    """Push upstream measurements into downstream blocks."""
    print("\nPropagating measurements...")

    # Integration depends on all phase-1 blocks
    integration_upstream = {}
    for dep_name in BLOCKS["integration"]["depends_on"]:
        dep_path = PROJECT_DIR / BLOCKS[dep_name]["path"] / "measurements.json"
        if dep_path.exists():
            with open(dep_path) as f:
                integration_upstream[dep_name] = json.load(f)
            print(f"  {dep_name} -> integration")
        else:
            print(f"  {dep_name}: measurements.json not found (skip)")

    if integration_upstream:
        out_path = PROJECT_DIR / "blocks" / "integration" / "upstream_config.json"
        with open(out_path, "w") as f:
            json.dump(integration_upstream, f, indent=2)
        print(f"  Wrote {out_path}")
    else:
        print("  No upstream measurements to propagate yet.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bio-AFE Build Orchestrator")
    parser.add_argument("--launch", action="store_true", help="Show launchable blocks")
    parser.add_argument("--propagate", action="store_true", help="Propagate upstream measurements")
    args = parser.parse_args()

    show_status()

    if args.launch:
        show_launchable()
    if args.propagate:
        propagate_measurements()
