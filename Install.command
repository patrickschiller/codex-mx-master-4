#!/bin/sh
set -eu
task_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$task_dir/codex-mx" install --apply --restart-logitech
printf '\nPress Enter to close this window.\n'
read -r task_reply
