# Phronesis Scripts — What You Actually Need

**One command does almost everything:**

```powershell
powershell -File D:\HermesData\scripts\Phronesis.ps1 go
```

Or double-click: **`D:\HermesData\scripts\START-PHRONESIS.bat`**

---

## The 4 scripts that matter

| Script | When to use | What it does |
|--------|-------------|--------------|
| **`Phronesis.ps1`** | You run this | One-stop CLI: `go`, `start`, `stop`, `heal`, `status`, `dashboard` |
| **`Phronesis-Guardian.ps1`** | Runs automatically every 5 min | Auto-heals broken ports (8090/8091/8642/9119/3001) |
| **`Phronesis-Simplify-Boot.ps1`** | Once, elevated | Registers the 2 Windows tasks above |
| **`phronesis-core.json`** | Edit rarely | Model, ports, venv paths — single config |

---

## Command cheat sheet

| You want… | Run |
|-----------|-----|
| Start everything (heal + boot + test) | `Phronesis.ps1 go` |
| Start stack (heals first automatically) | `Phronesis.ps1 start` |
| Stop everything | `Phronesis.ps1 stop` |
| Discord `/reset` not responding | `Phronesis.ps1 heal -ForceGateway` |
| After editing scripts / ASCII lint fails | `Phronesis.ps1 doctor` |
| Quick check | `Phronesis.ps1 status` |
| Pretty report | `Phronesis.ps1 dashboard` |
| After optimizer broke WiFi/tasks | `Phronesis.ps1 recover` (elevated) |
| First-time Windows setup | `Phronesis.ps1 boot` (elevated) |

---

## Runs automatically (ignore these)

| Task | Trigger | Script |
|------|---------|--------|
| `Phronesis-Start-At-Logon` | Logon | `Phronesis.ps1 start` |
| `Phronesis-Guardian` | Every 5 min | `Phronesis-Heal.ps1` |

---

## Internal plumbing (you don't run these)

| File | Role |
|------|------|
| `Phronesis-Heal.ps1` | Shared auto-heal engine |
| `Phronesis-ForkGuard.ps1` | Kills wrong Python forks, starts venv services |
| `Phronesis-OneButton-Start.ps1` | Stack boot implementation |
| `Phronesis-OneButton-Stop.ps1` | Stack shutdown |
| `Start-Sovereign-Proxy-8091.ps1` | Proxy launcher (venv only) |
| `ops/02-08*.ps1` | Granular pieces called by `Phronesis.ps1` |

---

## Old names → use this instead

| Confusing old name | Use instead |
|--------------------|-------------|
| `Phronesis-OneButton-Start.ps1` | `Phronesis.ps1 start` or `go` |
| `Phronesis-Hygiene-Cycle3.ps1` | `Phronesis.ps1 heal` |
| `01-recovery.ps1` | `Phronesis.ps1 restart` |
| `05-stop-all.ps1` | `Phronesis.ps1 stop` |
| `Phronesis-Fix.ps1` / `Phronesis-Recovery.ps1` | `Phronesis.ps1 recover` |
| `Start-Hermes-Gateway-Background.ps1` | `Phronesis.ps1 gateway start` |
| `hermes_gateway_watchdog.ps1` | Guardian (archived) |

---

## Archive

Retired scripts: `D:\HermesData\scripts\archive\` (see `archive/README.md`)

## Ports

8090 brain · 8091 proxy · 8642 gateway/Discord · 9119 dashboard · 3001 workspace