cmake_minimum_required(VERSION 3.24)
project(mafia_cuda LANGUAGES CXX CUDA)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CUDA_STANDARD 17)
if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES native)
endif()
find_package(Python3 REQUIRED COMPONENTS Interpreter)
set(DATA_DIR "${CMAKE_CURRENT_SOURCE_DIR}/data" CACHE PATH "Local game data")
add_custom_command(OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/items_generated.hpp
  COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/export_items.py
    ${DATA_DIR} ${CMAKE_CURRENT_BINARY_DIR}/items_generated.hpp
  DEPENDS tools/export_items.py ${DATA_DIR}/catalog.json ${DATA_DIR}/variants.json)
add_executable(mafia_cuda src/main.cu ${CMAKE_CURRENT_BINARY_DIR}/items_generated.hpp)
target_include_directories(mafia_cuda PRIVATE src ${CMAKE_CURRENT_BINARY_DIR})
target_compile_options(mafia_cuda PRIVATE $<$<COMPILE_LANGUAGE:CUDA>:--fmad=false>)
enable_testing()
add_test(NAME cuda_self_test COMMAND mafia_cuda --self-test)
