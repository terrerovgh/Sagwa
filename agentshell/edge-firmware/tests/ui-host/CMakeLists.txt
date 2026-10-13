cmake_minimum_required(VERSION 3.20)
project(sagwa_ui_host LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(EDGE_ROOT "${CMAKE_CURRENT_LIST_DIR}/../..")
get_filename_component(EDGE_ROOT "${EDGE_ROOT}" ABSOLUTE)
set(LV_BUILD_CONF_PATH "${CMAKE_CURRENT_LIST_DIR}/lv_conf.h" CACHE PATH "" FORCE)
set(CONFIG_LV_BUILD_DEMOS OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(CONFIG_LV_USE_THORVG_INTERNAL OFF CACHE BOOL "" FORCE)
add_compile_options(-fsanitize=address,undefined -g)
add_link_options(-fsanitize=address,undefined)
add_subdirectory("${EDGE_ROOT}/managed_components/lvgl__lvgl" lvgl)
add_library(cjson STATIC "${EDGE_ROOT}/managed_components/espressif__cjson/cJSON/cJSON.c")
target_include_directories(cjson PUBLIC "${EDGE_ROOT}/managed_components/espressif__cjson/cJSON")
add_executable(sagwa-ui-gallery host.cpp
  "${EDGE_ROOT}/components/sagwa_edge/graphics.cpp"
  "${EDGE_ROOT}/components/sagwa_edge/core.cpp"
  "${EDGE_ROOT}/components/sagwa_edge/rig_assets.c"
  "${EDGE_ROOT}/components/sagwa_edge/badges.c"
  "${EDGE_ROOT}/components/sagwa_edge/fonts/inter16.c")
target_compile_definitions(sagwa-ui-gallery PRIVATE SAGWA_UI_HOST=1 LV_LVGL_H_INCLUDE_SIMPLE)
target_include_directories(sagwa-ui-gallery BEFORE PRIVATE shims
  "${EDGE_ROOT}/components/sagwa_edge/include"
  "${EDGE_ROOT}/components/agentshell_storage"
  "${EDGE_ROOT}/components/agentshell_network")
target_link_libraries(sagwa-ui-gallery PRIVATE lvgl cjson)
