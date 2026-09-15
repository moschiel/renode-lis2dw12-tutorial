# Executed by Renode's embedded Python runtime.
import json

uart_lines = []
uart_partial = []


def on_uart_byte(value):
    if value == 10:
        uart_lines.append(''.join(uart_partial))
        del uart_partial[:]
        if len(uart_lines) > 80:
            del uart_lines[0]
    elif value != 13:
        uart_partial.append(chr(value))


monitor.Machine['sysbus.usart2'].CharReceived += on_uart_byte


def mc_lab_state():
    accel = monitor.Machine['sysbus.i2c1.accel']
    x = int(accel.SampleX) & 0xFFFF
    y = int(accel.SampleY) & 0xFFFF
    z = int(accel.SampleZ) & 0xFFFF
    print(json.dumps({
        'seconds': float(monitor.Machine.ElapsedVirtualTime.TimeElapsed.TotalSeconds),
        'registers': {
            'WHO_AM_I': int(accel.ReadRegister(0x0F)),
            'CTRL1': int(accel.ReadRegister(0x20)),
            'CTRL2': int(accel.ReadRegister(0x21)),
            'CTRL4_INT1_PAD_CTRL': int(accel.ReadRegister(0x23)),
            'STATUS': int(accel.ReadRegister(0x27)),
            'OUT_X_L': x & 0xFF,
            'OUT_X_H': x >> 8,
            'OUT_Y_L': y & 0xFF,
            'OUT_Y_H': y >> 8,
            'OUT_Z_L': z & 0xFF,
            'OUT_Z_H': z >> 8,
        },
        'sample': {
            'x': int(accel.SampleX),
            'y': int(accel.SampleY),
            'z': int(accel.SampleZ),
        },
        'interrupt1': bool(accel.Interrupt1.IsSet),
        'uart': list(uart_lines),
    }))
