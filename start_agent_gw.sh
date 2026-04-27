#!/bin/bash
# Start Agent GW in the background.
# If a previous instance is running, stop it and restart.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PID_FILE="$SCRIPT_DIR/.agent_gw.pid"

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
# Set environment variable to disable console output (avoid duplication)
# Logger will detect this and only write to files
export AGENT_GW_NO_CONSOLE=1
nohup python3 agent_gw.py > /dev/null 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

echo "Agent GW started with PID: $NEW_PID"
echo "Log files:"
echo "  - Main log:  $SCRIPT_DIR/logs/agent_gw.log"
echo "  - ARF log:   $SCRIPT_DIR/logs/arf.log"
echo "  - ACF log:   $SCRIPT_DIR/logs/acf.log"
echo "  - MOQT log:  $SCRIPT_DIR/logs/moqt.log"
echo ""
echo "View logs with: tail -f $SCRIPT_DIR/logs/*.log"
echo ""
echo "Or run 'python3 agent_gw.py' directly for console output."
