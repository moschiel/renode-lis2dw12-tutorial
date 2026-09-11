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


def mc_assert_auto_increment_uart():
    expected = ['WHO_AM_I: 0x44', 'IF_ADD_INC: PASS']
    assert uart_lines == expected, 'UART mismatch: ' + str(uart_lines)
    print('PASS firmware: WHO_AM_I and IF_ADD_INC')


def mc_assert_reference_auto_increment_uart():
    expected = ['WHO_AM_I: 0x44', 'IF_ADD_INC: ERROR']
    assert uart_lines == expected, 'UART mismatch: ' + str(uart_lines)
    print('PASS reference firmware: I2C transactions complete; known auto-increment difference observed')
