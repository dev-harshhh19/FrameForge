"""Core package initialization and system binary discovery."""
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(local_app_data) / "Microsoft" / "WinGet" / "Links",
        Path("C:/ProgramData/chocolatey/bin"),
        Path(os.path.expanduser("~")) / "scoop" / "shims",
    ]
    for c in candidates:
        if c.exists():
            c_str = str(c)
            current_path = os.environ.get("PATH", "")
            if c_str not in current_path:
                os.environ["PATH"] = c_str + os.pathsep + current_path
