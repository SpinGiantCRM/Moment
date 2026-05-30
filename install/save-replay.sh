#!/bin/sh
# Send SIGUSR1 to a running gpu-screen-recorder to dump the replay buffer.
# Used by Moment's overlay as a fallback when in-process signal delivery fails.
# Uses PID-based signalling (pgrep + kill) for precise targeting.
GSR_PID=$(pgrep -x gpu-screen-recorder 2>/dev/null | head -1)
if [ -n "$GSR_PID" ]; then
    kill -USR1 "$GSR_PID"
fi
