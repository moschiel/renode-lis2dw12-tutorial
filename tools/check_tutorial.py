"""Rebuild tutorial files from README blocks and run the documented checks."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLOCK = re.compile(
    r"<!-- tutorial-file: ([^>]+) -->\s*\n"
    r"```[^\n]*\n(.*?)\n```", re.DOTALL
)
CHECKS = [
    ("tests/stage1.resc", "PASS stage1: transport and register storage"),
    ("tests/reference.resc", "PASS reference: WHO_AM_I baseline"),
]


def materialize(destination):
    blocks = BLOCK.findall((ROOT / "README.md").read_text(encoding="utf-8"))
    if not blocks:
        raise RuntimeError("No tutorial-file blocks found in README")
    seen = set()
    for relative, source in blocks:
        relative = relative.strip()
        target = (destination / relative).resolve()
        if not target.is_relative_to(destination.resolve()) or relative in seen:
            raise RuntimeError("Unsafe or duplicate tutorial path: " + relative)
        seen.add(relative)
        source = source.rstrip() + "\n"
        reference = (ROOT / relative).read_text(encoding="utf-8")
        if reference != source:
            raise RuntimeError("README differs from repository file: " + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    shutil.copytree(ROOT / "tests", destination / "tests")
    print("PASS README: reconstructed", len(seen), "files", flush=True)


def check(renode, destination):
    for index, (script, marker) in enumerate(CHECKS):
        command = [
            renode, "--config", str(destination / ("renode-" + str(index) + ".config")),
            "--console", "--disable-gui", "--plain", script,
        ]
        result = subprocess.run(
            command, cwd=destination, input="quit\n", text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=60,
        )
        # Monitor errors can still produce exit code zero. Require the final
        # marker and reject explicit compilation/command/assertion failures.
        failed = re.search(
            r"AssertionError|There was an error|Errors during compilation|"
            r"Could not compile|No such command|Traceback|Fatal error",
            result.stdout, re.IGNORECASE,
        )
        if result.returncode != 0 or marker not in result.stdout or failed:
            raise RuntimeError(script + " failed:\n" + result.stdout)
        print(marker, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renode", default="renode", help="Renode executable")
    args = parser.parse_args()
    executable = shutil.which(args.renode)
    if executable is None:
        parser.error("Renode not found: " + args.renode)
    try:
        with tempfile.TemporaryDirectory(prefix="lis2dw12-tutorial-") as temporary:
            destination = Path(temporary)
            materialize(destination)
            check(executable, destination)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print("FAIL:", error, file=sys.stderr)
        return 1
    print("PASS tutorial: stage 1 (isolated models; no firmware)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
