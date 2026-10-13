#pragma once
#include "esp_err.h"
#define unlikely(x) (x)
#define ESP_RETURN_ON_ERROR(call,tag,...) do { (void)(tag); esp_err_t rc_=(call); if(rc_!=ESP_OK)return rc_; } while(0)
#define ESP_RETURN_ON_FALSE(cond,rc,tag,...) do { (void)(tag); if(!(cond))return(rc); } while(0)
#define ESP_LOGI(tag,...) ((void)(tag))
