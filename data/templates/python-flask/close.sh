#!/bin/bash
# Optional. Runs when you press Stop, with $RUNNER_PGID (start.sh's process group),
# $RUNNER_PID, $PORT and $PROJECT_DIR. Runner waits a few seconds after this and
# then kills whatever is left of the group, so this only needs to handle graceful shutdown.
kill -TERM -"$RUNNER_PGID" 2>/dev/null || true
