idf_component_register(SRCS "ota.cpp" INCLUDE_DIRS "." REQUIRES agentshell_storage esp_http_client app_update mbedtls espressif__cjson EMBED_TXTFILES "release-public.pem")
