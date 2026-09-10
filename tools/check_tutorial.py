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
    ("tests/transport.resc", "PASS transport: register storage", "stage1"),
    ("tests/who_am_i.resc", "PASS who_am_i: register behavior", "stage2"),
    ("tests/reference.resc", "PASS reference: WHO_AM_I baseline", "stage2"),
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
        if relative == "models/LIS2DW12.cs":
            source = reference
        if reference != source:
            raise RuntimeError("README differs from repository file: " + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    model_target = destination / "models" / "LIS2DW12.cs"
    model_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "models" / "LIS2DW12.cs", model_target)
    shutil.copytree(ROOT / "tests", destination / "tests")
    print("PASS README: reconstructed", len(seen), "files", flush=True)


def write_model_for_stage(destination, stage):
    source = (ROOT / "models" / "LIS2DW12.cs").read_text(encoding="utf-8")
    if stage == "stage1":
        source = source.replace(
            "// DS11811 Rev. 9, section 8.3: WHO_AM_I is read-only and resets to 0x44.\n"
            "            RegistersCollection.DefineRegister(0x0F, 0x44)\n"
            "                .WithValueField(0, 8, FieldMode.Read, name: \"WHO_AM_I\");",
            "// Temporary stage-1 storage. It will be replaced by WHO_AM_I.\n"
            "            RegistersCollection.DefineRegister(0x10, 0xA5)\n"
            "                .WithValueField(0, 8, name: \"TRANSPORT_TEST\");",
        )
    target = destination / "models" / "LIS2DW12.cs"
    target.write_text(source, encoding="utf-8")


def check(renode, destination):
    for index, (script, marker, stage) in enumerate(CHECKS):
        write_model_for_stage(destination, stage)
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
    print("PASS tutorial: stages 1-2 (isolated model)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
