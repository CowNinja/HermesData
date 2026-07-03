# Phronesis ops — active scripts only

Archived originals: `D:\HermesData\scripts\archive\`

| Script | Purpose |
|--------|---------|
| `phronesis-start.bat` | Desktop launcher: Guardian → OneButton → Dashboard |
| `01-recovery.ps1` | Full recovery (wraps OneButton Stop + Start) |
| `02-start-llama.ps1` | llama-server only (defaults from phronesis-core.json) |
| `03-start-proxy.ps1` | sovereign proxy only |
| `04-status.ps1` | Port + venv health |
| `05-stop-all.ps1` | Stop stack (wraps OneButton-Stop) |
| `06-smoke-test.ps1` | End-to-end inference test |
| `07-switch-model.ps1` | Model swap (blocked when rotation locked) |
| `08-download-model.ps1` | Download GGUF |
| `Phronesis-Dashboard.ps1` | Human-readable health dashboard |
| `Phronesis-Recovery.ps1` | Elevated admin recovery (WiFi + boot tasks + restart) |
| `Phronesis-Fix.ps1` | Wrapper → Phronesis-Recovery.ps1 |
| `Phronesis-Hygiene-Cycle3.ps1` | **Stub** → Guardian + Dashboard (full script in archive) |