cmake_minimum_required(VERSION 3.13)

set(PICO_BOARD pico2 CACHE STRING "Board type")

include(pico_sdk_import.cmake)

project(mlx_thermal C CXX ASM)
set(CMAKE_C_STANDARD 11)

pico_sdk_init()

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
# Shared project code: board pin map, logging
# ---------------------------------------------------------------------------
add_library(project_common INTERFACE)
target_include_directories(project_common INTERFACE ${CMAKE_CURRENT_LIST_DIR}/src)
target_link_libraries(project_common INTERFACE pico_stdlib segger_rtt)

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
target_link_libraries(stream_usb PUBLIC project_common sensor tinyusb_device pico_unique_id)

add_firmware(mlx_thermal src/main.c)		# main firmware (32 Hz)
target_link_libraries(mlx_thermal PRIVATE sensor stream_usb)

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

# I2C line rise time test (M2)
add_firmware(rise_test tests/rise_test.c)
pico_generate_pio_header(rise_test ${CMAKE_CURRENT_LIST_DIR}/tests/rise_test.pio)
target_link_libraries(rise_test PRIVATE hardware_pio)
