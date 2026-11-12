#!/usr/bin/env bash
# Generate Python bindings from a local copy of Rithmic's R|Protocol kit.
# The kit is not redistributable, so the output stays in a git-ignored folder.
set -euo pipefail

: "${RITHMIC_KIT_DIR:?Set RITHMIC_KIT_DIR to the unpacked kit, the folder containing proto/ and etc/}"
[[ -d "$RITHMIC_KIT_DIR/proto" ]] || { echo "No proto/ folder in $RITHMIC_KIT_DIR" >&2; exit 1; }
command -v protoc >/dev/null || { echo "protoc is not installed" >&2; exit 1; }

out="$(cd "$(dirname "$0")/.." && pwd)/rithmic_kit/gen"
mkdir -p "$out"

(cd "$RITHMIC_KIT_DIR/proto" && protoc -I . --python_out="$out" ./*.proto)
(cd "$RITHMIC_KIT_DIR/samples/samples.py" && protoc -I . --python_out="$out" base.proto)

echo "Generated bindings in $out"
