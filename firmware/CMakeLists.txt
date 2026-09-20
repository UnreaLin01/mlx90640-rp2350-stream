# Firmware targets. The SDK setup is in the top-level CMakeLists.txt, which
# adds this directory; do not configure this directory on its own.

# ---------------------------------------------------------------------------
# SEGGER RTT (third-party code, kept unmodified)
# ---------------------------------------------------------------------------
set(RTT_DIR ${CMAKE_CURRENT_LIST_DIR}/../third_party/SEGGER_RTT)
add_library(segger_rtt STATIC
	${RTT_DIR}/RTT/SEGGER_RTT.c
	${RTT_DIR}/RTT/SEGGER_RTT_printf.c
	${RTT_DIR}/RTT/SEGGER_RTT_ASM_ARMv7M.S
)
target_include_directories(segger_rtt PUBLIC
	${RTT_DIR}/RTT
	${RTT_DIR}/Config
)
# Bigger log buffer (default 1 KB) so a full EEPROM dump fits.
# Set here instead of editing the RTT config file.
target_compile_definitions(segger_rtt PUBLIC BUFFER_SIZE_UP=8192)

# ---------------------------------------------------------------------------
# Melexis MLX90640 library (third-party code, kept unmodified)
# ---------------------------------------------------------------------------
set(MLX_DIR ${CMAKE_CURRENT_LIST_DIR}/../third_party/mlx90640-library)
# Built as object files and packed into the `sensor` library below, because
# the Melexis code and our I2C functions call each other.
add_library(mlx90640_api OBJECT ${MLX_DIR}/functions/MLX90640_API.c)
target_include_directories(mlx90640_api PUBLIC ${MLX_DIR}/headers)

# ---------------------------------------------------------------------------
# WIZnet W6300 Ethernet (third-party code, kept unmodified)
#
# Only the files this project needs are built, with the settings the WIZnet
# build uses for the W6300-EVB-Pico2: chip W6300, QSPI in quad mode.
# The chip is driven over QSPI by PIO on GPIO15-22 (fixed by the board).
# ---------------------------------------------------------------------------
set(WIZ_DIR ${CMAKE_CURRENT_LIST_DIR}/../third_party/WIZnet-PICO-C)
set(WIZ_IO ${WIZ_DIR}/libraries/ioLibrary_Driver)
set(WIZ_PORT ${WIZ_DIR}/port)

add_library(wiznet STATIC
	${WIZ_IO}/Ethernet/socket.c
	${WIZ_IO}/Ethernet/wizchip_conf.c
	${WIZ_IO}/Ethernet/W6300/w6300.c
	${WIZ_IO}/Internet/DHCP/dhcp.c
	${WIZ_PORT}/ioLibrary_Driver/src/wizchip_spi.c
	${WIZ_PORT}/ioLibrary_Driver/src/wizchip_gpio_irq.c
	${WIZ_PORT}/ioLibrary_Driver/src/wizchip_qspi_pio.c
	${WIZ_PORT}/timer/timer.c
)
pico_generate_pio_header(wiznet ${WIZ_PORT}/ioLibrary_Driver/src/wizchip_qspi_pio.pio)
target_compile_definitions(wiznet PUBLIC
	_WIZCHIP_=W6300
	DEVICE_BOARD_NAME=W6300_EVB_PICO2
	_WIZCHIP_QSPI_MODE_=QSPI_QUAD_MODE
)
# SYSTEM: do not report warnings from WIZnet's headers in our files.
target_include_directories(wiznet SYSTEM PUBLIC
	${WIZ_IO}/Ethernet
	${WIZ_IO}/Ethernet/W6300
	${WIZ_IO}/Internet/DHCP
	${WIZ_PORT}
	${WIZ_PORT}/ioLibrary_Driver/inc
	${WIZ_PORT}/timer
)
target_link_libraries(wiznet PUBLIC
	pico_stdlib hardware_pio hardware_spi hardware_dma hardware_clocks
)

# ---------------------------------------------------------------------------
# Shared project code: board pin map, logging
# ---------------------------------------------------------------------------
add_library(project_common STATIC src/log.c)
target_compile_options(project_common PRIVATE -Wall -Wextra)
target_include_directories(project_common PUBLIC ${CMAKE_CURRENT_LIST_DIR}/src)
target_link_libraries(project_common PUBLIC pico_stdlib hardware_sync segger_rtt)

# Sensor access: I2C bus driver, the I2C functions the Melexis library
# needs, and sensor control (setup, wait for data, read a subpage)
add_library(sensor STATIC
	src/i2c_bus.c
	src/mlx90640_i2c.c
	src/sensor.c
	$<TARGET_OBJECTS:mlx90640_api>
)
target_compile_options(sensor PRIVATE -Wall -Wextra)
target_include_directories(sensor PUBLIC ${MLX_DIR}/headers)
target_link_libraries(sensor PUBLIC project_common hardware_i2c hardware_dma m)

