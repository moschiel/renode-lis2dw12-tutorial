# Executed by Renode's embedded Python runtime during firmware checks.
from System import Environment

uart_lines = []
uart_partial = []
headless_test = Environment.GetEnvironmentVariable('RENODE_TEST_HEADLESS') == '1'


def on_uart_byte(value):
    if value == 10:
        uart_lines.append(''.join(uart_partial))
        del uart_partial[:]
    elif value != 13:
        uart_partial.append(chr(value))


monitor.Machine['sysbus.usart2'].CharReceived += on_uart_byte

if not headless_test:
    monitor.Parse('showAnalyzer usart2')


def assert_current_line(expected, description):
    assert uart_lines.count(expected) == 1, 'UART mismatch: ' + str(uart_lines)
    print('PASS firmware: ' + description)


def mc_finish_firmware_test():
    if headless_test:
        monitor.Parse('quit')


def mc_assert_xyz_uart():
    assert_current_line('XYZ: 1600,-3200,16000', 'XYZ sample')


def mc_assert_auto_increment_uart():
    assert_current_line('IF_ADD_INC: PASS', 'IF_ADD_INC behavior')


def mc_assert_data_ready_polling_uart():
    assert_current_line('DRDY_POLL: PASS', 'data-ready polling')


def mc_assert_data_ready_interrupt_uart():
    assert_current_line('DRDY_INT1: PASS', 'data-ready interrupt')


def mc_assert_reference_firmware_uart():
    expected = [
        'Hello from STM32', 'WHO_AM_I: 0x44', 'XYZ: 1600,-3200,16000', 'IF_ADD_INC: PASS',
        'DRDY_POLL: PASS', 'DRDY_INT1: PASS',
    ]
    assert uart_lines[:len(expected)] == expected, 'UART mismatch: ' + str(uart_lines)
    print('PASS reference firmware: same XYZ and IF_ADD_INC behavior')
