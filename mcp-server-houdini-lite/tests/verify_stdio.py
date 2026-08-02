"""Launch the server exactly as the plugin config does and check it over raw JSON-RPC."""

import json
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
CMD = [
    "uv", "run", "--no-sync",
    "--directory", str(SERVER_DIR),
    "server.py",
]


def main():
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr_file:
        proc = subprocess.Popen(
            CMD,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            bufsize=1,
        )
        stdout_lines = queue.Queue()

        def read_stdout():
            try:
                for line in proc.stdout:
                    stdout_lines.put(line)
            finally:
                stdout_lines.put(None)

        reader = threading.Thread(target=read_stdout, daemon=True)
        reader.start()

        def send(msg):
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()

        def read_until(target_id, timeout=30):
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"timed out waiting for response id {target_id}")
                try:
                    line = stdout_lines.get(timeout=remaining)
                except queue.Empty as e:
                    raise TimeoutError(
                        f"timed out waiting for response id {target_id}"
                    ) from e
                if line is None:
                    raise RuntimeError("server closed the stream unexpectedly")
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == target_id:
                    return msg

        try:
            send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "verify", "version": "0"}}})
            read_until(1)
            print("initialize OK")

            send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

            send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            print("tools:", len(read_until(2)["result"]["tools"]))

            send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "bgeo_read_header",
                "arguments": {"path": "/unused/missing.bgeo.sc"}}})
            reply = read_until(3)
            print("error:", json.dumps(reply.get("error"), ensure_ascii=False))
        finally:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
            try:
                exit_code = proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                exit_code = proc.wait()
            reader.join(timeout=1)
            print("exit code:", exit_code)
            stderr_file.seek(0)
            print("stderr:", stderr_file.read()[-300:] or "(empty)")


if __name__ == "__main__":
    main()
