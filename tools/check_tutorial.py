"""Rebuild tutorial files from README blocks and run the documented checks."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

# Exemplo de comando para parar em um certo ponto do tutorial
# python tools\check_tutorial.py --workspace ..\my-lis2dw12 --stage 2 (vai parar na secao 2)

ROOT = Path(__file__).resolve().parents[1]
BLOCK = re.compile(
    r"<!-- tutorial-file: ([^>]+) -->\s*\n"
    r"```[^\n]*\n(.*?)\n```", re.DOTALL
)
STAGE_MODEL = re.compile(
    r"<!-- tutorial-stage-model: stage1 -->\s*\n"
    r"```csharp\n(.*?)\n```", re.DOTALL
)
CHECKS = [
    ("tests/transport.resc", "PASS transport: register storage", "stage1"),
    ("tests/who_am_i.resc", "PASS who_am_i: register behavior", "stage2"),
    ("tests/reference.resc", "PASS reference: WHO_AM_I baseline", "stage2"),
    ("tests/xyz_read.resc", "PASS xyz_read: signed XYZ output registers", "stage3"),
    ("tests/firmware_xyz.resc", "PASS firmware: WHO_AM_I and XYZ sample", "stage3"),
    ("tests/auto_increment.resc", "PASS auto_increment: IF_ADD_INC behavior", "stage4"),
    ("tests/compare_models.resc", "PASS compare: custom and reference identity/XYZ access", "stage4"),
    ("tests/firmware_custom.resc", "PASS firmware: WHO_AM_I, XYZ, and IF_ADD_INC", "stage4"),
    ("tests/firmware_reference.resc", "PASS reference firmware: I2C transactions complete; stimulus difference observed", "stage4"),
]
STAGE_ORDER = {"stage1": 1, "stage2": 2, "stage3": 3, "stage4": 4}


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
    shutil.copytree(
        ROOT / "firmware", destination / "firmware",
        ignore=shutil.ignore_patterns("old-lis2dw12-demo"),
    )
    shutil.copy2(ROOT / "scripts" / "uart_capture.py",
                 destination / "scripts" / "uart_capture.py")
    print("PASS README: reconstructed", len(seen), "files", flush=True)


def write_model_for_stage(destination, stage):
    if stage == "stage4":
        source = (ROOT / "models" / "LIS2DW12.cs").read_text(encoding="utf-8")
    elif stage == "stage3":
        source = (ROOT / "models" / "LIS2DW12.cs").read_text(encoding="utf-8")
        control2 = re.compile(
            r"            // DS11811 Rev\. 9, datasheet section 8\.5: this stage models only IF_ADD_INC\.\n"
            r"            RegistersCollection\.DefineRegister\(0x21, 0x04\)\.WithFlag\(2, out automaticAddressIncrement, name: \"IF_ADD_INC\"\);\n"
        )
        source, removed = control2.subn("", source, count=1)
        if removed != 1:
            raise RuntimeError("Could not remove stage-4 CTRL2 definition")
        source = source.replace(
            "        public byte Control2 => automaticAddressIncrement.Value ? (byte)0x04 : (byte)0x00;\n",
            "",
        )
        source = source.replace("                IncrementSelectedRegister();\n", "")
        increment_helper = re.compile(
            r"        private void IncrementSelectedRegister\(\)\n"
            r"        \{\n"
            r"(?:.*\n)*?        \}\n\n"
        )
        source, removed = increment_helper.subn("", source, count=1)
        if removed != 1:
            raise RuntimeError("Could not remove stage-4 increment helper")
        source = source.replace("        private IFlagRegisterField automaticAddressIncrement;\n", "")
    else:
        document = (ROOT / "README.md").read_text(encoding="utf-8")
        match = STAGE_MODEL.search(document)
        if match is None:
            raise RuntimeError("Stage-1 model block not found")
        source = match.group(1).rstrip() + "\n"
        if stage == "stage2":
            temporary = (
                "// Temporary stage-1 storage. It will be replaced by WHO_AM_I.\n"
                "            RegistersCollection.DefineRegister(0x10, 0xA5).WithValueField(0, 8, name: \"TRANSPORT_TEST\");"
            )
            identity = (
                "// DS11811 Rev. 9, section 8.3: WHO_AM_I is read-only and resets to 0x44.\n"
                "            RegistersCollection.DefineRegister(0x0F, 0x44).WithValueField(0, 8, FieldMode.Read, name: \"WHO_AM_I\");"
            )
            if temporary not in source:
                raise RuntimeError("Temporary stage-1 register block changed")
            source = source.replace(temporary, identity)
    target = destination / "models" / "LIS2DW12.cs"
    target.write_text(source, encoding="utf-8")


def check(renode, destination, final_stage):
    for index, (script, marker, stage) in enumerate(CHECKS):
        if STAGE_ORDER[stage] > final_stage:
            continue
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

    write_model_for_stage(destination, "stage" + str(final_stage))


def recreate_workspace(path):
    destination = path.expanduser().resolve()
    home = Path.home().resolve()
    filesystem_root = Path(destination.anchor).resolve()

    if destination in (ROOT.resolve(), home, filesystem_root):
        raise RuntimeError("Refusing to clear unsafe workspace: " + str(destination))
    if ROOT.resolve().is_relative_to(destination):
        raise RuntimeError("Workspace cannot contain the tutorial repository: " + str(destination))

    if destination.exists():
        if not destination.is_dir():
            raise RuntimeError("Workspace is not a directory: " + str(destination))
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    return destination


def check_gui(renode):
    from renode_client import Renode

    with Renode(renode) as simulation:
        simulation.advance(.1)
        state = simulation.state()
        assert state["registers"] == {
            "WHO_AM_I": 0x44, "CTRL2": 0x04,
            "OUT_X_L": 0xE8, "OUT_X_H": 0x03,
            "OUT_Y_L": 0x0C, "OUT_Y_H": 0xFE,
            "OUT_Z_L": 0x00, "OUT_Z_H": 0x40,
        }, state
        assert state["sample"] == {"x": 1000, "y": -500, "z": 16384}, state
        assert state["uart"] == [
            "WHO_AM_I: 0x44", "XYZ: 1000,-500,16384", "IF_ADD_INC: PASS",
        ], state
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert all(label in page for label in (
        "STM32L072", "WHO_AM_I", "CTRL2", "IF_ADD_INC", "SOFT_RESET", "BOOT",
        "OUT_X_L", "OUT_X_H", "OUT_Y_L", "OUT_Y_H", "OUT_Z_L", "OUT_Z_H",
    ))
    print("PASS GUI support: register snapshot and firmware UART", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renode", default="renode", help="Renode executable")
    parser.add_argument(
        "--workspace", type=Path,
        help="Persistent destination to clear, reconstruct, validate, and keep",
    )
    parser.add_argument(
        "--stage", type=int, choices=range(1, 5), default=4,
        help="Last tutorial stage to materialize and validate (default: 4)",
    )
    args = parser.parse_args()
    executable = shutil.which(args.renode)
    if executable is None:
        parser.error("Renode not found: " + args.renode)
    try:
        if args.workspace is not None:
            destination = recreate_workspace(args.workspace)
            materialize(destination)
            check(executable, destination, args.stage)
            print("PASS workspace kept at:", destination, flush=True)
        else:
            with tempfile.TemporaryDirectory(prefix="lis2dw12-tutorial-") as temporary:
                destination = Path(temporary)
                materialize(destination)
                check(executable, destination, args.stage)
        if args.stage == 4:
            check_gui(executable)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print("FAIL:", error, file=sys.stderr)
        return 1
    scope = "stage 1" if args.stage == 1 else "stages 1-" + str(args.stage)
    print("PASS tutorial: " + scope
          + (" and optional GUI" if args.stage == 4 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
