# Top-level build file.
#
# It only sets up the Pico SDK and then builds firmware/. It lives in the
# project root so the VS Code "Raspberry Pi Pico" extension finds the
# project when the whole repository is opened (the extension looks for a
# CMakeLists.txt in the workspace root).
#
# Command line build (pinned tool versions, see scripts/env.ps1):
#   scripts/build.ps1

cmake_minimum_required(VERSION 3.13)

# == DO NOT EDIT THE FOLLOWING LINES for the Raspberry Pi Pico VS Code Extension to work ==
if(WIN32)
    set(USERHOME $ENV{USERPROFILE})
else()
    set(USERHOME $ENV{HOME})
endif()
set(sdkVersion 2.3.1)
set(toolchainVersion 15_2_Rel1)
set(picotoolVersion 2.3.1)
set(picoVscode ${USERHOME}/.pico-sdk/cmake/pico-vscode.cmake)
if (EXISTS ${picoVscode})
    include(${picoVscode})
endif()
# ========================================================================================

set(PICO_BOARD pico2 CACHE STRING "Board type")

include(firmware/pico_sdk_import.cmake)

project(mlx_thermal C CXX ASM)
set(CMAKE_C_STANDARD 11)

pico_sdk_init()

add_subdirectory(firmware)
