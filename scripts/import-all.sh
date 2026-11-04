#!/usr/bin/env bash
# scripts/import-all.sh
# Dependency-ordered import for WasteLoop AI Orchestrate resources.
# Run from the project root: bash scripts/import-all.sh
set -e

VENV_PYTHON="venv/Scripts/python"
ORCHESTRATE="venv/Scripts/orchestrate"

echo "=== WasteLoop AI: importing to active Orchestrate environment ==="
$ORCHESTRATE env list

echo ""
echo "--- Step 1: Import Python tool ---"
$ORCHESTRATE tools import -k python -f tools/find_waste_matches.py

echo ""
echo "--- Step 2: Import agent ---"
$ORCHESTRATE agents import -f agents/wasteloop_agent.yaml

echo ""
echo "=== Import complete. Verify with: ==="
echo "  $ORCHESTRATE tools list"
echo "  $ORCHESTRATE agents list"