# Add one firmware image. Every image uses the same rules:
# logs go to RTT only, and USB/UART stdio stays off.
function(add_firmware name)
	add_executable(${name} ${ARGN})
	target_compile_options(${name} PRIVATE -Wall -Wextra)
	target_link_libraries(${name} PRIVATE project_common)
	pico_enable_stdio_usb(${name} 0)
	pico_enable_stdio_uart(${name} 0)
	pico_add_extra_outputs(${name})
endfunction()

# ---------------------------------------------------------------------------
# Firmware images
# ---------------------------------------------------------------------------
# Streaming: protocol packets + USB CDC transport (TinyUSB, own descriptors;
# the SDK's stdio_usb stays off because USB carries only image data)
add_library(stream_usb STATIC
	src/protocol.c
	src/stream.c
	src/transport_usb.c
	src/usb_descriptors.c
)
target_compile_options(stream_usb PRIVATE -Wall -Wextra)
target_link_libraries(stream_usb PUBLIC
	project_common sensor tinyusb_device pico_unique_id pico_usb_reset)
# picotool can restart the board into BOOTSEL by itself (no button press),
# see src/usb_descriptors.c.
target_compile_definitions(stream_usb PUBLIC
	PICO_ENABLE_USB_RESET_VIA_VENDOR_INTERFACE=1
	PICO_USB_RESET_INCLUDE_DEFAULT_APP_DRIVER_CB=1
	PICO_USB_RESET_SUPPORT_MS_OS_20_DESCRIPTOR=1
	PICO_USB_RESET_MS_OS_20_DESCRIPTOR_ITF=2
)

# Same protocol over UDP (M7). Only the transport differs; main.c is shared.
add_library(stream_udp STATIC
	src/protocol.c
	src/stream.c
	src/transport_udp.c
	src/net.c
)
target_compile_options(stream_udp PRIVATE -Wall -Wextra)
# pico_multicore: the network task runs on core 1 (see transport_udp.c).
# Core 1 gets 4 KB of stack (default 2 KB): the WIZnet and DHCP code nests
# a few levels deep.
target_link_libraries(stream_udp PUBLIC
	project_common sensor wiznet pico_unique_id pico_multicore)
target_compile_definitions(stream_udp PUBLIC PICO_CORE1_STACK_SIZE=4096)

add_firmware(mlx_thermal src/main.c)		# main firmware, USB (32 Hz)
target_link_libraries(mlx_thermal PRIVATE sensor stream_usb)

# Same firmware streaming over Ethernet instead of USB (M7)
add_firmware(mlx_thermal_udp src/main.c)
target_link_libraries(mlx_thermal_udp PRIVATE sensor stream_udp)

# Same firmware at other subpage rates, for timing comparison (M3)
foreach(rate 16 64)
	add_firmware(mlx_thermal_${rate}hz src/main.c)
	target_compile_definitions(mlx_thermal_${rate}hz PRIVATE SENSOR_RATE=SENSOR_RATE_${rate}HZ)
	target_link_libraries(mlx_thermal_${rate}hz PRIVATE sensor stream_usb)
endforeach()
add_firmware(pin_test tests/pin_test.c)		# Logic 8 wiring check

# EEPROM read test at two clock rates (M2)
foreach(hz 400000 1000000)
	math(EXPR khz "${hz} / 1000")
	add_firmware(eeprom_test_${khz}k tests/eeprom_test.c)
	target_compile_definitions(eeprom_test_${khz}k PRIVATE I2C_TEST_HZ=${hz})
	target_link_libraries(eeprom_test_${khz}k PRIVATE sensor)
endforeach()

# Long-run test at 1 MHz: read back to back, print a status line every 500 reads
add_firmware(eeprom_soak_1000k tests/eeprom_test.c)
target_compile_definitions(eeprom_soak_1000k PRIVATE
	I2C_TEST_HZ=1000000 READ_INTERVAL_MS=0 REPORT_EVERY=500)
target_link_libraries(eeprom_soak_1000k PRIVATE sensor)

# Ethernet bring-up test (M6)
add_firmware(net_test tests/net_test.c src/net.c)
target_link_libraries(net_test PRIVATE wiznet pico_unique_id)

# I2C line rise time test (M2)
add_firmware(rise_test tests/rise_test.c)
pico_generate_pio_header(rise_test ${CMAKE_CURRENT_LIST_DIR}/tests/rise_test.pio)
target_link_libraries(rise_test PRIVATE hardware_pio)
