#!/usr/bin/env python3
import runpy
import sys

sys.argv = [sys.argv[0], "--mode", "weekly", "--execute-safe"]
runpy.run_path(
    r"D:\HermesData\scripts\vault_gardener_autonomy_suite.py",
    run_name="__main__",
)
