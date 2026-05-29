#!/bin/sh
# Send SIGUSR1 to any running gpu-screen-recorder to dump the replay buffer.
# Used by Moment's overlay as a fallback when in-process signal delivery fails.
killall -USR1 gpu-screen-recorder 2>/dev/null
