"""Load canonical Hermes .env for standalone scripts (fleet, agent, panel)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERMES_ROOT = Path(r"D:\HermesData")
CANONICAL_ENV = HERMES_ROOT / ".env"
_AGENT_ROOT = HERMES_ROOT / "hermes-agent"

_bootstrapped = False


def bootstrap_env(*, quiet_secrets: bool = True) -> None:
    """Load D:\\HermesData\\.env via HERMES_HOME (also ~/.hermes junction)."""
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True
    os.environ.setdefault("HERMES_HOME", str(HERMES_ROOT))
    if quiet_secrets:
        os.environ.setdefault("HERMES_QUIET_SECRETS", "1")
    try:
        if _AGENT_ROOT.is_dir() and str(_AGENT_ROOT) not in sys.path:
            sys.path.insert(0, str(_AGENT_ROOT))
        from hermes_cli.env_loader import load_hermes_dotenv

        if quiet_secrets:
            import contextlib

            with open(os.devnull, "w", encoding="utf-8") as devnull, contextlib.redirect_stderr(devnull):
                load_hermes_dotenv(hermes_home=HERMES_ROOT, project_env=None)
        else:
            load_hermes_dotenv(hermes_home=HERMES_ROOT, project_env=None)
    except Exception:
        pass