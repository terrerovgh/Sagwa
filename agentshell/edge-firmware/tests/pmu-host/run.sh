#!/bin/sh
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cc -std=c11 -D_DEFAULT_SOURCE -Wall -Wextra -Werror -fsanitize=address,undefined -g -pthread \
 -I"$ROOT/tests/pmu-host/shims" -I"$ROOT/components/m5stack_core_s3/priv_include" \
 "$ROOT/components/m5stack_core_s3/src/bsp_feature_en.c" "$ROOT/tests/pmu-host/test.c" -o "$TMP/pmu-test"
"$TMP/pmu-test"
