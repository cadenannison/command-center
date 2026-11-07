#!/bin/bash
# AGENTS.md must stay under 200 lines and every concrete repo path it names must exist.
# Paths containing placeholders (<...>) or globs (*) are skipped.
set -e
cd "$(dirname "$0")/.."
lines=$(wc -l < AGENTS.md)
if [ "$lines" -ge 200 ]; then echo "AGENTS.md has $lines lines (limit 199)"; exit 1; fi
missing=0
for p in $(grep -Eo '(docs|scripts|src|tests|\.claude|\.github)/[A-Za-z0-9_./-]*[A-Za-z0-9_]' AGENTS.md | sort -u); do
  case "$p" in *\<*|*\**) continue ;; esac
  if [ ! -e "$p" ]; then echo "AGENTS.md names a path that does not exist: $p"; missing=1; fi
done
exit $missing
