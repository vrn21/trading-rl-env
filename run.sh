#!/bin/bash
set -e

# Save original stdout to FD 3, then redirect all subsequent script output to stderr
# This guarantees that nothing pollutes the stdout JSON-RPC stream
exec 3>&1
exec 1>&2

echo "Starting PostgreSQL..."
su postgres -c "/usr/lib/postgresql/15/bin/postgres -D /var/lib/postgresql/15/main -c config_file=/etc/postgresql/15/main/postgresql.conf" > /dev/null 2>&1 &

echo "Waiting for PostgreSQL..."
until pg_isready -h localhost -U postgres -d simdb > /dev/null 2>&1; do sleep 1; done

echo "Starting QuantReplay..."
cd /market-simulator/quod
export INSTANCE_ID=XETRA
export PREFIX=QUOD
export LOG_DIR=/market-simulator/quod/data/log
/entrypoint_os.sh > /dev/null 2>&1 &

echo "Waiting for QuantReplay..."
until curl -sf http://localhost:9050/api/venuestatus > /dev/null 2>&1; do sleep 2; done

echo "QuantReplay ready. Execing into MCP server..."
cd /mcp_server

# Restore original stdout for the MCP server, close FD 3
exec 1>&3
exec 3>&-

# Replace the shell process with the MCP server so it directly inherits
# the container's real stdin and stdout.
exec hud dev env:env --stdio
