// Pin map: Espressif m5stack_core_s3 BSP; power/IMU/RTC: M5Unified 0.2.24.
// Camera: GC0308 on DVP; SCCB reuses M5Unified's I2C controller.
#include "hal.hpp"
#include "M5Unified.h"
#include "esp_camera.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "esp_system.h"
#include "esp_vfs_fat.h"
#include "driver/sdspi_host.h"
#include "nvs.h"
#include <cmath>
#include <ctime>
namespace shell {
static bool key_down, key_press, key_release, light_fresh;
static bool light_ok, near, calibrating, calibrated;
static int64_t sampled, cal_start;
static float light_value, proximity, low[3], high[3], offset[3],
    scale[3] = {1, 1, 1};
static bool accel_ok, gyro_ok, mag_ok;
static float accel[3], gyro[3], mag[3];
static bool card;
static void calibration_store(bool write) {
  nvs_handle_t handle;
  if(nvs_open("agentshell",write?NVS_READWRITE:NVS_READONLY,&handle)!=ESP_OK)return;
  float data[6];size_t size=sizeof(data);
  if(write) {
    for(int i=0;i<3;i++) {data[i]=offset[i];data[i+3]=scale[i];}
    nvs_set_blob(handle,"mag_cal",data,sizeof(data));nvs_commit(handle);
  } else if(nvs_get_blob(handle,"mag_cal",data,&size)==ESP_OK&&size==sizeof(data)) {
    bool valid=true;
    for(int i=0;i<3;i++) valid &= std::isfinite(data[i])&&std::isfinite(data[i+3])&&data[i+3]>0.05f&&data[i+3]<20.f;
    if(valid) {for(int i=0;i<3;i++) {offset[i]=data[i];scale[i]=data[i+3];}calibrated=true;}
  }
  nvs_close(handle);
}
bool hal_begin() {
  auto cfg = M5.config();
  cfg.pmic_button = false;
  cfg.external_spk = false;
  cfg.external_imu = false;
  cfg.internal_mic = true;
  cfg.internal_spk = true;
  M5.begin(cfg);
  calibration_store(false);
  if(M5.Rtc.isEnabled()) {
    m5::rtc_datetime_t date;
    if(M5.Rtc.getDateTime(&date)&&date.date.year>=2025)M5.Rtc.setSystemTimeFromRtc();
  }
  M5.Display.setRotation(1);
  M5.Display.setBrightness(100);
  uint8_t id = 0;
  light_ok = M5.In_I2C.readRegister(0x23, 0x87, &id, 1, 100000) && id == 0x05;
  if (light_ok) {
    M5.In_I2C.writeRegister8(0x23, 0x80, 1, 100000);
    M5.In_I2C.writeRegister8(0x23, 0x81, 3, 100000);
    M5.In_I2C.writeRegister8(0x23, 0x82, 0x6b, 100000);
  }
  M5.In_I2C.bitOn(0x34, 0x27, 12, 100000);
  M5.In_I2C.bitOn(0x34, 0x41, 15, 100000);
  M5.In_I2C.writeRegister8(0x34, 0x49, 15, 100000);
  return M5.Display.width() == 320 && M5.Display.height() == 240;
}
void hal_update() {
  M5.update();
  key_press = key_release = false;
  uint8_t irq = 0;
  if (M5.In_I2C.readRegister(0x34, 0x49, &irq, 1, 100000) && (irq & 15)) {
    M5.In_I2C.writeRegister8(0x34, 0x49, irq & 15, 100000);
    if (irq & 2) {
      key_down = true;
      key_press = true;
    }
    if (irq & 1) {
      key_down = false;
      key_release = true;
    }
  }
  static int64_t last;
  const int64_t now = esp_timer_get_time();
  if (now - last < 200000)
    return;
  last = now;
  sampled = now;
  accel_ok = M5.Imu.getAccel(accel, accel + 1, accel + 2);
  gyro_ok = M5.Imu.getGyro(gyro, gyro + 1, gyro + 2);
  mag_ok = M5.Imu.getMag(mag, mag + 1, mag + 2);
  uint8_t raw[7];
  bool ok = light_ok && M5.In_I2C.readRegister(0x23, 0x88, raw, 7, 100000);
  light_fresh = ok;
  if (ok) {
    light_value = raw[2] + 256 * raw[3];
    proximity = raw[5] + 256 * (raw[6] & 7);
    near = proximity > 300;
    M5.Display.setBrightness(
        std::min(180, int(45 + 30 * log10f(1 + light_value))));
  } else
    near = false;
  if (calibrating && mag_ok) {
    for (int i = 0; i < 3; i++) {
      low[i] = std::min(low[i], mag[i]);
      high[i] = std::max(high[i], mag[i]);
    }
    if (now - cal_start > 30000000) {
      float r[3], mean = 0;
      bool valid = true;
      for (int i = 0; i < 3; i++) {
        r[i] = (high[i] - low[i]) / 2;
        mean += r[i] / 3;
        valid &= r[i] > 5;
      }
      if (valid) {
        for (int i = 0; i < 3; i++) {
          offset[i] = (high[i] + low[i]) / 2;
          scale[i] = mean / r[i];
        }
        calibrated = true;
        calibration_store(true);
      }
      calibrating = false;
    }
  }
  static int64_t rtc_saved;
  if(M5.Rtc.isEnabled()&&now-rtc_saved>60000000&&time(nullptr)>1735689600) {
    time_t epoch=time(nullptr);tm date={};gmtime_r(&epoch,&date);M5.Rtc.setDateTime(&date);rtc_saved=now;
  }
}
bool key_pressed() { return key_press; }
bool key_released() { return key_release; }
bool key_held() { return key_down; }
bool touch(int &x, int &y, bool &held) {
  auto detail = M5.Touch.getDetail();
  x = detail.x;
  y = detail.y;
  held = detail.isPressed();
  return detail.wasPressed();
}
int battery() { return M5.Power.getBatteryLevel(); }
bool presence() { return near; }
void calibrate(bool start) {
  calibrating = start;
  if (start) {
    cal_start = esp_timer_get_time();
    for (int i = 0; i < 3; i++) {
      low[i] = 1e9;
      high[i] = -1e9;
    }
  }
}
static cJSON *reading(bool ok, const char *unit, const float *values,
                      int axes) {
  for(int i=0;i<axes;i++) ok &= std::isfinite(values[i]);
  cJSON *r = cJSON_CreateObject();
  cJSON_AddBoolToObject(r, "available", ok);
  cJSON_AddStringToObject(r, "unit", unit);
  cJSON_AddStringToObject(r, "status", ok ? "ok" : "unavailable");
  const bool fresh = sampled && esp_timer_get_time() - sampled < 3000000;
  cJSON_AddNumberToObject(r, "age_s",
                          sampled ? (esp_timer_get_time() - sampled) / 1e6 : 0);
  if (!ok || !fresh)
    cJSON_AddNullToObject(r, "value");
  else if (axes == 1)
    cJSON_AddNumberToObject(r, "value", values[0]);
  else {
    cJSON *a = cJSON_AddArrayToObject(r, "value");
    for (int i = 0; i < axes; i++)
      cJSON_AddItemToArray(a, cJSON_CreateNumber(values[i]));
  }
  return r;
}
LocalSensors local_sensors() {return {uint32_t(sampled/1000),light_ok&&light_fresh,light_ok&&light_fresh,accel_ok,gyro_ok,light_value,proximity,accel[0],accel[1],accel[2],gyro[0],gyro[1],gyro[2]};}
cJSON *sensors() {
  cJSON *p = cJSON_CreateObject();
  cJSON_AddItemToObject(p, "acceleration", reading(accel_ok, "g", accel, 3));
  cJSON_AddItemToObject(p, "gyroscope", reading(gyro_ok, "deg/s", gyro, 3));
  float corrected[3];
  for (int i = 0; i < 3; i++)
    corrected[i] = (mag[i] - offset[i]) * scale[i];
  cJSON_AddItemToObject(p, "magnetometer", reading(mag_ok, "uT", corrected, 3));
  cJSON_AddBoolToObject(p, "magnetometer_calibrated", calibrated);
  cJSON_AddBoolToObject(p, "calibrating", calibrating);
  cJSON_AddItemToObject(p, "ambient_light",
                        reading(light_ok && light_fresh, "ADC counts (1x gain)",
                                &light_value, 1));
  cJSON_AddItemToObject(
      p, "proximity",
      reading(light_ok && light_fresh, "relative counts", &proximity, 1));
  cJSON *power = cJSON_AddObjectToObject(p, "power");
  cJSON_AddNumberToObject(power, "battery_pct", M5.Power.getBatteryLevel());
  cJSON_AddNumberToObject(power, "battery_mv", M5.Power.getBatteryVoltage());
  cJSON_AddBoolToObject(power, "charging", M5.Power.isCharging());
  m5::rtc_datetime_t date;
  const bool rtc_ok=M5.Rtc.isEnabled()&&M5.Rtc.getDateTime(&date)&&date.date.year>=2025;
  auto *rtc=cJSON_AddObjectToObject(p,"rtc");cJSON_AddBoolToObject(rtc,"available",rtc_ok);cJSON_AddStringToObject(rtc,"unit","unix seconds UTC");cJSON_AddNumberToObject(rtc,"age_s",0);
  if(rtc_ok) {tm utc=date.get_tm();cJSON_AddNumberToObject(rtc,"value",timegm(&utc));}
  else cJSON_AddNullToObject(rtc,"value");
  cJSON *sd=cJSON_AddObjectToObject(p,"sd");cJSON_AddBoolToObject(sd,"available",card);cJSON_AddStringToObject(sd,"status",card?"mounted":"optional_unavailable");
  cJSON *runtime=cJSON_AddObjectToObject(p,"runtime");
  cJSON_AddNumberToObject(runtime,"uptime_s",esp_timer_get_time()/1e6);
  cJSON_AddNumberToObject(runtime,"free_heap_bytes",heap_caps_get_free_size(MALLOC_CAP_8BIT));
  cJSON_AddNumberToObject(runtime,"minimum_free_heap_bytes",heap_caps_get_minimum_free_size(MALLOC_CAP_8BIT));
  cJSON_AddNumberToObject(runtime,"free_internal_heap_bytes",heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
  cJSON_AddNumberToObject(runtime,"largest_internal_block_bytes",heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
  cJSON_AddNumberToObject(runtime,"reset_reason",esp_reset_reason());
  return p;
}
bool hal_sd_begin() {
  sdmmc_host_t host=SDSPI_HOST_DEFAULT();host.slot=SPI2_HOST;host.max_freq_khz=10000;
  sdspi_device_config_t device=SDSPI_DEVICE_CONFIG_DEFAULT();device.host_id=SPI2_HOST;device.gpio_cs=GPIO_NUM_4;
  esp_vfs_fat_sdmmc_mount_config_t config={};config.format_if_mount_failed=false;config.max_files=2;config.allocation_unit_size=4096;
  sdmmc_card_t *found=nullptr;
  card=esp_vfs_fat_sdspi_mount("/sdcard",&host,&device,&config,&found)==ESP_OK;
  return card;
}
bool capture(std::vector<uint8_t> &out) {
  // Camera reset is AW9523 P1_0. Preserve all other pins and camera's LDO
  // rails.
  M5.In_I2C.bitOn(0x58, 0x03, 1, 100000);
  camera_config_t cfg = {};
  cfg.pin_pwdn = -1;
  cfg.pin_reset = -1;
  cfg.pin_xclk = -1;
  cfg.pin_sccb_sda = -1;
  cfg.pin_sccb_scl = -1;
  cfg.pin_d0 = 39;
  cfg.pin_d1 = 40;
  cfg.pin_d2 = 41;
  cfg.pin_d3 = 42;
  cfg.pin_d4 = 15;
  cfg.pin_d5 = 16;
  cfg.pin_d6 = 48;
  cfg.pin_d7 = 47;
  cfg.pin_vsync = 46;
  cfg.pin_href = 38;
  cfg.pin_pclk = 45;
  cfg.xclk_freq_hz = 20000000;
  cfg.ledc_timer = LEDC_TIMER_0;
  cfg.ledc_channel = LEDC_CHANNEL_0;
  cfg.pixel_format = PIXFORMAT_RGB565;
  cfg.frame_size = FRAMESIZE_QVGA;
  cfg.jpeg_quality = 12;
  cfg.fb_count = 1;
  cfg.fb_location = CAMERA_FB_IN_PSRAM;
  cfg.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  cfg.sccb_i2c_port = M5.In_I2C.getPort();
  bool ok = esp_camera_init(&cfg) == ESP_OK;
  if (ok) {
    for (int i = 0; i < 4; i++) {
      camera_fb_t *frame = esp_camera_fb_get();
      if (!frame) {
        ok = false;
        break;
      }
      if (i == 3) {
        ok = frame->len == 320 * 240 * 2;
        if (ok)
          out.assign(frame->buf, frame->buf + frame->len);
      }
      esp_camera_fb_return(frame);
    }
    esp_camera_deinit();
  }
  M5.In_I2C.bitOff(0x58, 0x03, 1, 100000);
  return ok;
}

} // namespace shell
