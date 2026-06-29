# Phronesis Operations — Crash Recovery & Ops Scripts
# Directory: D:\HermesData\scripts\ops\
#
# Quick reference:
#   01-recovery.ps1    — Full stack crash recovery (kill zombies + all services)
#   02-start-llama.ps1 — Start llama.cpp backend only (port 8090)
#   03-start-proxy.ps1 — Start MoE gateway proxy only (port 8091)
#   04-status.ps1      — Health-check all running services
#   05-stop-all.ps1    — Kill all managed processes
#   06-smoke-test.ps1  — End-to-end test: proxy → llama.cpp → response
#   07-switch-model.ps1 — Swap which GGUF the llama.cpp backend serves (no proxy restart)
#   08-download-model.ps1 — Download a GGUF from HuggingFace or direct URL
#
# For full details, environment variables, and troubleshooting see README.md
