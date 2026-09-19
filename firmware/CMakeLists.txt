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

# ---------------------------------------------------------------------------
# Shared project code: board pin map, logging
# ---------------------------------------------------------------------------
add_library(project_common INTERFACE)
target_include_directories(project_common INTERFACE ${CMAKE_CURRENT_LIST_DIR}/src)
target_link_libraries(project_common INTERFACE pico_stdlib segger_rtt)

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
add_firmware(mlx_thermal src/main.c)		# main firmware
add_firmware(pin_test tests/pin_test.c)		# Logic 8 wiring check
