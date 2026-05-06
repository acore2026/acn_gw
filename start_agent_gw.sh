#!/bin/bash
# Manage Agent GW in the background.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PID_FILE="$SCRIPT_DIR/.agent_gw.pid"
APP_LOG_DIR="$SCRIPT_DIR/agent_gw/logs"
START_LOG="$SCRIPT_DIR/logs/agent_gw_start.log"
APP_LOG_DIR="$SCRIPT_DIR/logs"
PROCESS_PATTERN='[p]ython3 .*agent_gw\.py'
SERVICE_PORTS=(9001 9002 9003)

cd "$SCRIPT_DIR"

usage() {
    cat <<EOF
Usage: $0 [command]

Commands:
  start       Start Agent GW in the background if it is not already running
  restart     Stop any running Agent GW process, then start it
  stop        Stop Agent GW
  status      Show whether Agent GW is running
  stat        Alias for status
  log         Tail Agent GW log files
  logs        Alias for log
  help        Show this help message

No command defaults to: restart
EOF
}

running_pids() {
    pgrep -f "$PROCESS_PATTERN" || true
}

port_pids() {
    PORT="$1"
    {
        ss -H -ltnp 2>/dev/null || true
        ss -H -lunp 2>/dev/null || true
    } | awk -v port=":$PORT" '$4 ~ port "$" || $5 ~ port "$"' \
        | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' \
        | sort -u
}

release_service_ports() {
    RELEASE_PIDS=""

    for PORT in "${SERVICE_PORTS[@]}"; do
        PIDS="$(port_pids "$PORT")"
        if [ -n "$PIDS" ]; then
            echo "Port $PORT is occupied by PID(s): $PIDS"
            RELEASE_PIDS="$RELEASE_PIDS $PIDS"
        fi
    done

    RELEASE_PIDS="$(printf '%s\n' $RELEASE_PIDS | sort -u | xargs 2>/dev/null || true)"
    if [ -z "$RELEASE_PIDS" ]; then
        return 0
    fi

    for PID in $RELEASE_PIDS; do
        echo "Stopping process using Agent GW service port: $PID"
        kill "$PID" 2>/dev/null || true
    done

    sleep 1

    for PID in $RELEASE_PIDS; do
        if kill -0 "$PID" 2>/dev/null; then
            echo "Forcing termination of process using Agent GW service port: $PID"
            kill -9 "$PID" 2>/dev/null || true
        fi
    done
}

show_logs() {
    mkdir -p "$APP_LOG_DIR" "$SCRIPT_DIR/logs"
    shopt -s nullglob
    LOG_FILES=("$APP_LOG_DIR"/*.log "$START_LOG")
    shopt -u nullglob

    if [ "${#LOG_FILES[@]}" -eq 0 ]; then
        echo "No log files found in $APP_LOG_DIR."
        echo "Start Agent GW first with: $0 start"
        return 1
    fi

    echo "Tailing Agent GW logs. Press Ctrl+C to stop."
    tail -f "${LOG_FILES[@]}"
}

show_status() {
    PIDS="$(running_pids)"

    if [ -n "$PIDS" ]; then
        echo "Agent GW is running."
        echo "PIDs: $PIDS"
        if [ -f "$PID_FILE" ]; then
            echo "PID file: $PID_FILE ($(cat "$PID_FILE"))"
        else
            echo "PID file: missing"
        fi
        echo ""
        echo "Log files:"
        echo "  - Main log:  $APP_LOG_DIR/agent_gw.log"
        echo "  - ARF log:   $APP_LOG_DIR/arf.log"
        echo "  - ACF log:   $APP_LOG_DIR/acf.log"
        echo "  - MOQT log:  $APP_LOG_DIR/moqt.log"
        echo "  - Start log: $START_LOG"
    else
        echo "Agent GW is not running."
        if [ -f "$PID_FILE" ]; then
            echo "Removing stale PID file: $PID_FILE"
            rm -f "$PID_FILE"
        fi
        return 1
    fi
}

stop_agent_gw() {
    STOP_PIDS="$(running_pids)"
    if [ -z "$STOP_PIDS" ]; then
        echo "Agent GW is not running."
        rm -f "$PID_FILE"
        return 0
    fi

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

    rm -f "$PID_FILE"
    echo "Agent GW stopped."
}

start_agent_gw() {
    release_service_ports

    START_PIDS="$(running_pids)"
    if [ -n "$START_PIDS" ]; then
        echo "Agent GW is already running."
        echo "PIDs: $START_PIDS"
        echo "Use '$0 restart' to restart it."
        return 0
    fi

    echo "Starting Agent GW in background..."
    # Set environment variable to disable console output (avoid duplication).
    # Logger will detect this and only write to files.
    export AGENT_GW_NO_CONSOLE=1
    mkdir -p "$APP_LOG_DIR" "$SCRIPT_DIR/logs"
    nohup python3 agent_gw.py > "$START_LOG" 2>&1 &
    NEW_PID=$!

    sleep 1

    if ! kill -0 "$NEW_PID" 2>/dev/null; then
        echo "Agent GW failed to start."
        echo "Startup output: $START_LOG"
        exit 1
    fi

    echo "$NEW_PID" > "$PID_FILE"

    echo "Agent GW started with PID: $NEW_PID"
    echo "Log files:"
    echo "  - Main log:  $APP_LOG_DIR/agent_gw.log"
    echo "  - ARF log:   $APP_LOG_DIR/arf.log"
    echo "  - ACF log:   $APP_LOG_DIR/acf.log"
    echo "  - MOQT log:  $APP_LOG_DIR/moqt.log"
    echo "  - Start log: $START_LOG"
    echo ""
    echo "View logs with: $0 log"
    echo ""
    echo "Or run 'python3 agent_gw.py' directly for console output."
}

COMMAND="${1:-restart}"

case "$COMMAND" in
    start)
        start_agent_gw
        ;;
    restart)
        stop_agent_gw
        start_agent_gw
        ;;
    stop)
        stop_agent_gw
        ;;
    status|stat)
        show_status
        ;;
    log|logs)
        show_logs
        ;;
    help|-h|--help)
        usage
        ;;
    *)
        echo "Unknown command: $COMMAND"
        echo ""
        usage
        exit 2
        ;;
esac
