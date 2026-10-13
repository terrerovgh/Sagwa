#!/bin/sh
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
CJSON="$ROOT/managed_components/espressif__cjson/cJSON"
cc -Wno-deprecated-declarations -fsanitize=address,undefined -g -c "$CJSON/cJSON.c" -o "$OUT/json.o"
c++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined -g -I"$CJSON" -I"$ROOT/components/sagwa_edge/include" "$ROOT/components/sagwa_edge/core.cpp" "$ROOT/tests/core_test.cpp" "$OUT/json.o" -o "$OUT/core-test"
"$OUT/core-test" "$OUT" "$ROOT/skins"
c++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined -g \
  -I"$ROOT/components/sagwa_edge/include" "$ROOT/tests/focus_timer_test.cpp" -o "$OUT/focus-test"
"$OUT/focus-test"
c++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined -g \
  -I"$ROOT/components/sagwa_edge/include" "$ROOT/tests/diagnostics_test.cpp" -o "$OUT/diagnostics-test"
"$OUT/diagnostics-test"
c++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined -g \
  -I"$CJSON" -I"$ROOT/components/sagwa_edge/include" "$ROOT/tests/weather_test.cpp" "$OUT/json.o" -o "$OUT/weather-test"
"$OUT/weather-test"
c++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined -g \
  -I"$ROOT/components/sagwa_edge/include" "$ROOT/tests/frame_metrics_test.cpp" -o "$OUT/frame-metrics-test"
"$OUT/frame-metrics-test"
c++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined -g \
  -I"$CJSON" -I"$ROOT/components/sagwa_edge/include" "$ROOT/components/sagwa_edge/core.cpp" \
  "$ROOT/tests/rig_renderer_test.cpp" "$OUT/json.o" -o "$OUT/rig-renderer-test"
"$OUT/rig-renderer-test"
