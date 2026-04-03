#!/bin/bash
# Start Agent GW in the background.
# If a previous instance is running, stop it and restart.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PID_FILE="$SCRIPT_DIR/.agent_gw.pid"
LOG_FILE="$SCRIPT_DIR/.agent_gw.log"

cd "$SCRIPT_DIR"

STOP_PIDS="$(pgrep -f '[p]ython3 .*agent_gw\.py' || true)"
if [ -n "$STOP_PIDS" ]; then
    for PID in $STOP_PIDS; do
        echo "Stopping existing Agent GW process: $PID"
        kill "$PID" 2>/dev/null || true
    done

    sleep 1

    for PID in $STOP_PIDS; do
        if kill -0 "$PID" 2>/dev/null; then
            echo "Forcing termination of Agent GW process: $PID"
            kill -9 "$PID" 2>/dev/null || true
        fi
    done
fi

rm -f "$PID_FILE"

echo "Starting Agent GW in background..."
nohup python3 agent_gw.py > "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

echo "Agent GW started with PID: $NEW_PID"
echo "Log file: $LOG_FILE"
