#!/usr/bin/env bash
# scripts/delete-all.sh
# Reverse-order cleanup for WasteLoop AI Orchestrate resources.
# Run from the project root: bash scripts/delete-all.sh
set -e

ORCHESTRATE="venv/Scripts/orchestrate"

echo "=== WasteLoop AI: removing from active Orchestrate environment ==="

echo "--- Removing agent ---"
$ORCHESTRATE agents remove -n wasteloop_agent --kind native || true

echo "--- Removing tool ---"
$ORCHESTRATE tools remove -n find_waste_matches || true

echo "=== Cleanup complete ==="