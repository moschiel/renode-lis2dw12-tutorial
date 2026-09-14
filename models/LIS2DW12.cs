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
            // DS11811 Rev. 9, datasheet section 8.3: WHO_AM_I is read-only and resets to 0x44.
            RegistersCollection.DefineRegister(0x0F, 0x44).WithValueField(0, 8, FieldMode.Read, name: "WHO_AM_I");
            // DS11811 Rev. 9, sections 8.12-8.17: each axis is exposed as a
            // little-endian, signed 16-bit value split across two registers.
            // Each `out` parameter receives a handle to the register field.
            RegistersCollection.DefineRegister(0x28, 0x00).WithValueField(0, 8, out outputXLow, FieldMode.Read, name: "OUT_X_L");
            RegistersCollection.DefineRegister(0x29, 0x00).WithValueField(0, 8, out outputXHigh, FieldMode.Read, name: "OUT_X_H");
            RegistersCollection.DefineRegister(0x2A, 0x00).WithValueField(0, 8, out outputYLow, FieldMode.Read, name: "OUT_Y_L");
            RegistersCollection.DefineRegister(0x2B, 0x00).WithValueField(0, 8, out outputYHigh, FieldMode.Read, name: "OUT_Y_H");
            RegistersCollection.DefineRegister(0x2C, 0x00).WithValueField(0, 8, out outputZLow, FieldMode.Read, name: "OUT_Z_L");
            RegistersCollection.DefineRegister(0x2D, 0x00).WithValueField(0, 8, out outputZHigh, FieldMode.Read, name: "OUT_Z_H");
            // DS11811 Rev. 9, section 8.5: only IF_ADD_INC affects behavior.
            // Tagged fields preserve the documented layout without simulating
            // features that are outside this tutorial's common polling path.
            RegistersCollection.DefineRegister(0x21, 0x04)
                .WithTaggedFlag("SIM", 0)
                .WithTaggedFlag("I2C_DISABLE", 1)
                .WithFlag(2, out automaticAddressIncrement, name: "IF_ADD_INC")
                .WithTaggedFlag("BDU", 3)
                .WithTaggedFlag("CS_PU_DISC", 4)
                .WithReservedBits(5, 1)
                .WithTaggedFlag("SOFT_RESET", 6)
                .WithTaggedFlag("BOOT", 7);
            Reset();
        }

        public ByteRegisterCollection RegistersCollection { get; }

        // Side-effect-free values used by optional visualization tooling.
        public byte WhoAmI => 0x44;
        public byte Control2 => automaticAddressIncrement.Value ? (byte)0x04 : (byte)0x00;
        public short SampleX => ReadAxis(outputXLow, outputXHigh);
        public short SampleY => ReadAxis(outputYLow, outputYHigh);
        public short SampleZ => ReadAxis(outputZLow, outputZHigh);

        // Supplies deterministic raw sensor data without simulating motion or
        // analog conversion. Values map directly to the six output registers.
        public void SetSample(int x, int y, int z)
        {
            SetAxis(x, outputXLow, outputXHigh, nameof(x));
            SetAxis(y, outputYLow, outputYHigh, nameof(y));
            SetAxis(z, outputZLow, outputZHigh, nameof(z));
            this.Log(LogLevel.Debug, "Sample updated to X={0}, Y={1}, Z={2}.", x, y, z);
        }

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
                IncrementSelectedRegister();
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
                IncrementSelectedRegister();
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

        private void IncrementSelectedRegister()
        {
            if(automaticAddressIncrement.Value)
            {
                selectedRegister++;
            }
        }

        private static void SetAxis(int value, IValueRegisterField low, IValueRegisterField high, string parameterName)
        {
            if(value < short.MinValue || value > short.MaxValue)
            {
                throw new ArgumentOutOfRangeException(parameterName, "Raw axis values must fit in a signed 16-bit register pair.");
            }

            var raw = unchecked((ushort)(short)value);
            // These handles update the low and high bytes in the actual register fields.
            low.Value = (byte)raw;
            high.Value = (byte)(raw >> 8);
        }

        private static short ReadAxis(IValueRegisterField low, IValueRegisterField high)
        {
            var raw = (ushort)(low.Value | (high.Value << 8));
            return unchecked((short)raw);
        }

        private void ClearSelection()
        {
            selectedRegister = 0;
            waitingForRegister = true;
        }

        private IFlagRegisterField automaticAddressIncrement;
        // Handles returned by WithValueField; their .Value accesses the register fields.
        private IValueRegisterField outputXLow;
        private IValueRegisterField outputXHigh;
        private IValueRegisterField outputYLow;
        private IValueRegisterField outputYHigh;
        private IValueRegisterField outputZLow;
        private IValueRegisterField outputZHigh;
        private byte selectedRegister;
        private bool waitingForRegister;
    }
}
