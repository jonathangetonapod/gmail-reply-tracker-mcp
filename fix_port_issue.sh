#!/bin/bash
# Fix for "Address already in use" error during OAuth

echo "🔍 Checking what's using port 8080..."
PROCESS=$(lsof -ti :8080)

if [ -z "$PROCESS" ]; then
    echo "✓ Port 8080 is free - you can run auto_oauth.py now"
else
    echo "Found process using port 8080: PID $PROCESS"
    echo "Killing process..."
    kill -9 $PROCESS
    sleep 1

    # Verify it's killed
    if lsof -ti :8080 > /dev/null 2>&1; then
        echo "✗ Failed to kill process - you may need to run with sudo"
        echo "Try: sudo kill -9 $PROCESS"
    else
        echo "✓ Port 8080 is now free - you can run auto_oauth.py now"
    fi
fi
