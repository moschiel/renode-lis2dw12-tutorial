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

> **Scope:** this tutorial focuses on functional digital modeling and firmware
> integration. The GUI and utility scripts are 100% *vibe coded* support assets;
> their implementation is outside the teaching scope. The future GUI will be
> optional, for visualizing registers and UART output.


## Limits and references

We will try to cover every documented register, focusing on observable digital
rules. Electrical characteristics, analog filtering, noise, power consumption,
and physical performance are **not** simulated. Settings affecting only those
properties may retain their written values without reproducing their effects.

Each field will have an explicit policy: functional behavior, stored configuration,
or fixed/injected data. Reset values, access permissions, command clearing, and
status semantics must be considered separately; a blanket read/write echo can
leave firmware waiting forever. Reserved addresses are not writable scratch storage.

Register coverage does not imply a complete FIFO, gesture engine, temperature
simulation, or sampling scheduler. Those groups will explicitly describe which
digital behaviors are implemented and which are simplified or mocked. SPI remains
a separate transport extension. Comparisons cover the demonstrated firmware and
configurations, not arbitrary drivers.

- [Preparatory PCF8574 tutorial](https://github.com/moschiel/renode-pcf8574-tutorial).
- [LIS2DW12 datasheet, DS11811 Rev. 9](https://www.st.com/resource/en/datasheet/lis2dw12.pdf): interfaces in section 6, register map in section 7, and registers in section 8.
- [Official Renode model](https://github.com/renode/renode-infrastructure/blob/master/src/Emulator/Peripherals/Peripherals/Sensors/LIS2DW12.cs): architectural reference; code on `master` may change.
- [Register Framework and peripheral modeling](https://renode.readthedocs.io/en/latest/advanced/writing-peripherals.html).


## 1. Set up the project and I2C skeleton

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
New-Item -ItemType Directory ..\my-lis2dw12\models, ..\my-lis2dw12\platforms, ..\my-lis2dw12\scripts
Copy-Item -Recurse tests ..\my-lis2dw12\tests
Set-Location ..\my-lis2dw12
```

**Linux / Bash:**

```bash
mkdir ../my-lis2dw12
mkdir ../my-lis2dw12/models ../my-lis2dw12/platforms ../my-lis2dw12/scripts
cp -R tests ../my-lis2dw12/tests
cd ../my-lis2dw12
```

All remaining commands start from `my-lis2dw12`.
**Monitor** blocks run inside the Renode session, not in the terminal.

### Separate transport and registers

In **section 6.1.1, I2C operation**, the datasheet describes the `SUB` byte,
which selects an internal register. During a write, subsequent bytes are data.
During a combined read, the master sends `SUB` and switches to receiving with
a repeated START. In Renode, the controller forwards this to `Write` and `Read`.

The device address, selected as `0x18` or `0x19` by SA0, will be configured in
the platform when we connect the STM32. It is distinct from `SUB` and should
not be interpreted as the first byte of `Write`.

The implementation has two responsibilities:

- `II2CPeripheral` receives accesses and keeps the selected register between calls.
- `ByteRegisterCollection` stores eight-bit registers, their fields, permissions, and reset values.

The [official model](https://github.com/renode/renode-infrastructure/blob/master/src/Emulator/Peripherals/Peripherals/Sensors/LIS2DW12.cs)
also separates these responsibilities. Its `Write` accepts address and data in
separate calls, and `FinishTransmission` ends that state. We follow this structure
with a boolean and a pointer.

The physical device also supports SPI (section 6.2). The reference implementation
uses `II2CPeripheral`; this tutorial we are going to implement I2C only.

### Create the model

Create `models/LIS2DW12.cs`:

<!-- tutorial-file: models/LIS2DW12.cs -->
```csharp
using System;
using Antmicro.Renode.Core.Structure.Registers;
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
        }

        // II2CPeripheral contract: receives bytes sent by the I2C master.
        public void Write(byte[] data)
        {
            if(data.Length == 0)
            {
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
            }

            for(var i = offset; i < data.Length; i++)
            {
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
                return result;
            }

            for(var i = 0; i < count; i++)
            {
                result[i] = RegistersCollection.Read(selectedRegister);
            }
            return result;
        }

        // II2CPeripheral contract: marks an I2C STOP / transaction boundary.
        public void FinishTransmission()
        {
            // Follow the reference model's transaction boundary.
            // Reset protocol state without resetting the register contents.
            selectedRegister = 0;
            waitingForRegister = true;
        }

        private byte selectedRegister;
        private bool waitingForRegister;
    }
}
```

`waitingForRegister` distinguishes a register-selection byte from data bytes.
The first byte selects a location; subsequent bytes received before the end of
the transaction are written to that location. `FinishTransmission` clears the
selection, while `Reset` also restores the collection values.

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
mach create "lis2dw12-stage1"
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
  sysbus (SystemBus)
  │
  └── accel (LIS2DW12)

You can write Python snippets in the **Monitor** to manually test the model's
expected behavior:

```text
python "from System import Array, Byte"
python "dev = monitor.Machine['sysbus.accel']"
python "dev.Write(Array[Byte]([0x10]))"
python "print(list(dev.Read(1)))"
```

`Array[Byte]` creates an array for the C# method. `dev` points to the `accel`
instance declared in the REPL. **Expected:** `[165]`, or `0xA5`, the reset
value of `TRANSPORT_TEST`. Enter `quit` when finished.

This demonstrates direct, interactive testing through the Monitor.

From this point onward, the tutorial uses supplied `.resc` scripts for validation.
They are repeatable, document the expected behavior in comments, and will grow
with each stage. Take a look at the test files to understand the syntax used to
write Renode tests.

### Run the stage 1 validation

`tests/stage1.resc` is supplied with the repository. It checks the temporary
register's reset value, separate and combined writes, an empty write, zero-length
read, fixed-address multiple-byte access, and the effects of transaction end and
hardware reset.

Start a fresh Renode session from the **Terminal**:

```sh
renode --console --disable-gui --plain tests/stage1.resc
```

**Expected:** `PASS stage1: transport and register storage`, followed by Renode
exiting. An `assert` stops the script if the response differs. If an error occurs,
check the message before the prompt; the process exit code alone does not
guarantee that the assertions passed.

### Confirm the installed reference model

`tests/reference.resc` is also supplied. It instantiates Renode's official
`Sensors.LIS2DW12` and verifies its `WHO_AM_I` response before our model has
implemented that register. Its comments describe the direct Monitor calls.

**Terminal:**

```sh
renode --console --disable-gui --plain tests/reference.resc
```

**Expected:** `PASS reference: WHO_AM_I baseline`.

This test uses `Sensors.LIS2DW12`, the model distributed with Renode, and checks
the `0x44` identifier described in **section 8.3, WHO_AM_I**. It is an initial
reference check just to make sure the official model is available and running in your environment.

## 2. WHO_AM_I and STM32 firmware (work in progress)
