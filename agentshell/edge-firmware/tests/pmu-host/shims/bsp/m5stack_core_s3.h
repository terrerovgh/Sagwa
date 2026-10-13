#pragma once
#include <stddef.h>
#include "esp_err.h"
typedef void *i2c_master_dev_handle_t;
typedef void *esp_io_expander_handle_t;
typedef struct { int dev_addr_length; int device_address; int scl_speed_hz; } i2c_device_config_t;
#define I2C_ADDR_BIT_LEN_7 0
#define IO_EXPANDER_OUTPUT 1
#define BSP_SD_EN 0
#define BSP_LCD_EN 1
#define BSP_TOUCH_EN 2
#define BSP_SPEAKER_EN 3
#define BSP_MIC_EN 4
#define BSP_CAMERA_EN 5
#define BSP_USB_EN 6
typedef enum {BSP_FEATURE_SD,BSP_FEATURE_LCD,BSP_FEATURE_TOUCH,BSP_FEATURE_SPEAKER,BSP_FEATURE_MIC,BSP_FEATURE_CAMERA,BSP_FEATURE_USB} bsp_feature_t;
esp_err_t bsp_i2c_init(void);
void *bsp_i2c_get_handle(void);
esp_err_t i2c_master_bus_add_device(void *, const i2c_device_config_t *, i2c_master_dev_handle_t *);
esp_err_t i2c_master_bus_rm_device(i2c_master_dev_handle_t);
esp_err_t i2c_master_transmit_receive(i2c_master_dev_handle_t,const uint8_t*,size_t,uint8_t*,size_t,int);
esp_err_t i2c_master_transmit(i2c_master_dev_handle_t,const uint8_t*,size_t,int);
esp_io_expander_handle_t bsp_io_expander_init(void);
esp_err_t esp_io_expander_set_dir(esp_io_expander_handle_t,int,int);
esp_err_t esp_io_expander_set_level(esp_io_expander_handle_t,int,bool);
esp_err_t bsp_pmu_init(void);
i2c_master_dev_handle_t bsp_pmu_get_handle(void);
esp_err_t bsp_feature_enable(bsp_feature_t,bool);
esp_err_t bsp_display_brightness_set(int);
