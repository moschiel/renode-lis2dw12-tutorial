# Modeling an I2C Accelerometer in Renode: LIS2DW12

The LIS2DW12 is a three-axis accelerometer with a register-based interface.
Renode already provides a model of this device. This tutorial builds a smaller
version to explain modeling decisions: interpreting transactions, defining
registers, representing samples, and responding to firmware.

We use the [official model](https://github.com/renode/renode-infrastructure/blob/master/src/Emulator/Peripherals/Peripherals/Sensors/LIS2DW12.cs)
as an architectural reference and for comparison. The tutorial reconstructs a
possible development process; it does not describe the original authors' thoughts.
Hardware behavior comes from the [ST DS11811 Rev. 9 datasheet](https://www.st.com/resource/en/datasheet/lis2dw12.pdf).

The intended result is to run the same STM32 firmware against both models,
comparing readings and UART output as each feature is added.

Recommended preparation: the [PCF8574 tutorial](https://github.com/moschiel/renode-pcf8574-tutorial).
It introduces C# models, REPL platforms, and the Monitor. Here we move on to
register maps and transaction state.

> **Scope:** this tutorial models the common polling path: identification, basic
> initialization, data-ready status, and XYZ samples. The GUI and utility scripts
> are 100% *vibe coded* support assets; their implementation is outside the
> teaching scope.
> See [Limits and References](#limits-and-references) for the complete scope.


<details>
<summary>1. Set up the project and I2C skeleton</summary>


You need **Renode 1.16.1** on your PATH.
See the [installation guide](https://renode.readthedocs.io/en/latest/introduction/installing.html).
The Python interpreter used by the `python` command inside the Monitor is
included with Renode.

In the **Terminal**, check:

```sh
renode --version
```

**Expected:** Renode prints its version without a command-not-found error.

From this tutorial repository's root, create a separate sibling working
directory. It receives the supplied validation scripts; you will create the
model, platform, and script files from the blocks below.

**Windows / PowerShell:**

```powershell
New-Item -ItemType Directory ..\my-lis2dw12 -ErrorAction Stop
New-Item -ItemType Directory ..\my-lis2dw12\models, ..\my-lis2dw12\platforms, ..\my-lis2dw12\scripts, ..\my-lis2dw12\tools
Copy-Item -Recurse tests ..\my-lis2dw12\tests
Copy-Item -Recurse firmware ..\my-lis2dw12\firmware
Copy-Item tools\build_firmware.py ..\my-lis2dw12\tools\build_firmware.py
Copy-Item tools\lab.py, tools\renode_client.py ..\my-lis2dw12\tools
Copy-Item scripts\bridge.py, scripts\lab.resc, scripts\uart_capture.py ..\my-lis2dw12\scripts
Copy-Item -Recurse web ..\my-lis2dw12\web
Set-Location ..\my-lis2dw12
```

**Linux / Bash:**

```bash
mkdir ../my-lis2dw12
mkdir ../my-lis2dw12/models ../my-lis2dw12/platforms ../my-lis2dw12/scripts ../my-lis2dw12/tools
cp -R tests ../my-lis2dw12/tests
cp -R firmware ../my-lis2dw12/firmware
cp tools/build_firmware.py ../my-lis2dw12/tools/build_firmware.py
cp tools/lab.py tools/renode_client.py ../my-lis2dw12/tools/
cp scripts/bridge.py scripts/lab.resc scripts/uart_capture.py ../my-lis2dw12/scripts/
cp -R web ../my-lis2dw12/web
cd ../my-lis2dw12
```

All remaining commands start from `my-lis2dw12`.
**Monitor** blocks run inside the Renode session, not in the terminal.

### Separate I2C transport from register storage

In **section 6.1.1, I2C operation**, the datasheet describes the `SUB` byte,
which selects an internal register. During a write, subsequent bytes are data.
During a combined read, the master sends `SUB` and switches to receiving with
a repeated START. In Renode, the controller forwards this to `Write` and `Read`.

The device address, selected as `0x18` or `0x19` by SA0, will be configured in
the platform when we connect the STM32. It is distinct from `SUB` and should
not be interpreted as the first byte of `Write`.

The implementation separates two responsibilities:

- `II2CPeripheral` represents the I2C transport: it receives bytes from the master, selects the target register, and returns response bytes.
- `ByteRegisterCollection` represents the register storage: it stores register values and applies their fields, permissions, and reset values.

The [official model](https://github.com/renode/renode-infrastructure/blob/master/src/Emulator/Peripherals/Peripherals/Sensors/LIS2DW12.cs)
also separates these responsibilities. Its `Write` accepts address and data in
separate calls, and `FinishTransmission` ends that state. We follow this structure
with a boolean and a pointer.

The physical device also supports SPI (section 6.2). The reference implementation
uses `II2CPeripheral`; this tutorial we are going to implement I2C only.

### Create the model

Create `models/LIS2DW12.cs`:

<!-- tutorial-stage-model: stage1 -->
```csharp
using System;
using Antmicro.Renode.Core.Structure.Registers;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.I2C;

namespace Antmicro.Renode.Peripherals.Tutorial
{
    public class LIS2DW12 : II2CPeripheral,
        IProvidesRegisterCollection<ByteRegisterCollection>
    {
        public LIS2DW12()
        {
            RegistersCollection = new ByteRegisterCollection(this);
            // Temporary stage-1 storage. It will be replaced by WHO_AM_I.
            RegistersCollection.DefineRegister(0x10, 0xA5)
                .WithValueField(0, 8, name: "TRANSPORT_TEST");
            Reset();
        }

        public ByteRegisterCollection RegistersCollection { get; }

        // IPeripheral contract inherited by II2CPeripheral.
        // Represents a hardware reset of the modeled device.
        public void Reset()
        {
            RegistersCollection.Reset();
            FinishTransmission();
            this.Log(LogLevel.Debug, "Hardware reset restored register defaults.");
        }

        // II2CPeripheral contract: receives bytes sent by the I2C master.
        public void Write(byte[] data)
        {
            if(data.Length == 0)
            {
                this.Log(LogLevel.Noisy, "Ignoring an empty I2C write.");
                return;
            }

            var offset = 0;
            if(waitingForRegister)
            {
                // DS11811 Rev. 9, section 6.1.1: SUB selects the register.
                // The controller may deliver SUB and data in separate calls.
                selectedRegister = data[0];
                waitingForRegister = false;
                offset = 1;
                this.Log(LogLevel.Noisy, "I2C selected register 0x{0:X2}.", selectedRegister);
            }

            for(var i = offset; i < data.Length; i++)
            {
                this.Log(LogLevel.Debug, "I2C write: register 0x{0:X2} <= 0x{1:X2}.", selectedRegister, data[i]);
                RegistersCollection.Write(selectedRegister, data[i]);
                // Address increment will be introduced with CTRL2.IF_ADD_INC.
            }
        }

        // II2CPeripheral contract: returns bytes requested by the I2C master.
        public byte[] Read(int count = 1)
        {
            if(count < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(count));
            }

            var result = new byte[count];
            if(waitingForRegister)
            {
                // Same fallback as the reference model for an unselected read.
                this.Log(LogLevel.Warning, "I2C read requested without selecting a register.");
                return result;
            }

            for(var i = 0; i < count; i++)
            {
                result[i] = RegistersCollection.Read(selectedRegister);
                this.Log(LogLevel.Noisy, "I2C read: register 0x{0:X2} => 0x{1:X2}.", selectedRegister, result[i]);
            }
            return result;
        }

        // II2CPeripheral contract: marks an I2C STOP / transaction boundary.
        public void FinishTransmission()
        {
            // Follow the reference model's transaction boundary.
            // Reset protocol state without resetting the register contents.
            if(!waitingForRegister)
            {
                this.Log(LogLevel.Noisy, "I2C transaction finished.");
            }
            ClearSelection();
        }

        private void ClearSelection()
        {
            selectedRegister = 0;
            waitingForRegister = true;
        }

        private byte selectedRegister;
        private bool waitingForRegister;
    }
}
```

`waitingForRegister` distinguishes a register-selection byte from data bytes.
The first byte selects a location; subsequent bytes are written to it.
`FinishTransmission` clears the selection at the I2C transaction boundary,
while `Reset` also restores the collection values. Keeping the selection between
`Write` and `Read` supports the repeated START used by a register read.

`this.Log` uses Renode's logging system. State-changing writes and resets use
`Debug`; frequent selections and reads use `Noisy`. Renode filters disabled
levels before formatting these messages, and the arguments used here are cheap.

We have not defined any sensor registers yet. Automatic increment will be added
with `CTRL2.IF_ADD_INC` (section 8.5), so this stage does not represent the full
LIS2DW12 behavior after reset.

In the **Terminal**, check compilation:

```sh
renode --console --disable-gui --plain models/LIS2DW12.cs
```

**Expected:** the Monitor opens without compilation errors.
`--disable-gui` avoids graphical windows and `--plain` simplifies output.
In the **Monitor**, enter `quit`.

### Check the transport with temporary storage

`TRANSPORT_TEST` is a temporary writable byte in the `LIS2DW12` class itself.
Its address and value are artificial; they do not belong to the LIS2DW12 map.
It lets us verify selection, writes, reads, and reset before adding the first
real register.
`WithValueField(0, 8)` creates a writable field covering the byte; the second
argument to `DefineRegister` is its reset value.

A **REPL** file describes instances and connections. Create `platforms/accel_isolated.repl`:

<!-- tutorial-file: platforms/accel_isolated.repl -->
```text
accel: Tutorial.LIS2DW12 @ sysbus
```

`accel` is the model under development. `Tutorial` identifies the namespace under `Antmicro.Renode.Peripherals`.
In this declaration, `@ sysbus` registers objects in the machine without assigning
memory addresses. There is no I2C controller or CPU yet.

A **RESC** file groups Monitor commands. Create `scripts/accel_isolated.resc`:

<!-- tutorial-file: scripts/accel_isolated.resc -->
```text
include @models/LIS2DW12.cs
mach create "lis2dw12-isolated"
machine LoadPlatformDescription @platforms/accel_isolated.repl
```

`include` compiles the model class. `mach create` creates the machine;
`LoadPlatformDescription` instantiates the object.

**Terminal:**

```sh
renode --console --disable-gui --plain scripts/accel_isolated.resc
```

In the **Monitor**, inspect the machine:

```text
peripherals
```

**Expected:** an `accel (LIS2DW12)` entry under `sysbus`.

```text
  sysbus (SystemBus)
  │
  └── accel (LIS2DW12)
```

To inspect the model while developing it, enable `Debug` logs for this instance:

```text
logLevel 0 sysbus.accel
```

Use `logLevel -1 sysbus.accel` when you also need the more frequent register
selection and read messages.

You can write Python snippets in the **Monitor** to manually test the model's
expected behavior:

```text
python "from System import Array, Byte"
python "dev = monitor.Machine['sysbus.accel']"
python "dev.Write(Array[Byte]([0x10]))"
python "print(list(dev.Read(1)))"
```

`Array[Byte]` creates an array for the C# method. `dev` points to the `accel`
instance declared in the REPL, the Write and Read call are the functions declared in the C# model. **Expected:** `[165]`, or `0xA5`, the reset
value of `TRANSPORT_TEST`. Enter `quit` when finished.

This demonstrates direct, interactive testing through the Monitor.

From this point onward, the tutorial uses supplied `.resc` scripts for validation, therefore there is no need to type direclty in the monitor the testing instructions.
The `.resc` scritps are repeatable, document the expected behavior in comments, and will grow
with each stage.
Take a look at the test files to understand the syntax used to write Renode tests.

### Run the stage 1 validation

`tests/transport.resc` is supplied with the repository. It checks the temporary
register's reset value, separate and combined writes, an empty write, zero-length
read, fixed-address multiple-byte access, and the effects of transaction end and
hardware reset.

Start a fresh Renode session from the **Terminal**:

```sh
renode --console --disable-gui --plain tests/transport.resc
```

**Expected:** `PASS transport: register storage`, followed by Renode
exiting. An `assert` stops the script if the response differs. If an error occurs,
check the message before the prompt; the process exit code alone does not
guarantee that the assertions passed.

</details>

<details>
<summary>2. WHO_AM_I and STM32 firmware</summary>


### Register behavior

`WHO_AM_I` identifies the connected sensor. A master selects sub-address `0x0F`
over I2C and receives the fixed value `0x44`. The register is read-only, so a
write must not change the value.

### Implement the register

In `models/LIS2DW12.cs`, replace the temporary `TRANSPORT_TEST` definition from
section 1 with the register described in **DS11811 Rev. 9, section 8.3**:

```csharp
// DS11811 Rev. 9, section 8.3: WHO_AM_I is read-only and resets to 0x44.
RegistersCollection.DefineRegister(0x0F, 0x44)
    .WithValueField(0, 8, FieldMode.Read, name: "WHO_AM_I");
```

The `FieldMode.Read` argument expresses the access rule from the datasheet:
writes to this register are ignored by the model.

### Validate the model

`tests/who_am_i.resc` is supplied with the project. It checks the reset value,
the register selection byte, and the read-only behavior. Run it from the
Terminal:

```sh
renode --console --disable-gui --plain tests/who_am_i.resc
```

**Expected:** `PASS who_am_i: register behavior`.

### Prepare the STM32 firmware

The supplied project in `firmware/lis2dw12-demo` was generated with STM32CubeMX
for **STM32L072CZYx**, the MCU family used by
[Renode's official LIS2DW12 test](https://github.com/renode/renode/blob/v1.16.1/tests/peripherals/LIS2DW12.robot).
It uses HAL, I2C1 on PB6/PB9, and USART2 on PA2/PA3. Open the project in
STM32CubeIDE if you want to edit or rebuild it.

For this section, the relevant application code
is limited to the following snippets from `Core/Src/main.c`.

The 7-bit device address is shifted because the STM32 HAL expects the address
in the I2C transaction format. The register sub-address remains `0x0F`:

```c
#define LIS2DW12_I2C_ADDRESS (0x18 << 1)
#define LIS2DW12_WHO_AM_I 0x0F
```

The `ValidateWhoAmI()` function performs one memory read and reports the result
through USART2:

```c
static void ValidateWhoAmI(void)
{
  uint8_t deviceId = 0;
  const uint8_t successMessage[] = "WHO_AM_I: 0x44\r\n";
  const uint8_t errorMessage[] = "WHO_AM_I: ERROR\r\n";

  if (HAL_I2C_Mem_Read(&hi2c1, LIS2DW12_I2C_ADDRESS, LIS2DW12_WHO_AM_I,
                       I2C_MEMADD_SIZE_8BIT, &deviceId, 1, 100) == HAL_OK
      && deviceId == 0x44)
  {
    HAL_UART_Transmit(&huart2, (uint8_t *)successMessage,
                      sizeof(successMessage) - 1, 100);
  }
  else
  {
    HAL_UART_Transmit(&huart2, (uint8_t *)errorMessage,
                      sizeof(errorMessage) - 1, 100);
  }
}
```

It is called once after CubeMX initializes GPIO, I2C1, and USART2:

```c
MX_GPIO_Init();
MX_I2C1_Init();
// Other CubeMX-generated peripheral initialization.
MX_USART2_UART_Init();

ValidateWhoAmI();
```

The clock setup, HAL initialization, interrupt handlers, and generated driver
code are supplied by CubeMX and are not specific to this register.

> **Note:** The precompiled binary is already available at
> `firmware/lis2dw12-demo/Debug/lis2dw12-demo.elf`, so you do not need to
> compile the firmware to follow this tutorial.
>
> If you edit the firmware source, you can rebuild it with STM32CubeIDE or use
> the supplied `tools/build_firmware.py` without an IDE. The script calls Arm
> GNU Toolchain directly and is usable on Windows or Linux. If
> `arm-none-eabi-gcc` is not on `PATH`, pass its full path:
>
> ```powershell
> python tools\build_firmware.py --gcc "C:\path\to\arm-none-eabi-gcc.exe"
> ```
>
> With the bundled STM32CubeIDE toolchain, the executable is under the IDE's
> `plugins/...gnu-tools-for-stm32.../tools/bin/` directory. The script uses the
> `STM32L072xx` compiler define and linker script, then writes the ELF to the
> same `firmware/lis2dw12-demo/Debug/` directory used by STM32CubeIDE.

### Connect the STM32

Create `platforms/stm32_lis2dw12.repl`:

<!-- tutorial-file: platforms/stm32_lis2dw12.repl -->
```text
using "platforms/cpus/stm32l072.repl"

accel: Tutorial.LIS2DW12 @ i2c1 0x18
```

The platform reuses Renode's STM32L072 CPU description and attaches the model
to the CPU's `i2c1` peripheral. This is the platform used by Renode's official
LIS2DW12 test. `0x18` is the LIS2DW12 7-bit address when SA0 is low; it is
different from the internal register address `0x0F`.

Create `scripts/stm32_lis2dw12.resc`:

<!-- tutorial-file: scripts/stm32_lis2dw12.resc -->
```text
include @models/LIS2DW12.cs
mach create "lis2dw12-stm32"
machine LoadPlatformDescription @platforms/stm32_lis2dw12.repl

$bin?=@firmware/lis2dw12-demo/Debug/lis2dw12-demo.elf
sysbus LoadELF $bin
showAnalyzer usart2
```

The script loads the supplied precompiled ELF. You only need to rebuild the
firmware if you edit `Core/Src/main.c`; the builder writes the replacement to
the same path.

Run it from the project root:

```sh
renode --console --plain scripts/stm32_lis2dw12.resc
```

Start the emulation with `start`.
The `showAnalyzer usart2` command in the script opens a window for debugging UART2;
As programmed in the firmware, it should display `WHO_AM_I: 0x44`.

</details>

<details>
<summary>3. Multi-byte register access</summary>


### IF_ADD_INC behavior

Sections **6.1.1 and 8.5** specify that each additional byte accesses the next
register when `IF_ADD_INC` is `1`, or repeats the selected register when it is
`0`. The bit is in `CTRL2` (`0x21`), which resets to `0x04`, so automatic
increment starts enabled.

`CTRL1` is temporary writable storage in this section only to make pointer
movement observable. Its useful configuration fields are introduced when the
firmware starts configuring sample acquisition.

### Define the control registers

Add these definitions after `WHO_AM_I` in the constructor:

```csharp
// Temporary neighboring storage used to observe IF_ADD_INC.
// CTRL1 fields and behavior are introduced with sample generation.
RegistersCollection.DefineRegister(0x20, 0x00)
    .WithValueField(0, 8, out control1, name: "CTRL1");
// DS11811 Rev. 9, section 8.5: only IF_ADD_INC affects behavior.
// Tagged fields document the remaining layout without simulating it.
RegistersCollection.DefineRegister(0x21, 0x04)
    .WithTaggedFlag("SIM", 0)
    .WithTaggedFlag("I2C_DISABLE", 1)
    .WithFlag(2, out automaticAddressIncrement, name: "IF_ADD_INC")
    .WithTaggedFlag("BDU", 3)
    .WithTaggedFlag("CS_PU_DISC", 4)
    .WithReservedBits(5, 1)
    .WithTaggedFlag("SOFT_RESET", 6)
    .WithTaggedFlag("BOOT", 7);
```

`WithTaggedFlag` preserves the documented register layout but does not attach
behavior to those fields. Declare only the state needed by this section:

```csharp
private IValueRegisterField control1;
private IFlagRegisterField automaticAddressIncrement;
```

### Apply IF_ADD_INC to transfers

After each `RegistersCollection.Write` and `RegistersCollection.Read`, call:

```csharp
IncrementSelectedRegister();
```

Then add the helper:

```csharp
private void IncrementSelectedRegister()
{
    if(automaticAddressIncrement.Value)
    {
        selectedRegister++;
    }
}
```

The increment happens once per data byte. Register selection itself does not
advance the pointer.

### Validate the model

The supplied `tests/auto_increment.resc` checks reset values, read/write
storage, fixed-address bursts with `IF_ADD_INC=0`, incrementing bursts with
`IF_ADD_INC=1`, and hardware reset. Run:

```sh
renode --console --disable-gui --plain tests/auto_increment.resc
```

**Expected:** `PASS auto_increment: IF_ADD_INC behavior`.

### Extend the STM32 firmware

The supplied firmware defines the two register addresses:

```c
#define LIS2DW12_I2C_ADDRESS (0x18 << 1)
#define LIS2DW12_CTRL1 0x20
#define LIS2DW12_CTRL2 0x21
```

`ValidateAutoIncrement()` first disables increment and writes two bytes
starting at `CTRL1`. Both target `CTRL1`, so its final value must be `0x34`.
It then enables increment, writes `0x50` to `CTRL1` and `0x04` to `CTRL2` in
one burst, and reads each register back:

```c
static void ValidateAutoIncrement(void)
{
  uint8_t disabled = 0x00;
  uint8_t enabled = 0x04;
  uint8_t fixedAddressBurst[] = {0x12, 0x34};
  uint8_t incrementingBurst[] = {0x50, 0x04};
  uint8_t ctrl1 = 0;
  uint8_t ctrl2 = 0;
  const uint8_t successMessage[] = "IF_ADD_INC: PASS\r\n";
  const uint8_t errorMessage[] = "IF_ADD_INC: ERROR\r\n";

  // With IF_ADD_INC disabled, both bytes target CTRL1.
  if (HAL_I2C_Mem_Write(&hi2c1, LIS2DW12_I2C_ADDRESS, LIS2DW12_CTRL2,
                        I2C_MEMADD_SIZE_8BIT, &disabled, 1, 100) != HAL_OK
      || HAL_I2C_Mem_Write(&hi2c1, LIS2DW12_I2C_ADDRESS, LIS2DW12_CTRL1,
                           I2C_MEMADD_SIZE_8BIT, fixedAddressBurst, 2, 100) != HAL_OK
      || HAL_I2C_Mem_Read(&hi2c1, LIS2DW12_I2C_ADDRESS, LIS2DW12_CTRL1,
                          I2C_MEMADD_SIZE_8BIT, &ctrl1, 1, 100) != HAL_OK
      || ctrl1 != 0x34)
  {
    HAL_UART_Transmit(&huart2, (uint8_t *)errorMessage,
                      sizeof(errorMessage) - 1, 100);
    return;
  }

  // Re-enable the default burst behavior and verify CTRL1 -> CTRL2 access.
  if (HAL_I2C_Mem_Write(&hi2c1, LIS2DW12_I2C_ADDRESS, LIS2DW12_CTRL2,
                        I2C_MEMADD_SIZE_8BIT, &enabled, 1, 100) != HAL_OK
      || HAL_I2C_Mem_Write(&hi2c1, LIS2DW12_I2C_ADDRESS, LIS2DW12_CTRL1,
                           I2C_MEMADD_SIZE_8BIT, incrementingBurst, 2, 100) != HAL_OK
      || HAL_I2C_Mem_Read(&hi2c1, LIS2DW12_I2C_ADDRESS, LIS2DW12_CTRL1,
                          I2C_MEMADD_SIZE_8BIT, &ctrl1, 1, 100) != HAL_OK
      || HAL_I2C_Mem_Read(&hi2c1, LIS2DW12_I2C_ADDRESS, LIS2DW12_CTRL2,
                          I2C_MEMADD_SIZE_8BIT, &ctrl2, 1, 100) != HAL_OK
      || ctrl1 != 0x50 || ctrl2 != 0x04)
  {
    HAL_UART_Transmit(&huart2, (uint8_t *)errorMessage,
                      sizeof(errorMessage) - 1, 100);
    return;
  }

  HAL_UART_Transmit(&huart2, (uint8_t *)successMessage,
                    sizeof(successMessage) - 1, 100);
}
```

Call it immediately after the identity check:

```c
ValidateWhoAmI();
ValidateAutoIncrement();
```

The firmware reads `CTRL1` and `CTRL2` separately after the burst so each value
is explicit in the validation.

Rebuild only if you changed the firmware source; the repository already
contains the updated ELF. Run `scripts/stm32_lis2dw12.resc`, start the machine,
and check USART2.

**Expected UART:**

```text
WHO_AM_I: 0x44
IF_ADD_INC: PASS
```

The supplied cumulative firmware check captures USART2 without opening an
analyzer window:

```sh
renode --console --disable-gui --plain tests/firmware_custom.resc
```

**Expected:** `PASS firmware: WHO_AM_I and IF_ADD_INC`.

The STM32L072 platform delivers each I2C transaction boundary to the peripheral,
so the same firmware reads `WHO_AM_I` correctly from both models. The
auto-increment result intentionally differs: Renode 1.16.1's official model
limits address auto-increment to its output and temperature register windows,
while this tutorial follows the datasheet rule for the demonstrated
`CTRL1 -> CTRL2` burst. `tests/compare_models.resc` records the shared behavior
and deliberate differences.

</details>

<details>
<summary>4. Minimal sensor initialization (work in progress)</summary>
</details>

<details>
<summary>Optional web view (vibe-coded)</summary>


The supplied read-only panel displays each implemented register as hexadecimal
and binary, decodes its named fields, and shows the real USART2 output. It is a
visualization aid, not part of the modeling lesson:

```sh
python tools/lab.py
```

It opens [localhost:8000](http://127.0.0.1:8000). As later registers are
implemented, they will be added to this same view. Stop it with `Ctrl+C`.

</details>

<details>
<summary>Limits and References</summary>


This tutorial implements the common polling path: device identification, basic
initialization, data-ready status, and XYZ sample reads. Configuration affects
the model only when the demonstrated firmware observes that effect. Other fields
may be tagged, stored, or return a documented default without a dedicated test.

Electrical characteristics, analog filtering, noise, power consumption, and
exact physical performance are not simulated. FIFO, tap, free-fall, orientation,
wake-up, self-test, and temperature features are outside this tutorial. SPI also
remains outside the transport scope.

The result is a teaching model for representative Renode patterns, not a complete
replacement for the device. Comparisons cover the demonstrated firmware and
configurations, not arbitrary LIS2DW12 drivers.

- [Preparatory PCF8574 tutorial](https://github.com/moschiel/renode-pcf8574-tutorial).
- [LIS2DW12 datasheet, DS11811 Rev. 9](https://www.st.com/resource/en/datasheet/lis2dw12.pdf): interfaces in section 6, register map in section 7, and registers in section 8.
- [Official Renode model](https://github.com/renode/renode-infrastructure/blob/master/src/Emulator/Peripherals/Peripherals/Sensors/LIS2DW12.cs): architectural reference; code on `master` may change.
- [Register Framework and peripheral modeling](https://renode.readthedocs.io/en/latest/advanced/writing-peripherals.html).

### Optional model comparison

At the end of the tutorial, `tests/compare_models.resc` can be used to run the
cumulative checks against both `Tutorial.LIS2DW12` and Renode's official
`Sensors.LIS2DW12` model. Run it from the project root:

```sh
renode --console --disable-gui --plain tests/compare_models.resc
```

`tests/firmware_reference.resc` also runs the supplied STM32L072 ELF against
the official model. At the current stage it confirms successful I2C transaction
boundaries and `WHO_AM_I`; it also records the known control-register
auto-increment difference described in section 3.

```sh
renode --console --disable-gui --plain tests/firmware_reference.resc
```

**Expected:** `PASS reference firmware: I2C transactions complete; known
auto-increment difference observed`.

</details>
