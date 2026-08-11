#!/usr/bin/env bash
# Oracle bootstrap entrypoint — see deploy/oracle/README.md
exec "$(cd "$(dirname "$0")" && pwd)/oracle/bootstrap.sh" "$@"
