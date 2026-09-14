using System;
using Antmicro.Renode.Core;
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
            Interrupt1 = new GPIO();
            // DS11811 Rev. 9, datasheet section 8.3: WHO_AM_I is read-only and resets to 0x44.
            RegistersCollection.DefineRegister((byte)RegisterId.WhoAmI, 0x44).WithValueField(0, 8, FieldMode.Read, name: "WHO_AM_I");
            // DS11811 Rev. 9, datasheet section 8.4: ODR=0 selects power-down.
            RegistersCollection.DefineRegister((byte)RegisterId.Control1, 0x00)
                .WithValueField(4, 4, out outputDataRate, name: "ODR")
                .WithWriteCallback((_, __) => HandleAcquisitionConfigurationChanged());
            // DS11811 Rev. 9, datasheet section 8.5: this stage models only IF_ADD_INC.
            RegistersCollection.DefineRegister((byte)RegisterId.Control2, 0x04).WithFlag(2, out automaticAddressIncrement, name: "IF_ADD_INC");
            // DS11811 Rev. 9, datasheet section 8.7: this stage models only INT1_DRDY.
            RegistersCollection.DefineRegister((byte)RegisterId.Control4Int1PadControl, 0x00)
                .WithFlag(0, out dataReadyInterruptEnabled, name: "INT1_DRDY")
                .WithWriteCallback((_, __) => UpdateInterrupt1());
            // DS11811 Rev. 9, datasheet section 8.11: DRDY reports XYZ availability.
            RegistersCollection.DefineRegister((byte)RegisterId.Status, 0x00)
                .WithFlag(0, out dataReady, FieldMode.Read, name: "DRDY");
            // DS11811 Rev. 9, sections 8.12-8.17: each axis is exposed as a
            // little-endian, signed 16-bit value split across two registers.
            // Each `out` parameter receives a handle to the register field.
            RegistersCollection.DefineRegister((byte)RegisterId.OutputXLow, 0x00).WithValueField(0, 8, out outputXLow, FieldMode.Read, name: "OUT_X_L");
            RegistersCollection.DefineRegister((byte)RegisterId.OutputXHigh, 0x00).WithValueField(0, 8, out outputXHigh, FieldMode.Read, name: "OUT_X_H");
            RegistersCollection.DefineRegister((byte)RegisterId.OutputYLow, 0x00).WithValueField(0, 8, out outputYLow, FieldMode.Read, name: "OUT_Y_L");
            RegistersCollection.DefineRegister((byte)RegisterId.OutputYHigh, 0x00).WithValueField(0, 8, out outputYHigh, FieldMode.Read, name: "OUT_Y_H");
            RegistersCollection.DefineRegister((byte)RegisterId.OutputZLow, 0x00).WithValueField(0, 8, out outputZLow, FieldMode.Read, name: "OUT_Z_L");
            RegistersCollection.DefineRegister((byte)RegisterId.OutputZHigh, 0x00).WithValueField(0, 8, out outputZHigh, FieldMode.Read, name: "OUT_Z_H");
            Reset();
        }

        public ByteRegisterCollection RegistersCollection { get; }

        public GPIO Interrupt1 { get; }

        // Side-effect-free values exposed for automated tests and the optional GUI.
        public byte WhoAmI => 0x44;
        public byte Control1 => (byte)(outputDataRate.Value << 4);
        public byte Control2 => automaticAddressIncrement.Value ? (byte)0x04 : (byte)0x00;
        public byte Control4 => dataReadyInterruptEnabled.Value ? (byte)0x01 : (byte)0x00;
        public byte Status => dataReady.Value ? (byte)0x01 : (byte)0x00;
        public bool AcquisitionEnabled => outputDataRate.Value != 0;
        public short SampleX => ReadAxis(outputXLow, outputXHigh);
        public short SampleY => ReadAxis(outputYLow, outputYHigh);
        public short SampleZ => ReadAxis(outputZLow, outputZHigh);

        // Public stimulus API used by automated tests and the optional GUI.
        // It represents a completed conversion without simulating motion or analog timing.
        public void SetSample(int x, int y, int z)
        {
            // CTRL1.ODR=0 is power-down, so no conversion can update the output registers.
            if(!AcquisitionEnabled)
            {
                this.Log(LogLevel.Debug, "Ignoring sample while the device is in power-down.");
                return;
            }

            SetAxis(x, outputXLow, outputXHigh, nameof(x));
            SetAxis(y, outputYLow, outputYHigh, nameof(y));
            SetAxis(z, outputZLow, outputZHigh, nameof(z));
            // A completed conversion makes a new XYZ set available to firmware.
            dataReady.Value = true;
            UpdateInterrupt1();
            this.Log(LogLevel.Debug, "Sample updated to X={0}, Y={1}, Z={2}.", x, y, z);
        }

        // Public inspection API for automated tests and the optional GUI.
        public byte ReadRegister(int address)
        {
            return RegistersCollection.Read(ValidateByte(address, nameof(address)));
        }

        // Public configuration API for automated tests and the optional GUI.
        // Register permissions and callbacks are still enforced by the framework.
        public void WriteRegister(int address, int value)
        {
            RegistersCollection.Write(ValidateByte(address, nameof(address)), ValidateByte(value, nameof(value)));
        }

        // IPeripheral contract inherited by II2CPeripheral.
        // Represents a hardware reset of the modeled device.
        public void Reset()
        {
            RegistersCollection.Reset();
            FinishTransmission();
            Interrupt1.Unset();
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
                // DS11811 Rev. 9, datasheet section 6.1.1: SUB selects the register.
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
                var register = selectedRegister;
                result[i] = RegistersCollection.Read(register);
                this.Log(LogLevel.Noisy, "I2C read: register 0x{0:X2} => 0x{1:X2}.", register, result[i]);
                AcknowledgeDataReady(register);
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

        private void HandleAcquisitionConfigurationChanged()
        {
            // Entering power-down invalidates any pending data-ready indication.
            if(!AcquisitionEnabled)
            {
                dataReady.Value = false;
            }
            UpdateInterrupt1();
        }

        private void AcknowledgeDataReady(byte register)
        {
            // AN5038 section 3.2: in the default latched mode, reading any axis
            // high byte acknowledges the available XYZ set and clears DRDY.
            if(dataReady.Value && (register == (byte)RegisterId.OutputXHigh
                || register == (byte)RegisterId.OutputYHigh
                || register == (byte)RegisterId.OutputZHigh))
            {
                dataReady.Value = false;
                UpdateInterrupt1();
                this.Log(LogLevel.Debug, "XYZ data acknowledged; DRDY cleared.");
            }
        }

        private void IncrementSelectedRegister()
        {
            if(automaticAddressIncrement.Value)
            {
                selectedRegister++;
            }
        }

        private void UpdateInterrupt1()
        {
            // CTRL4 only routes the pending data-ready event; it does not create one.
            var state = dataReady.Value && dataReadyInterruptEnabled.Value;
            Interrupt1.Set(state);
            this.Log(LogLevel.Noisy, "INT1 data-ready state changed to {0}.", state);
        }

        private static byte ValidateByte(int value, string parameterName)
        {
            if(value < byte.MinValue || value > byte.MaxValue)
            {
                throw new ArgumentOutOfRangeException(parameterName, "Register addresses and values must fit in one byte.");
            }
            return (byte)value;
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

        // Register addresses from DS11811 Rev. 9, datasheet section 8.
        private enum RegisterId : byte
        {
            WhoAmI = 0x0F,
            Control1 = 0x20,
            Control2 = 0x21,
            Control4Int1PadControl = 0x23,
            Status = 0x27,
            OutputXLow = 0x28,
            OutputXHigh = 0x29,
            OutputYLow = 0x2A,
            OutputYHigh = 0x2B,
            OutputZLow = 0x2C,
            OutputZHigh = 0x2D,
        }

        private IFlagRegisterField automaticAddressIncrement;
        private IFlagRegisterField dataReadyInterruptEnabled;
        private IValueRegisterField outputDataRate;
        // Handles returned by WithValueField; their .Value accesses the register fields.
        private IValueRegisterField outputXLow;
        private IValueRegisterField outputXHigh;
        private IValueRegisterField outputYLow;
        private IValueRegisterField outputYHigh;
        private IValueRegisterField outputZLow;
        private IValueRegisterField outputZHigh;
        private byte selectedRegister;
        private IFlagRegisterField dataReady;
        private bool waitingForRegister;
    }
}
