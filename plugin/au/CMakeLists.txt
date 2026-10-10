# Audio Unit (AUv2) version of the plugin, for Logic and other AU-only hosts: free-audio's clap-wrapper (MIT) turns
# the CLAP that `cargo xtask bundle-universal` builds into an AU with that CLAP embedded in the bundle.
#   cmake -S au -B au/build -DCLAP_BUNDLE="$PWD/target/bundled/Mortiflix Singer.clap" && cmake --build au/build --config Release
cmake_minimum_required(VERSION 3.21)
set(CMAKE_OSX_DEPLOYMENT_TARGET 11.0 CACHE STRING "")
set(CMAKE_OSX_ARCHITECTURES "arm64;x86_64" CACHE STRING "")
project(mortiflix_singer_au VERSION 0.1.1 LANGUAGES C CXX OBJC OBJCXX)
set(CMAKE_CXX_STANDARD 17)

if (NOT CLAP_BUNDLE)
    message(FATAL_ERROR "set CLAP_BUNDLE to the built 'Mortiflix Singer.clap'")
endif ()

set(CLAP_WRAPPER_DOWNLOAD_DEPENDENCIES TRUE CACHE BOOL "")
include(FetchContent)
FetchContent_Declare(clap-wrapper GIT_REPOSITORY https://github.com/free-audio/clap-wrapper.git GIT_TAG v0.16.0)
FetchContent_MakeAvailable(clap-wrapper)

add_library(mortiflix_singer_auv2 MODULE)
target_add_auv2_wrapper(
    TARGET mortiflix_singer_auv2
    OUTPUT_NAME "Mortiflix Singer"
    BUNDLE_IDENTIFIER "com.mortiflix.singer.bridge.auv2"
    BUNDLE_VERSION "${PROJECT_VERSION}"
    INSTRUMENT_TYPE "aumu"
    MANUFACTURER_NAME "Mortiflix"
    MANUFACTURER_CODE "Mrtf"
    SUBTYPE_CODE "MfSg"
    MACOS_EMBEDDED_CLAP_LOCATION "${CLAP_BUNDLE}"
)
