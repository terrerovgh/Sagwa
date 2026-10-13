# Sagwa Edge — guía de integración

**Actualización13oct2026:** [estado canónico](../../docs/STATUS.md). M/N2 tuvieron diagnóstico app-only y retorno0.2; N2 fue rechazado. Cadencia28ms actual experimental. Ninguna versiónEdge promovida ni24h aceptadas; las frases históricas de preparación siguientes no sustituyen este estado.

Proyecto ESP-IDF independiente `0.3.0-dev` para el M5Stack CoreS3. La arquitectura, sus contratos y límites están en [ARCHITECTURE.md](ARCHITECTURE.md). El código de 0.2.0 instalado continúa en `../firmware`. G/H/I/J/M/N2 tuvieron pruebas breves app-only con retorno a 0.2.0; ninguna versión Edge está promovida. N2 fue rechazado por regresión de rendimiento. K/L fueron preparaciones/revisiones host.

## Compilar y probar

Requisitos: ESP-IDF **6.0.1**, target **esp32s3**, Python del entorno IDF y compiladores del host para las pruebas. Component Manager descarga versiones fijadas en `main/idf_component.yml`/`dependencies.lock`: BSP CoreS3 4.1.0, LVGL 9.4.0 y ESP-SR 2.6.0. No se necesita Node.js para compilar: Inter y los emojis ya están preparados.

Desde la raíz de este repositorio:

```sh
source ./activar-muse.sh
idf.py -C agentshell/edge-firmware -B build/edge build
agentshell/edge-firmware/tests/run.sh
```

En un checkout independiente de este directorio, primero active el entorno ESP-IDF y ejecute `idf.py -B build set-target esp32s3`, seguido de `idf.py -B build build`. La primera compilación descarga las dependencias; las siguientes usan el lockfile. Los tests nativos necesitan que la dependencia cJSON esté descargada. Corren con AddressSanitizer y UndefinedBehaviorSanitizer.

`build/edge/sagwa_edge.bin` es una **imagen de desarrollo sin firma de release**. La compilación también crea `storage.bin` con las diez skins y el paquete de modelos que seleccione ESP-SR. No ejecute `idf.py flash` sobre el equipo que está en la prueba de 24 horas. El build no publica una oferta OTA ni inicia servicios remotos.

## Módulos

| Archivo | Función |
|---|---|
| `components/sagwa_edge/include/edge.hpp` | Contratos portables, FSM, skins, router y plugins |
| `components/sagwa_edge/core.cpp` | Matemática de animación, FFT, parser y decisión local |
| `components/sagwa_edge/graphics.cpp` | LVGL, rig por capas, gestos y pantallas |
| `components/sagwa_edge/skin_storage.cpp` | Recarga de archivos fuera del hilo de UI |
| `components/sagwa_edge/audio.cpp` | BSP I2S real, WakeNet, SFX y captura/playback prioritario |
| `components/sagwa_edge/runtime.cpp` | Tareas, colas, sensores, PWR, comandos y consola |
| `components/sagwa_edge/cloud.cpp` | Adapters HTTPS de proveedores comerciales |
| `components/sagwa_edge/credentials.cpp` | Vault NVS cifrado y contrato OAuth |
| `components/sagwa_edge/network.cpp` | Protocolo AgentShell, Muse, media y autorizaciones |
| `include/weather.hpp` / `include/weather_json.hpp` | Pronóstico autenticado, validación y vencimiento monotónico; [integración](WEATHER.md) |
| `components/sagwa_edge/camera.cpp` | Captura V4L2 GC0308 separada, preview y envío confirmado |
| `components/sagwa_edge/maintenance.cpp` | Verificación de arranque y actualización firmada fuera de UI |
| `components/sagwa_edge/telemetry.cpp` | Métricas de SPI terminado, memoria, sensores y audio |
| `components/agentshell_ota` | Validador de firma/hash/tamaño y escritura al slot inactivo |
| `components/m5stack_core_s3` | BSP 4.1.0 local con correcciones acotadas documentadas |
| `components/agentshell_network` | Transporte Wi-Fi/WSS/mTLS reutilizado, cámara declarada |
| `components/agentshell_protocol` | Envelope, UUID y frames binarios compatibles |
| `components/agentshell_storage` | Provisionado/contador NVS existentes; no inicializa otro driver de display |

No se inicializa M5Unified junto con el BSP: evitaría tener dos propietarios de SPI, I2C, audio y touch. El BSP administra los buses y los códecs adecuados.

## Memoria y particiones

Tabla de desarrollo para 16 MB; las dos apps OTA conservan sus offsets y tamaños de 0.2.0:

| Partición | Offset | Tamaño | Uso |
|---|---:|---:|---|
| `nvs` | `0x11000` | 48 KB | Wi-Fi/provisión mTLS y contador existentes |
| `otadata` | `0x1D000` | 8 KB | Selección OTA |
| `phy_init` | `0x1F000` | 4 KB | Datos PHY |
| `ota_0` | `0x20000` | 4 MB | App A |
| `ota_1` | `0x420000` | 4 MB | App B |
| `model` | `0x820000` | 4 MB | Modelos ESP-SR |
| `storage` | `0xC20000` | `0x3D7000` | SPIFFS de skins y recursos |
| `nvs_keys` | `0xFF7000` | 4 KB | Claves XTS de vault; flag encrypted |
| `vault` | `0xFF8000` | 32 KB | Claves comerciales y tokens cifrados |

**La zona de datos cambia.** No basta ofrecer el binario por OTA al firmware anterior: primero hace falta una migración con copia de la flash/datos, compatibilidad con bootloader y tabla verificada. SPIFFS no se formatea automáticamente al fallar el montaje. microSD es opcional (`CONFIG_SAGWA_SD_ENABLED`), montada por el BSP; funciona sin tarjeta usando skins compiladas/SPIFFS.

Dos buffers RGB565 ocupan 300 KiB de PSRAM; captura máxima 320 KB PCM + 44 bytes WAV; playback pendiente limitado a 32 bloques de 4 KB más la cola de entrada; descriptor máximo 8 KB; respuesta HTTP máxima 64 KB, petición máxima 224 KB (audio standalone ≤5 s; texto ≤8 KB). El uso real se mide con métricas y watermarks; un modelo WakeNet personalizado puede cambiar el margen. No se ha medido el pico de RAM de esa combinación en hardware.

## Instalar skins y plugins

Copie `skin_template.json` como `<id>.json` a `/sdcard/sagwa` o al image SPIFFS montado como `/skins`. En SPIFFS, `skins` es el contenido raíz de la partición, no un subdirectorio real. El `id` debe coincidir con el nombre; `schema: 1`, `revision` positiva y una `base` existente para nuevas skins. Recarga automática cada dos segundos, con último descriptor válido conservado.

No se aceptan DLL, scripts, bytecode ni URLs dentro de descriptores. Para un nuevo tipo de widget:

1. Implemente `SagwaPluginInterface`; todos sus métodos que dibujan se ejecutan en UI_Task bajo el mutex LVGL.
2. Agregue el `.cpp` a CMake y llame `register_plugin("clock", factory)` **antes de `start()`**. El ejemplo `examples/plugin_clock.cpp` ofrece `register_clock()`.
3. Declare `type: "clock"` en el descriptor. `page: "home"` es principal; `page: "reloj"` crea una secundaria accesible por el borde derecho.
4. Use `unmount` para eliminar objetos/recursos; no bloquee en `update`. Para datos remotos, otra tarea obtiene los datos y publica una copia.

En la consola de desarrollo: `skin night`, `skin pet` y `ask estado`. Las skins personalizadas se seleccionan desde el catálogo táctil. Un plugin nativo puede enviar un `Request` por `submit`, marcando `private_context`, `tools`, `capability` y `target`; esto debe proceder de una acción explícita del usuario. Los sensores nunca llaman `submit`.

## Provisión de red y proveedores

Se reutiliza la provisión AgentShell de 0.2.0 en el namespace `agentshell`: SSID, contraseña Wi-Fi, CA privada, certificado/llave del Core y dos URLs `wss://…/v1/device/ws`. No hay direcciones ni credenciales reales en el firmware. En un Core sin esa provisión, complete primero el flujo existente de USB/provisionado. Sin provisión ni Wi-Fi, los modos/gestos/SFX siguen funcionando.

El gateway comunica disponibilidad real de agentes y sigue usando Muse como principal. La preferencia de enrutamiento se cambia desde el borde derecho. `local_only` bloquea todas las consultas que necesiten red. Un perfil cloud solo es candidato si está habilitado, tiene claves/modelos válidos y hay Wi-Fi; HTTPS determina el resultado real. Ante errores aplica cooldown de 30 segundos y prueba otro perfil habilitado. Consultas privadas y herramientas nunca pasan a cloud por este mecanismo.

Las claves comerciales requieren **vault cifrado y Flash Encryption provisionados previamente**. El proyecto rechaza guardarlas si no existen esas condiciones. Las flags de seguridad no se activan por flashear este proyecto; no hay llamadas de quemado eFuse ni borrado automático. Para fabricación se necesita un procedimiento separado con Secure Boot, claves por dispositivo, recuperación controlada y firmware firmado. No active Flash Encryption ni Secure Boot en el prototipo sin preparar la recuperación y autorizar ese cambio irreversible.

En un dispositivo ya provisionado de forma segura, importe un perfil mediante la consola física. La línea es `profile ` seguida de JSON. Mantenga el archivo de entrada privado y evite copiar la clave al historial del shell. Este ejemplo contiene solo marcadores:

```json
{"provider":"openrouter","enabled":true,"key":"CLAVE_DEL_DISPOSITIVO","small":"ID_PEQUENO_VERIFICADO","strong":"ID_POTENTE_VERIFICADO","audio_input":false,"responses_api":false}
```

Otros valores de `provider`: `openai`, `xai`, `gemini`, `opencode`. En OpenCode se configura una **clave Zen**, y `responses_api: true` selecciona `/zen/v1/responses` para modelos compatibles; `false` usa chat completions. Gemini requiere un ID compatible con generateContent, sin el prefijo `models/`. Para OpenRouter con audio, verifique la modalidad WAV del modelo antes de activar `audio_input`. Los adaptadores directos restantes son de texto. Se imprime únicamente `profile.installed` o `profile.rejected`.

Use claves dedicadas y límites de gasto del proveedor. No se reutiliza la clave del servicio TTS ni se modifica su ledger compartido de US$5. No hay llamadas comerciales ejecutadas ni modelos de pago activados en esta entrega. OAuth necesita un adapter específico al contrato oficial del proveedor; la interfaz abstracta y el almacenamiento cifrado están listos, pero no hay refresh ni login de suscripciones implementado.

## Modelo de activación «Sagwa»

No se incluye un detector Sagwa entrenado. Para habilitarlo:

1. Obtenga/entrene el modelo personalizado siguiendo el procedimiento de Espressif, con dataset, licencia y evaluación documentados.
2. Configure `CONFIG_ESP_SR_EXTERNAL_MODEL_PATH` según el paquete recibido. Verifique que el tool de ESP-SR empaque ese modelo; no use una palabra distinta renombrada.
3. Mantenga `CONFIG_SAGWA_WAKE_ENABLED=n` hasta preparar el artefacto. Active la opción solo con metadata exacta `Sagwa`, mono a 16 kHz.
4. Configure `CONFIG_SAGWA_MODEL_SHA256` con la huella de **los 4 MB completos de la partición**, incluyendo el relleno final con `0xFF`, no solo el archivo sin padding. WakeDetector compara esa huella antes de crear el modelo.
5. En un equipo de prueba, mida falsos positivos, distancia, ruido, acento, latencia y consumo. Si falta el modelo/huella/metadata, WakeNet queda desactivado y PWR continúa operativo.

La latencia medida por `wake_audio_us` empieza **después** de que WakeNet devuelve detección y termina después de escribir el primer bloque I2S. No incluye captura previa, ventana del modelo ni propagación acústica. Para el objetivo <100 ms hace falta medición con micrófono/analizador, sin confundirlo con la latencia de inferencia.

## Validación antes de promover

Pruebas ejecutadas: compilación completa ESP-IDF y suite C++ con ASan/UBSan para los diez descriptores, tamaños/paths/recarga inválida, privacidad/enrutamiento con endpoints sin credenciales, sensores antiguos, FSM y FFT. Consulte `validation.json` y `build.log`.

La galería nativa usa el `graphics.cpp` de producción y LVGL 9.4: `tests/ui-host`. Renderiza 31 pantallas RGB565 y prueba 21 gestos con el input real de LVGL bajo ASan/UBSan. Activa `LV_USE_FONT_COMPRESSED` para Inter, igual que el firmware. La prueba exige píxeles blancos de texto para detectar una fuente omitida. Los datos, tiempo, cámara y BSP son fixtures; no demuestra DMA, FPS, audio ni latencias de hardware. La galería está en `../evidence/sagwa-v2/edge-ui-gallery-k/index.html` con sus hashes y límites.

Para reproducirla, active el entorno de compilación, ejecute `cmake -S tests/ui-host -B <build-host> -G Ninja`, `cmake --build <build-host>`, y `<build-host>/sagwa-ui-gallery <ruta-absoluta-a-evidence/sagwa-v2/edge-ui-gallery>`. `tests/ui-host/package_gallery.py` convierte PPM a PNG y prepara el visor, usando Pillow. El texto de autorización completo conserva desplazamiento; el gesto de volver restaura la pantalla anterior.

El transporte recupera una tarea propia mediante `device.resume` y `device.snapshot`. Un arranque puede mostrar la tarea reciente; una reconexión conserva el turno ya seleccionado. Las respuestas completas se vuelven a leer sin reproducir audio antiguo. Las autorizaciones recuperadas exigen UUID, hash, estado activo y fecha vigente; requieren hora SNTP y confirmación manual. Se descartan decisiones consumidas, denegadas o ya confirmadas. El gateway verifica propietario y rechaza seleccionar una tarea delegada como conversación principal.

Pendiente en hardware para **este proyecto**: flush/FPS, PSRAM bajo carga, DMA, español/legibilidad, touch/PWR, audio stereo→mono, SFX/interrupción, BMI270/LTR553, modelo Sagwa, comparación visual con el arte original, fallos de proveedor y reconexión. Los adapters cloud y CredentialStore no están probados con peticiones/dispositivo reales. La cámara y el actualizador firmado están portados y compilan, pero aún no han sido ejercidos en el Core. La distribución dinámica del rig nuevo sigue pendiente. Consulte `PRODUCT-ACCEPTANCE.md` para la aceptación completa, incluyendo UI y rutas todavía incompletas.

Para una futura release: completar la aceptación, reproducir el build, migrar datos sin alterar los slots OTA, hacer revisión de otra familia según `_coord`, presentar apariencia/voz finales, probar rollback y después validar 24 horas en el equipo. No publique este binario de desarrollo como release aprobada.

La sincronización SNTP habilita autorizaciones solo tras recibir hora actual; la época persistida de provisión no es suficiente. Si no se sincroniza, no se habilita aprobar. Ajuste el servidor de tiempo en el transporte para una red restringida. El centinela reacciona visualmente a RMS del micrófono, sin llamadas de red; el umbral `.22` necesita calibración en hardware para ruido/distancia reales.

## Compatibilidad y dictamen del candidato

Antes de probar este candidato, el gateway debe usar las fuentes completas revisadas de `agentshell/src`, verificadas con los hashes del recibo de esa misma revisión. Incluyen cancelación, recuperación y control de audio. `gateway-compat.patch` es un archivo histórico incompleto y no es una instrucción de instalación. Los cambios actuales todavía no están aplicados al servicio instalado.

La revisión estática anterior de otra familia dio PASS para las correcciones de ACK, generaciones de audio y vault NVS (`review-grok-final-a.txt`). Los cambios posteriores de rig, cámara, OTA y métricas requieren una revisión nueva. Ese dictamen no aprueba flashear ni sustituye las comprobaciones físicas pendientes. Los dictámenes anteriores FAIL se conservan junto con sus correcciones.

## Medición de fluidez

`device.telemetry` se emite cada cinco segundos. `ui.completed_frames` y `completed_transfers` avanzan desde el callback real `on_color_trans_done` de SPI; `completed_fps` calcula frames cuya última transferencia terminó en la ventana anterior. Una pantalla inmóvil puede producir cero frames: la medición de 30+ FPS debe hacerse con animación activa. `last_transfer_us` mide transferencia, `max_frame_gap_us` conserva el mayor intervalo desde la lectura previa y `last_update_us` solo mide trabajo de UI. Las latencias de reacción parten del evento táctil entregado o del sample de IMU y terminan en la última transferencia del frame; no incluyen scanout/acústica. No se interpreta `LV_EVENT_FLUSH_FINISH` como fin de DMA.

El callback conserva `lv_display_flush_ready`, no asigna memoria ni serializa JSON en ISR. El BSP sigue siendo dueño de SPI/IO; su getter solo presta el handle. El candidato N actualiza la UI cada 28 ms y LVGL revisa invalidaciones cada 16 ms. M, con cadencia de 32 ms, midió 26,392–31,280 FPS físicos, con mediana de 31,189: todavía no cumple 30+ FPS estables. N deja más margen de cadencia, pero requiere medir CPU, memoria, voz y frames SPI en hardware antes de promoverlo. Se desactiva el overlay de rendimiento para conservar la pantalla limpia.

## Enfoque

El menú ofrece Enfoque. En su modo principal, tocar el temporizador abre los controles de inicio, pausa, continuación, descanso y reinicio. El contador no empieza al dibujarse. Se guarda en NVS fuera de UI; al reiniciar vuelve en pausa. Con un corte brusco puede perderse hasta el último minuto más el tiempo de la cola de escritura. No requiere red ni microSD. La validación de persistencia física sigue pendiente.

Las órdenes habladas vuelven al enrutador del Core solo si el gateway confirma transcript_routing=client. Con gateways anteriores el flujo Muse original se mantiene. Comandos locales, privacidad y herramientas se evalúan sobre el texto sin cambiar el destino/capacidad elegidos al capturar. STT se hace en los hosts; el modelo WakeNet auténtico aún falta.

Para el preflight de solo aplicación, el auditor requiere --candidate-sha256 obtenido del recibo de la revisión exacta, además de dos backups privados y baseline0.2. Es una comprobación de bytes, no una firma ni una aprobación de despliegue. gateway-compat.patch conserva únicamente un parche inicial histórico; el siguiente despliegue debe usar las fuentes completas revisadas y sus hashes, nunca asumir que ese parche representa todos los cambios actuales.

El candidato K añade historial local en modo Terminal: 64 eventos tipados en RAM, ordenados del más reciente al más antiguo; las horas indican tiempo desde arranque. Tocar el panel abre lectura desplazable y el borde izquierdo vuelve. Si hay una respuesta real, tocarla conserva la lectura completa. El historial no acepta prompts, transcripciones, URLs ni mensajes de error libres; desaparece al reiniciar. Sus pruebas de wrap del reloj, memoria acotada, privacidad y navegación son nativas, no una medición física. La nueva galería K conserva las anteriores. No se ha instalado K en el dispositivo.
