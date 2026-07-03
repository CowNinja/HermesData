"""Load Hermes + workspace .env for standalone scripts (fleet, agent, panel)."""
from __future__ import annotations

import sys
from pathlib import Path

HERMES_ROOT = Path(r"D:\HermesData")
WORKSPACE_ENV = HERMES_ROOT / "hermes-workspace" / ".env"
_AGENT_ROOT = HERMES_ROOT / "hermes-agent"

_bootstrapped = False


def bootstrap_env() -> None:
    """Load ~/.hermes/.env then hermes-workspace/.env (fills missing keys)."""
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True
    try:
        if _AGENT_ROOT.is_dir() and str(_AGENT_ROOT) not in sys.path:
            sys.path.insert(0, str(_AGENT_ROOT))
        from hermes_cli.env_loader import load_hermes_dotenv

        load_hermes_dotenv(project_env=WORKSPACE_ENV)
    except Exception:
        pass