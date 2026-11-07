#!/bin/bash
set -e
chmod +x scripts/hooks/* scripts/*.sh
git config core.hooksPath scripts/hooks
echo "Git hooks installed (core.hooksPath=scripts/hooks)."
