#!/bin/bash
# Runs with the project folder as cwd. Runner sets $PORT (unique per project),
# $PROJECT_DIR, $PROJECT_ID and $RUNNER_PROJECT_DATA. Stay in the foreground: use exec.
set -e
if [ ! -x .venv/bin/python ]; then
  echo "No .venv — creating one"
  python3 -m venv .venv
  if [ -f requirements.txt ]; then .venv/bin/pip install -r requirements.txt; fi
fi
# The app must listen on $PORT, e.g. app.run(port=int(os.environ.get("PORT", 5000))).
# If it hard-codes its port, use the flask CLI instead:
#   exec .venv/bin/flask --app app run --port "$PORT" --debug
exec .venv/bin/python app.py
