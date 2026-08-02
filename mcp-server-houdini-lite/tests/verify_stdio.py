"""Launch the server exactly as the plugin config does and check it over raw JSON-RPC."""

import json
import subprocess
import sys

CMD = [
    "uv", "run", "--no-sync",
    "--directory", r"D:\dev\houdini-tools\mcp-server-houdini-lite",
    "server.py",
]

proc = subprocess.Popen(CMD, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, bufsize=1)


def send(msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def read_until(target_id):
    while True:
        line = proc.stdout.readline()
        if not line:
            raise SystemExit("server closed the stream unexpectedly")
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == target_id:
            return msg


send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-11-25", "capabilities": {},
    "clientInfo": {"name": "verify", "version": "0"}}})
read_until(1)
print("initialize OK")

send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
print("tools:", len(read_until(2)["result"]["tools"]))

send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
    "name": "bgeo_read_header", "arguments": {"path": "D:/nope/missing.bgeo.sc"}}})
reply = read_until(3)
print("error:", json.dumps(reply.get("error"), ensure_ascii=False))

proc.stdin.close()
print("exit code:", proc.wait(timeout=30))
print("stderr:", proc.stderr.read()[-300:] or "(empty)")
