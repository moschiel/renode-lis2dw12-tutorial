# Executed by Renode's embedded Python runtime during firmware checks.
uart_lines = []
uart_partial = []


def on_uart_byte(value):
    if value == 10:
        uart_lines.append(''.join(uart_partial))
        del uart_partial[:]
    elif value != 13:
        uart_partial.append(chr(value))


monitor.Machine['sysbus.usart2'].CharReceived += on_uart_byte


def mc_assert_control_uart():
    expected = ['WHO_AM_I: 0x44', 'CTRL1/CTRL2: PASS']
    assert uart_lines == expected, 'UART mismatch: ' + str(uart_lines)
    print('PASS firmware: WHO_AM_I and control registers')


def mc_assert_reference_control_uart():
    expected = ['WHO_AM_I: 0x44', 'CTRL1/CTRL2: ERROR']
    assert uart_lines == expected, 'UART mismatch: ' + str(uart_lines)
    print('PASS reference firmware: I2C transactions complete; known control-register difference observed')
