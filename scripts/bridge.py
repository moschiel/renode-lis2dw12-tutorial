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
    print(json.dumps({
        'registers': {
            'WHO_AM_I': int(accel.WhoAmI),
            'CTRL1': int(accel.Control1),
            'CTRL2': int(accel.Control2),
        },
        'uart': list(uart_lines),
    }))
