#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMMAND="${1:-setup-adapter}"

case "$COMMAND" in
    check)
        shift
        uv run python -m pokewalker_client.cli check-adapter "$@"
        ;;
    setup)
        shift
        uv run python -m pokewalker_client.cli setup-adapter "$@"
        ;;
    *)
        uv run python -m pokewalker_client.cli setup-adapter "$@"
        ;;
esac
