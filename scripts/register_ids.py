# Shared register names for readable Monitor and RESC test commands.
class RegisterId:
    # Temporary register used only by the transport test in tutorial section 1.
    TRANSPORT_TEST = 0x10

    WHO_AM_I = 0x0F
    CTRL1 = 0x20
    CTRL2 = 0x21
    CTRL4_INT1_PAD_CTRL = 0x23
    STATUS = 0x27
    OUT_X_L = 0x28
    OUT_X_H = 0x29
    OUT_Y_L = 0x2A
    OUT_Y_H = 0x2B
    OUT_Z_L = 0x2C
    OUT_Z_H = 0x2D
