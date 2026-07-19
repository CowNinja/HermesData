import subprocess, re, time, json
from pathlib import Path

def pids():
    out = subprocess.check_output(
        ["wmic", "process", "where", "name like 'python%'", "get", "ProcessId,ParentProcessId,CommandLine", "/FORMAT:LIST"],
        text=True, errors="ignore",
    )
    found = []
    cur = {}
    for line in out.splitlines() + [""]:
        if not line.strip():
            if cur:
                cl = cur.get("CommandLine") or ""
                if re.search(r"watch_comfy_delivery|comfy_delivery_daemon|post_discord_image", cl):
                    found.append(cur)
            cur = {}
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            cur[k.strip()] = v.strip()
    return found

f1 = pids()
print("found", len(f1))
for p in f1:
    print(json.dumps(p)[:300])
    pid = p.get("ProcessId")
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True)
print("killed")
time.sleep(4)
f2 = pids()
print("after4s", len(f2))
for p in f2:
    print(json.dumps(p)[:300])
