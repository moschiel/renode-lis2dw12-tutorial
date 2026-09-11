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
            // DS11811 Rev. 9, section 8.3: WHO_AM_I is read-only and resets to 0x44.
            RegistersCollection.DefineRegister(0x0F, 0x44)
                .WithValueField(0, 8, FieldMode.Read, name: "WHO_AM_I");
            // DS11811 Rev. 9, section 8.4: configuration is stored, while
            // physical ODR, power, noise and resolution effects are out of scope.
            RegistersCollection.DefineRegister(0x20, 0x00)
                .WithValueField(0, 8, out control1, name: "CTRL1");
            // DS11811 Rev. 9, section 8.5: only IF_ADD_INC is modeled for now.
            RegistersCollection.DefineRegister(0x21, 0x04)
                .WithReservedBits(0, 2)
                .WithFlag(2, out automaticAddressIncrement, name: "IF_ADD_INC")
                .WithReservedBits(3, 5);
            Reset();
        }

        public ByteRegisterCollection RegistersCollection { get; }

        // Side-effect-free values used by optional visualization tooling.
        public byte WhoAmI => 0x44;
        public byte Control1 => (byte)control1.Value;
        public byte Control2 => automaticAddressIncrement.Value ? (byte)0x04 : (byte)0x00;

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

        private void ClearSelection()
        {
            selectedRegister = 0;
            waitingForRegister = true;
        }

        private IValueRegisterField control1;
        private IFlagRegisterField automaticAddressIncrement;
        private byte selectedRegister;
        private bool waitingForRegister;
    }
}
