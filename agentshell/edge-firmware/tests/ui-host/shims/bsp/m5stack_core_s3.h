#pragma once
#include "lvgl.h"
constexpr int ESP_OK = 0;
struct HostLvglConfig { int task_affinity = 0; uint32_t task_max_sleep_ms = 0; };
struct bsp_display_cfg_t {
  HostLvglConfig lvgl_port_cfg;
  uint32_t buffer_size = 0;
  bool double_buffer = false;
  struct { bool buff_dma = false, buff_spiram = false; } flags;
};
#define ESP_LVGL_PORT_INIT_CONFIG() HostLvglConfig{}
using esp_lcd_panel_io_handle_t = void *;
struct esp_lcd_panel_io_event_data_t {};
struct esp_lcd_panel_io_callbacks_t {
  bool (*on_color_trans_done)(esp_lcd_panel_io_handle_t,
                            esp_lcd_panel_io_event_data_t *, void *) = nullptr;
};
int esp_lcd_panel_io_register_event_callbacks(esp_lcd_panel_io_handle_t,
                                             const esp_lcd_panel_io_callbacks_t *, void *);
esp_lcd_panel_io_handle_t bsp_display_get_panel_io();
lv_display_t *bsp_display_start_with_config(const bsp_display_cfg_t *);
bool bsp_display_lock(uint32_t);
void bsp_display_unlock();
void bsp_display_backlight_on();
void bsp_display_brightness_set(int);
