#!/bin/bash
# Runs with the project folder as cwd. Runner sets $PORT (unique per project),
# $PROJECT_DIR, $PROJECT_ID and $RUNNER_PROJECT_DATA. Stay in the foreground: use exec.
set -e
if [ ! -d node_modules ]; then
  echo "No node_modules — installing"
  npm install
fi
# Vite: npm run dev -- --port "$PORT" --strictPort ; Next.js: npm run dev -- -p "$PORT"
# Many servers (Express, Next) read $PORT themselves.
exec npm run dev -- --port "$PORT"
