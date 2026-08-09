import subprocess
import time

proc = subprocess.Popen(
    ["python3", "server.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

time.sleep(2)
proc.terminate()

stdout, stderr = proc.communicate(timeout=5)

print("=== STDOUT ===")
print(stdout)
print("\n=== STDERR ===")
print(stderr)