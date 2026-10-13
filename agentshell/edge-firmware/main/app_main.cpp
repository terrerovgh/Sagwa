#include "edge.hpp"
#include "sdkconfig.h"
extern "C" void app_main() {
  sagwa::RuntimeConfig config; // Activate only after installing an
                               // authenticated model with exact word metadata.
#ifdef CONFIG_SAGWA_WAKE_ENABLED
  config.wake_enabled = true;
  config.wake_model_sha256 = CONFIG_SAGWA_MODEL_SHA256;
#endif
  sagwa::start(config);
}
