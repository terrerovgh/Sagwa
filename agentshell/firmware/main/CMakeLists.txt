idf_component_register(SRCS "app_main.cpp" INCLUDE_DIRS "." REQUIRES agentshell_hal agentshell_ui agentshell_protocol agentshell_network agentshell_storage agentshell_audio agentshell_ota nvs_flash esp_timer esp_system esp_app_format esp_driver_usb_serial_jtag)
if(AGENTSHELL_TEST_BOOT_FAILURE)
  target_compile_definitions(${COMPONENT_LIB} PRIVATE AGENTSHELL_TEST_BOOT_FAILURE=1)
endif()
