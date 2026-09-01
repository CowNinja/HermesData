#!/usr/bin/env python3
"""Shim. Living copy: D:\\HermesData\\scripts\\ops\\grok_inbox_consumer.py"""
from pathlib import Path
import runpy

runpy.run_path(
    str(Path(r"D:\HermesData\scripts\ops\grok_inbox_consumer.py")),
    run_name="__main__",
)
