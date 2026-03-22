#!/usr/bin/env python3
"""Bootstrap Workflow 3 runtime dependencies into a project-local virtualenv."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PHASE_DEPENDENCIES: dict[str, dict[str, Any]] = {
    "figure": {
        "python_packages": {
            "matplotlib": "matplotlib",
            "seaborn": "seaborn",
            "numpy": "numpy",
            "pandas": "pandas",
        },
        "commands": [],
        "playwright_browser": False,
    },
    "illustration": {
        "python_packages": {
            "playwright": "playwright>=1.52.0,<2",
        },
        "commands": [],
        "playwright_browser": True,
    },
    "write": {
        "python_packages": {},
        "commands": ["curl"],
        "playwright_browser": False,
    },
    "compile": {
        "python_packages": {},
        "commands": ["pdflatex", "latexmk", "bibtex", "pdfinfo", "pdftotext"],
        "playwright_browser": False,
    },
}

PHASE_ORDER = ["figure", "illustration", "write", "compile"]
PHASE_ALIASES = {"workflow3": PHASE_ORDER}

APT_PHASE_PACKAGES: dict[str, list[str]] = {
    "base": ["python3-venv"],
    "write": ["curl"],
    "compile": ["texlive-full", "latexmk", "poppler-utils", "curl"],
}

BREW_PHASE_PACKAGES: dict[str, list[str]] = {
    "write": ["curl"],
    "compile": ["poppler", "curl"],
}

BREW_PHASE_CASKS: dict[str, list[str]] = {
    "compile": ["mactex-no-gui"],
}

AUTO_INSTALL_ENV = "PAPER_AUTO_INSTALL"
VENV_DIR_ENV = "PAPER_VENV_DIR"
SYSTEM_INSTALL_ENV = "PAPER_SYSTEM_INSTALL"
ACTIVE_ENV = "ARIS_PAPER_RUNTIME_ACTIVE"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        default="workflow3",
        choices=["workflow3", *PHASE_ORDER],
        help="Dependency group to ensure.",
    )
    parser.add_argument(
        "--work-dir",
        default=".",
        help="Project working directory. Defaults to the current directory.",
    )
    parser.add_argument(
        "--latex-package",
        help="Optional tlmgr package name to install after compile failures.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    work_dir = Path(args.work_dir).resolve()
    try:
        if args.latex_package:
            ensure_latex_package(args.latex_package, work_dir=work_dir)
            return 0

        state = ensure_runtime(args.phase, work_dir=work_dir)
        _log(
            "Paper runtime ready: "
            f"phase={state['requested_phase']} "
            f"venv={state['venv_python']} "
            f"package_manager={state['package_manager'] or 'none'}"
        )
        return 0
    except Exception as exc:
        _log(f"Bootstrap failed: {exc}")
        return 1


def maybe_reexec_for_phase(phase: str, *, work_dir: Path | None = None) -> None:
    work_dir = Path(work_dir or Path.cwd()).resolve()
    state = ensure_runtime(phase, work_dir=work_dir)
    target_python = Path(state["venv_python"]).resolve()
    current_python = Path(sys.executable).resolve()
    if current_python == target_python:
        return
    env = os.environ.copy()
    env[ACTIVE_ENV] = "1"
    os.execve(str(target_python), [str(target_python), *sys.argv], env)


def ensure_runtime(phase: str, *, work_dir: Path | None = None) -> dict[str, Any]:
    work_dir = Path(work_dir or Path.cwd()).resolve()
    requested_phase = phase
    phases = _expand_phases(phase)
    state_dir = work_dir / "refine-logs"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "PAPER_RUNTIME_STATE.json"

    auto_install = _env_bool(AUTO_INSTALL_ENV, True)
    system_install = os.getenv(SYSTEM_INSTALL_ENV, "auto").strip().lower() or "auto"
    if system_install not in {"auto", "off"}:
        system_install = "auto"

    venv_dir = _resolve_venv_dir(work_dir)
    package_manager = _detect_package_manager()
    state: dict[str, Any] = {
        "generated_at": _utc_now(),
        "requested_phase": requested_phase,
        "resolved_phases": phases,
        "work_dir": str(work_dir),
        "venv_dir": str(venv_dir),
        "venv_python": str(_venv_python(venv_dir)),
        "current_python": sys.executable,
        "auto_install": auto_install,
        "system_install": system_install,
        "package_manager": package_manager,
        "python_packages": {},
        "commands": {},
        "playwright_browser_installed": False,
        "status": "ok",
    }

    try:
        venv_python = _ensure_venv(
            venv_dir,
            auto_install=auto_install,
            package_manager=package_manager,
            system_install=system_install,
        )
        state["venv_python"] = str(venv_python)

        required_packages = _required_python_packages(phases)
        if required_packages:
            _ensure_python_packages(
                venv_python,
                required_packages,
                auto_install=auto_install,
            )
        state["python_packages"] = _query_python_packages(
            venv_python,
            list(required_packages.keys()),
        )

        if "illustration" in phases:
            state["playwright_browser_installed"] = _ensure_playwright_browser(
                venv_python,
                auto_install=auto_install,
                system_install=system_install,
                package_manager=package_manager,
            )

        required_commands = _required_commands(phases)
        if required_commands:
            _ensure_system_commands(
                required_commands,
                phases=phases,
                auto_install=auto_install,
                system_install=system_install,
                package_manager=package_manager,
            )
        state["commands"] = {
            command: bool(shutil.which(command)) for command in required_commands
        }

        _write_state(state_path, state)
        return state
    except Exception as exc:
        state["status"] = "error"
        state["error"] = str(exc)
        _write_state(state_path, state)
        raise


def ensure_latex_package(package_name: str, *, work_dir: Path | None = None) -> None:
    work_dir = Path(work_dir or Path.cwd()).resolve()
    ensure_runtime("compile", work_dir=work_dir)
    tlmgr = shutil.which("tlmgr")
    if not tlmgr:
        raise RuntimeError(
            "tlmgr is not available after compile bootstrap. Install TeX Live first."
        )
    _log(f"Installing LaTeX package via tlmgr: {package_name}")
    _run_command([tlmgr, "install", package_name], cwd=work_dir)


def _expand_phases(phase: str) -> list[str]:
    members = PHASE_ALIASES.get(phase, [phase])
    resolved: list[str] = []
    for item in members:
        if item not in resolved:
            resolved.append(item)
    return resolved


def _resolve_venv_dir(work_dir: Path) -> Path:
    raw = os.getenv(VENV_DIR_ENV, ".venv").strip() or ".venv"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = work_dir / path
    return path.resolve()


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _required_python_packages(phases: list[str]) -> dict[str, str]:
    packages: dict[str, str] = {}
    for phase in phases:
        packages.update(PHASE_DEPENDENCIES[phase]["python_packages"])
    return packages


def _required_commands(phases: list[str]) -> list[str]:
    commands: list[str] = []
    for phase in phases:
        for command in PHASE_DEPENDENCIES[phase]["commands"]:
            if command not in commands:
                commands.append(command)
    return commands


def _ensure_venv(
    venv_dir: Path,
    *,
    auto_install: bool,
    package_manager: str | None,
    system_install: str,
) -> Path:
    python_path = _venv_python(venv_dir)
    if python_path.exists():
        return python_path
    if not auto_install:
        raise RuntimeError(
            f"Virtualenv missing at {venv_dir}. Set {AUTO_INSTALL_ENV}=true to allow bootstrap."
        )
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    _log(f"Creating project virtualenv at {venv_dir}")
    try:
        _run_command([sys.executable, "-m", "venv", str(venv_dir)])
    except subprocess.CalledProcessError:
        if package_manager == "apt" and system_install == "auto":
            _ensure_system_packages(
                packages=list(APT_PHASE_PACKAGES["base"]),
                auto_install=auto_install,
                package_manager=package_manager,
            )
            _run_command([sys.executable, "-m", "venv", str(venv_dir)])
        else:
            raise
    if not python_path.exists():
        raise RuntimeError(f"Virtualenv creation failed: {python_path} not found")
    return python_path


def _ensure_python_packages(
    venv_python: Path,
    required_packages: dict[str, str],
    *,
    auto_install: bool,
) -> None:
    missing = [
        spec
        for module, spec in required_packages.items()
        if not _python_module_available(venv_python, module)
    ]
    if not missing:
        return
    if not auto_install:
        raise RuntimeError(
            "Missing Python packages in project virtualenv: " + ", ".join(missing)
        )
    _log("Installing Python packages into project virtualenv: " + ", ".join(missing))
    _run_command([str(venv_python), "-m", "pip", "install", *missing])


def _ensure_playwright_browser(
    venv_python: Path,
    *,
    auto_install: bool,
    system_install: str,
    package_manager: str | None,
) -> bool:
    if _playwright_browser_installed():
        return True
    if not auto_install:
        raise RuntimeError(
            "Playwright Chromium is missing. Set PAPER_AUTO_INSTALL=true to allow bootstrap."
        )
    cmd = [str(venv_python), "-m", "playwright", "install", "chromium"]
    if platform.system() == "Linux" and system_install == "auto" and package_manager == "apt":
        cmd = [str(venv_python), "-m", "playwright", "install", "--with-deps", "chromium"]
    _log("Installing Playwright Chromium")
    _run_command(cmd)
    return _playwright_browser_installed()


def _ensure_system_commands(
    commands: list[str],
    *,
    phases: list[str],
    auto_install: bool,
    system_install: str,
    package_manager: str | None,
) -> None:
    missing = [command for command in commands if not shutil.which(command)]
    if not missing:
        return
    if system_install != "auto":
        raise RuntimeError(
            "Missing system commands: "
            + ", ".join(missing)
            + f". Set {SYSTEM_INSTALL_ENV}=auto to allow bootstrap."
        )
    packages = _packages_for_missing_commands(phases, package_manager)
    if not packages and missing:
        raise RuntimeError(
            "Missing system commands and no supported package manager was detected: "
            + ", ".join(missing)
        )
    _ensure_system_packages(
        packages=packages,
        auto_install=auto_install,
        package_manager=package_manager,
    )
    still_missing = [command for command in commands if not shutil.which(command)]
    if still_missing:
        raise RuntimeError(
            "System bootstrap did not provide required commands: "
            + ", ".join(still_missing)
        )


def _packages_for_missing_commands(
    phases: list[str],
    package_manager: str | None,
) -> list[str]:
    if package_manager == "apt":
        packages: list[str] = []
        if "write" in phases:
            packages.extend(APT_PHASE_PACKAGES["write"])
        if "compile" in phases:
            packages.extend(APT_PHASE_PACKAGES["compile"])
        return _dedupe(packages)
    if package_manager == "brew":
        packages: list[str] = []
        if "write" in phases:
            packages.extend(BREW_PHASE_PACKAGES["write"])
        if "compile" in phases:
            packages.extend(BREW_PHASE_PACKAGES["compile"])
            packages.extend(BREW_PHASE_CASKS["compile"])
        return _dedupe(packages)
    return []


def _ensure_system_packages(
    *,
    packages: list[str],
    auto_install: bool,
    package_manager: str | None,
) -> None:
    packages = _dedupe(packages)
    if not packages:
        return
    if not auto_install:
        raise RuntimeError(
            "Missing system packages: " + ", ".join(packages)
        )
    if package_manager == "apt":
        prefix = _sudo_prefix()
        _log("Installing apt packages: " + ", ".join(packages))
        _run_command([*prefix, "apt-get", "update"])
        _run_command([*prefix, "apt-get", "install", "-y", *packages])
        return
    if package_manager == "brew":
        formulae = [pkg for pkg in packages if pkg not in BREW_PHASE_CASKS["compile"]]
        casks = [pkg for pkg in packages if pkg in BREW_PHASE_CASKS["compile"]]
        if casks:
            _log("Installing brew casks: " + ", ".join(casks))
            _run_command(["brew", "install", "--cask", *casks])
        if formulae:
            _log("Installing brew formulae: " + ", ".join(formulae))
            _run_command(["brew", "install", *formulae])
        return
    raise RuntimeError(
        "Automatic system package installation is only supported on apt-get and brew hosts."
    )


def _sudo_prefix() -> list[str]:
    if os.name == "nt":
        return []
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return []
    if shutil.which("sudo"):
        return ["sudo"]
    return []


def _python_module_available(venv_python: Path, module: str) -> bool:
    cmd = [
        str(venv_python),
        "-c",
        "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)",
        module,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode == 0


def _query_python_packages(venv_python: Path, modules: list[str]) -> dict[str, str | None]:
    if not modules:
        return {}
    script = (
        "import importlib.metadata, json, sys\n"
        "result = {}\n"
        "for name in sys.argv[1:]:\n"
        "    try:\n"
        "        result[name] = importlib.metadata.version(name)\n"
        "    except importlib.metadata.PackageNotFoundError:\n"
        "        result[name] = None\n"
        "print(json.dumps(result))\n"
    )
    result = subprocess.run(
        [str(venv_python), "-c", script, *modules],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {name: None for name in modules}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {name: None for name in modules}


def _playwright_browser_installed() -> bool:
    custom = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    candidates: list[Path] = []
    if custom:
        candidates.append(Path(custom).expanduser())
    home = Path.home()
    candidates.extend(
        [
            home / ".cache" / "ms-playwright",
            home / "Library" / "Caches" / "ms-playwright",
            home / "AppData" / "Local" / "ms-playwright",
        ]
    )
    for base in candidates:
        if not base.exists():
            continue
        for item in base.iterdir():
            name = item.name.lower()
            if name.startswith("chromium-") or name.startswith("chromium_headless_shell-"):
                return True
    return False


def _detect_package_manager() -> str | None:
    if platform.system() == "Darwin" and shutil.which("brew"):
        return "brew"
    if shutil.which("apt-get"):
        return "apt"
    return None


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run_command(cmd: list[str], *, cwd: Path | None = None) -> None:
    _log("Running: " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(message: str) -> None:
    print(f"[paper-runtime] {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
