"""Build the CubeMX-generated STM32F401RE firmware with Arm GNU Toolchain."""
import argparse
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "firmware" / "lis2dw12-demo"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gcc",
        default="arm-none-eabi-gcc",
        help="Arm GCC executable name or full path",
    )
    args = parser.parse_args()

    gcc = shutil.which(args.gcc) or (Path(args.gcc) if Path(args.gcc).is_file() else None)
    if gcc is None:
        parser.error("Arm GCC not found. Use --gcc with the executable path.")

    build = PROJECT / "Debug"
    build.mkdir(exist_ok=True)
    hal = PROJECT / "Drivers" / "STM32F4xx_HAL_Driver"
    device = PROJECT / "Drivers" / "CMSIS" / "Device" / "ST" / "STM32F4xx"
    sources = [
        *sorted((PROJECT / "Core" / "Src").glob("*.c")),
        *sorted((PROJECT / "Core" / "Startup").glob("*.s")),
        *sorted((hal / "Src").glob("*.c")),
    ]
    includes = [
        PROJECT / "Core" / "Inc",
        hal / "Inc",
        hal / "Inc" / "Legacy",
        device / "Include",
        PROJECT / "Drivers" / "CMSIS" / "Include",
    ]
    flags = [
        "-mcpu=cortex-m4",
        "-mthumb",
        "-mfpu=fpv4-sp-d16",
        "-mfloat-abi=hard",
        "-DSTM32F401xE",
        "-DUSE_HAL_DRIVER",
        "-Og",
        "-g3",
        "-ffunction-sections",
        "-fdata-sections",
        "-Wall",
        "-Wextra",
    ]
    include_flags = ["-I" + str(path) for path in includes]
    objects = []

    for source in sources:
        obj = build / (source.stem + ".o")
        subprocess.run(
            [str(gcc), *flags, *include_flags, "-c", str(source), "-o", str(obj)],
            check=True,
        )
        objects.append(str(obj))

    elf = build / "lis2dw12-demo.elf"
    subprocess.run(
        [
            str(gcc),
            *flags,
            *objects,
            "-T" + str(PROJECT / "STM32F401RETX_FLASH.ld"),
            "--specs=nano.specs",
            "--specs=nosys.specs",
            "-Wl,--gc-sections",
            "-Wl,-Map=" + str(build / "lis2dw12-demo.map"),
            "-o",
            str(elf),
        ],
        check=True,
    )
    print(f"Built {elf.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
