#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/xilinx/jupyter_notebooks/stage4
BACKUP=/tmp/stage4_board_cleanup_20261030

if [[ "$(realpath "$ROOT")" != "$ROOT" ]]; then
    echo "unexpected project path" >&2
    exit 1
fi

mkdir -p "$BACKUP/cache" "$BACKUP/old_evidence"

move_item() {
    local source="$1"
    local destination="$2"
    if [[ -e "$source" ]]; then
        mv "$source" "$destination"
    fi
}

move_item "$ROOT/.ipynb_checkpoints" "$BACKUP/cache/root_checkpoints"
move_item "$ROOT/__pycache__" "$BACKUP/cache/root_pycache"
move_item "$ROOT/notebooks/.ipynb_checkpoints" "$BACKUP/cache/notebooks_checkpoints"
move_item "$ROOT/tests/__pycache__" "$BACKUP/cache/tests_pycache"
move_item "$ROOT/tools/__pycache__" "$BACKUP/cache/tools_pycache"
move_item "$ROOT/evidence" "$BACKUP/old_evidence/evidence"
move_item "/home/xilinx/jupyter_notebooks/stage4_traffic_light.ipynb" "$BACKUP/stage4_traffic_light.ipynb"
move_item "/home/xilinx/jupyter_notebooks/ov5640_lcd_7010" "$BACKUP/ov5640_lcd_7010"

mkdir -p "$ROOT/evidence"
echo "board cleanup complete: $BACKUP"
