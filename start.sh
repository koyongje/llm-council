#!/bin/bash

# LLM Council - Start script
# Usage: ./start.sh            (this PC only)
#        ./start.sh --remote   (also reachable from your other devices via Tailscale)

FRONTEND_URL="http://localhost:5173"
export LLM_COUNCIL_HOST=localhost
if [ "$1" = "--remote" ]; then
    # Frontend on the Tailscale IP only; backend stays on 127.0.0.1 behind the Vite proxy
    LLM_COUNCIL_HOST=$(tailscale ip -4 2>/dev/null | head -n1)
    if [ -z "$LLM_COUNCIL_HOST" ]; then
        echo "Tailscale is not installed or not signed in (https://tailscale.com/download)"
        exit 1
    fi
    FRONTEND_URL="http://$LLM_COUNCIL_HOST:5173"
fi

echo "Starting LLM Council..."
echo ""

# Start backend
echo "Starting backend on http://localhost:8001..."
uv run python -m backend.main &
BACKEND_PID=$!

# Wait a bit for backend to start
sleep 2

# Start frontend
echo "Starting frontend on $FRONTEND_URL..."
cd frontend
npm run dev &
FRONTEND_PID=$!

echo ""
echo "✓ LLM Council is running!"
echo "  Backend:  http://localhost:8001"
echo "  Frontend: $FRONTEND_URL"
echo ""
echo "Press Ctrl+C to stop both servers"

# Wait for Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait
