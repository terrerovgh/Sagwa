# ADR: primera validación física Edge mediante OTA de aplicación

Estado: preparado; requiere revisión independiente y evidencia antes de aplicar. No sustituye la aceptación completa del producto ni autoriza eFuses, pagos o una migración de datos.

El Core ejecuta Sagwa 0.2.0 con slots OTA de 4 MiB en 0x20000 y 0x420000. El candidato Edge conserva esos offsets y tamaños. La primera prueba de pantalla, sensores, PWR, cámara y audio puede ensayarse con la tabla instalada, sin flashear el bootloader, tabla, NVS, datos ni modelos. ESP-IDF busca las particiones en la tabla real del dispositivo; los offsets del CSV de desarrollo no se usan como una orden de escritura de OTA.

`Runtime::start` inicializa NVS provisionado sin borrarlo y monta `storage` mediante SPIFFS con `format_if_mount_failed=false`. La geometría SPIFFS debe compararse contra ambos sdkconfig antes de aplicar. Los diez modos y el rig básico están compilados. La ausencia del modelo y del vault mantiene WakeNet y APIs directas desactivados; no se crea ni se quema ninguna clave. El namespace nuevo `sagwa_ui` permite preferencias sin sustituir provisión. Debe comprobarse el espacio libre antes de escribir preferencias.

Procedimiento preparado:

1. Congelar fuentes, build y firma; revisar código y este ADR con otra familia. Completar cualquier bloqueante del dictamen.
2. Registrar y detener únicamente la prueba de estabilidad propia antes de la intervención prevista, preservando JSON/NDJSON/stderr. La ventana 0.2 no se mezcla con la versión nueva.
3. Antes de conectar USB, registrar la telemetría vigente, partición activa/estado OTA y hash de 0.2. Al abrir USB se espera reset y se documenta como intervención. Guardar copia completa de los 16 MiB en ruta privada 0700/archivo0600: contiene provisión y credenciales. Verificar tamaño y dos lecturas coincidentes; solo publicar hash. No imprimir ni adjuntar ese contenido.
4. Examinar offline la tabla real y metadatos OTA. Rechazar cualquier diferencia de offsets/tamaños, bootloader sin rollback, flash cifrada no recuperable con este procedimiento o hash inesperado. Conservar los dos slots previos en la copia privada.
5. Publicar exclusivamente el binario de aplicación firmado mediante el mecanismo autenticado actual. Ofrecer OTA al slot inactivo. No usar `idf.py flash` ni `flash_args`: incluyen tabla/model/storage y no forman parte de esta prueba.
6. Observar arranque, boot_validated, memoria, frame completado por DMA, captura local y transporte. La marca válida espera 30 segundos de salud básica; además exigir métricas de hardware y revisión visual antes de promover.
7. Probar vuelta real al binario 0.2.0 firmado mediante OTA, confirmar versión/hash, y volver al candidato solo si la reversión es reproducible. Si no arranca o no hay red, restaurar el slot y metadatos correctos desde el respaldo privado, preservando tabla/NVS/datos; confirmar dos hashes antes de escribir.
8. Medir 30+ FPS con animación, latencias táctiles/sensores/audio, micrófono, altavoz, cámara y PWR; recorrer pantallas. Documentar fallos y corregir; no presentar el trial como producto terminado.

La instalación futura del modelo WakeNet y vault requiere otro plan de migración reversible de datos y provisión segura, con autorización específica para cualquier eFuse irreversible. No se puede aprobar este ADR solo con build, harness LVGL o una prueba de telemetría 0.2.

## Auditoría preparada

`tools/audit_app_trial.py` es de solo lectura: nunca abre USB ni llama a esptool, OTA o eFuses. Usa el parser oficial de particiones ESP-IDF para comprobar MD5/layout, dos archivos completos distintos de16MiB con bytes idénticos, permisos0600/directorio0700, bootloader de referencia, metadatos OTA confirmados/CRC y hash del app0.2 activo. El candidato debe caber en4MiB y tener descriptor ESP-IDF0.3.0-dev. Su resultado marca siempre `deployment_approved=false`: no prueba que los archivos vengan del hardware, la firma de publicación ni una reversión real.

Se ejecutaron seis pruebas con una imagen completa sintética construida a partir de imágenes públicas compiladas y datos vacíos, sin provisión real: copia desigual/incompleta, baseline alterado, slot modificado, OTA pendiente/inválido/CRC, tamaño/descriptor/version del candidato, permisos y symlink. `app-trial-tests.log` conserva el resultado. Esto no cuenta como respaldo físico ni como rollback probado.

El binario0.2 exacto está en `build/agentshell.bin` (SHA88e9c70d…); otros builds antiguos tienen hashes distintos y no se aceptan como baseline. La geometría SPIFFS de `build/config/sdkconfig.h`/sdkconfig debe confirmarse junto con el bootloader real. `reference/app-only-preflight.json` compara únicamente los sdkconfig de fuentes; su `flash_read_not_run=true` permanece hasta la lectura física.
