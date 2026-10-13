#!/usr/bin/env bash
# Ejecutar con: source ./activar-muse.sh
export PATH="${SAGWA_TOOLS_BIN:-$HOME/esp/muse-tools/bin}:$PATH"
export SAGWA_IDF_EXPORT="${SAGWA_IDF_EXPORT:-$HOME/esp/esp-idf-v6.0.1/export.sh}"
if [ ! -f "$SAGWA_IDF_EXPORT" ]; then
    printf '%s\n' 'Configure SAGWA_IDF_EXPORT con el export.sh de ESP-IDF 6.0.1.' >&2
    return 1 2>/dev/null || exit 1
fi
. "$SAGWA_IDF_EXPORT"
