"""Lager Demo Script"""

from lager import Net, NetType
import time
import logging

# Suppress debug logging 
logging.disable(logging.WARNING)

# Connect to instruments
supply1 = Net.get("supply1", type=NetType.PowerSupply)
arm1 = Net.get("arm1", type=NetType.Arm)
debug1 = Net.get("debug1", type=NetType.Debug)
usb1 = Net.get("usb1", type=NetType.Usb)
adc1 = Net.get("adc1", type=NetType.ADC)

# Control robot arm
print("Positioning arm...")
print(" Moving to work position...")
arm1.move_to(200, 350, 50)
time.sleep(2) # Wait for arm to reach position
print(" Returning to home...")
arm1.go_home()
time.sleep(2) # Wait for arm to reach home position (0, 300, 0)

# Enable power supply
print("Powering channel 1 to 3.0V...")
supply1.set_voltage(3.0)
supply1.enable()
time.sleep(0.5)

# Toggle debug probe via USB hub
print("Resetting debug probe...")
usb1.disable()
time.sleep(1)
usb1.enable()
time.sleep(2)

# Erase, reset, and flash firmware
print("Flashing firmware...")
print(" Connecting to debug probe...")
debug1.connect()
print(" Erasing chip...")
debug1.erase()
print(" Resetting device...")
debug1.reset()
print(" Flashing firmware...")
debug1.flash("nrf_blinky.hex")
print(" Disconnecting...")
debug1.disconnect()

# Take voltage measurement
print("Reading voltage...")
voltage = adc1.input()
print(f"Measured: {voltage:.3f}V")

# Cleanup
print("Cleaning up...")
supply1.disable()

# Report result
print("TEST PASSED!" if 2.95 <= voltage <= 3.05 else "TEST FAILED!")