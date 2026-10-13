# Aceptación del producto Sagwa

El objetivo conserva la petición completa: producto utilizable en CoreS3, interfaz negra, mascota fiel a Sagwa, voz natural, navegación completa y arquitectura Edge del texto original `USER-REQUEST.md`. Compilar un candidato no completa el objetivo. El firmware instalado sigue siendo 0.2.0; las pruebas de esa versión no verifican 0.3.0-dev.

Estado a 2026-10-13: integración en curso. `validation.json` describe evidencias del candidato; cada despliegue deberá identificar hashes de firmware, datos, paquetes y servicios. **No hay aprobación física ni release comercial de Edge todavía.**

| Requisito | Evidencia necesaria | Estado / fuente actual |
|---|---|---|
| Negro puro, texto blanco Inter español, avatar transparente 136 px, emoji derecho 28 px | Capturas de todas las pantallas reales, prueba de acentos y píxeles fuera de arte | Implementado en `graphics.cpp`; nuevo rig con vista QA `assets/sagwa-rig/assembled-black-preview.png`; hardware pendiente |
| Respiración, parpadeo aleatorio, orejas, pupilas touch/IMU, easing | FSM y secuencia visual real con sensores/eventos | FSM y capas transparentes implementadas, pruebas nativas pasan; visual real pendiente |
| Identidad y originales Sagwa intactos | SHA/procedencia de referencia y comparación de arte/animación | `assets/sagwa-rig/provenance.json`, atlas y 12 piezas nuevos derivados; originales privados conservados; aprobación visual pendiente |
| Doce estados de mascota sin sustituir escucha/autorización/error | Cobertura de FSM, clips/rig, prioridad de estados y prueba física | FSM 13 estados con prioridad probada; doce clips existen en 0.2; rig nuevo pendiente en hardware |
| 30+ FPS estable, doble buffer PSRAM, SPI DMA, UI sin audio/red/FS bloqueantes | FPS de frames terminados, intervalos/p95, watermarks bajo carga y prueba de tearing | Dos buffers de 320×240 configurados; `telemetry.cpp` y callback SPI real. M midió 26,392–31,280 FPS (mediana 31,189), gap máximo 129,734 ms: objetivo estable incumplido. N cambia solo cadencia UI de 32 a 28 ms; sin prueba física ni aprobación de despliegue. LVGL refresh sigue en 16 ms |
| Gestos de tres bordes, texto scroll/lectura, caricias; PWR habla/interrumpe | Recorrido completo y latencias en Core | Gestos implementados; medición touch/IMU→última transferencia preparada; prueba física pendiente |
| Menú, herramientas, agentes, destinos, tareas, lectura, cámara, sensores, voz, mascota, autorización, cancelación y errores | Galería y recorrido de todas las pantallas, disponibilidad real y navegación de vuelta | Galería del renderer LVGL: 31 vistas y 21 gestos simulados con ASan/UBSan; vuelta al padre corregida. Datos sintéticos; recorrido físico pendiente |
| Skin mascota: reposo y ronroneo | Prueba sin red con SFX y caricias | FSM/SFX local preparados; medición nueva pendiente |
| Skin foco: Pomodoro | Persistencia entre cambios de pantalla, inicio/fin/cancelación | Inicio/pausa/continuar/rest5min/reset, fin único y persistencia NVS con restauración en pausa implementados; reloj portable y flujo LVGL pasan; reinicio físico pendiente |
| Skin diagnóstico: CPU/RAM/Wi-Fi/batería real, estética del personaje | Telemetría real, faltantes visibles, control de fluidez | Widget y telemetría preparados; medición en Core pendiente |
| Skin noche: brillo bajo, ojos cerrados, respiración lenta, silencio | Brillo físico y preferencia persistida; mecanismo correcto de placa | Implementado usando BSP; confirmar método PWM/PMU y ahorro real |
| Skin centinela: sacudidas y ruido, orejas alertas | Umbrales/calibración local, privacidad de MIC visible | RMS local y sensores preparados; calibración y pruebas pendientes |
| Skin terminal: retro monocromo y logs útiles | Pantalla real y salida de diagnóstico sin secretos | Recoloración e historial local de 64 eventos tipados, tiempos desde arranque, dos entradas en principal y lectura desplazable implementados; límites/privacidad/navegación pasan en host. No expone texto libre ni persiste conversaciones. Hardware pendiente |
| Skin multimedia: FFT→orejas/cola | FFT probado y animación con audio reproducido | FFT nativo pasa; respuesta física pendiente |
| Skin trabajo: avatar esquina/canvas texto | Captura y toque ajustado al tamaño | Implementado; verificación visual pendiente |
| Skin clima: datos locales/remotos válidos y expresión/paleta | Fuente configurada, frescura, clima desconocido y datos reales | L integra NWS opcional, fechas/TTL/URL/unidades validadas, tinte y orejas en reposo; consulta pública real válida y galería vigente/vencido. Configuración de ciudad, revisión, despliegue y hardware pendientes; [WEATHER.md](WEATHER.md) |
| Skin error: recuperación clara ante red/proveedor | Fallos inducidos y vuelta al estado normal | Estados de error presentes; recorrido/failover físico pendiente |
| SkinManager y plugins JSON/factories C++, hot-reload SD/SPIFFS | Plantillas, ejemplo compilado y recarga real inválida/válida sin bloquear | Parser/límites/recarga nativa pasan; ejemplo/flujo real de instalación y preferencias pendientes |
| Wake «Sagwa» auténtico offline ESP-SR/WakeNet | Modelo, licencia, hash, precisión/ruido/distancia y latencia medidos | No hay modelo genuino; detector preparado, desactivado; consulta enviada con autorización y Grok PASS; receipt `reference/wakenet-inquiry-sent.json` |
| ACK maullido antes de sockets y <100 ms | Detección→PCM y medición acústica, sin red | Orden implementado; `wake_to_first_write_us` preparado; depende del modelo y medición física |
| Ronroneo al acariciar / quejido al sacudir, licencia, volumen suave | Atribución comprobada, offline, interrupción y cooldown ≥5 s | PCM incrustado/licenciado; no exige SD; pruebas físicas nuevas pendientes |
| Reacciones proximidad/tilt/oscuridad, suavizado/histéresis, sensores antiguos ausentes | Prueba local y matriz de sensores faltantes/antiguos | Implementación y pruebas nativas parciales; prueba física pendiente |
| Motor local determinista y control seguro de hardware | Comandos sin red, ningún comando remoto por sensores | Router local y transcripción negociada devuelta al Core preparados; contexto/privacidad y handshake legacy/nuevo pasan; voz real/hardware pendientes |
| Cloud OpenRouter independiente de ordenadores, modelo pequeño/potente | Equipo con Wi-Fi y rigs apagados, respuesta real y fallos/budget | Adapter y decisión preparados; credenciales seguras y llamadas reales pendientes |
| Homelab Muse principal, herramientas y destinos con disponibilidad real | Solicitudes reales y caídas/reconexión/cambio de host | Protocolo WSS/mTLS preparado; conservar políticas 0.2; integración nueva pendiente |
| APIs OpenAI/xAI/Gemini/OpenCode, contrato OAuth futuro cifrado | Adapters compatibles, credenciales protegidas y pruebas de proveedor | Código modular preparado; APIs no ejercidas; OAuth específico futuro no implementado (alcance: contrato preparado) |
| Qwen auxiliar integrado sin hacerse pasar por Muse ni ejecutar herramientas | Ruta local real autorizada y pruebas de privacidad/complejidad | Docker Model Runner funciona; helper auxiliar probado; aún sin enrutamiento automático Core |
| Voz Chatterbox LATAM TUF, Kokoro ef_dora Docker Mac/native, Bella API ≤US$5/mes | Audio real Core, failover, interrupción, reserva de coste y mediciones separadas | Servicios instalados/probados con 0.2; `../evidence/sagwa-v2/mac-docker.json`; Edge requiere prueba completa |
| PCM 16 kHz mono streaming, audio cancelado descartado | Backpressure, generaciones y corte durante reproducción | Implementado; parche gateway preparado y testeado, despliegue compatibilidad pendiente |
| Respuestas 5–10 palabras, cifras preservadas, lectura completa y autorizaciones íntegras | Casos reales Muse y proveedores, UX/UI completa | Muse 0.2 configurado; contratos brief/detail preparados; pruebas Edge pendientes |
| Cámara solo por usuario, preview local, confirmación explícita de envío | Foto real, descartar/offline/reintento, ausencia de envío automático | Worker V4L2 y confirmación implementados; hardware pendiente |
| Paquetes completos en ambos hosts, oferta ui.avatar y caché PSRAM, básicos offline | Descarga autenticada/hash/versionado, red caída y distribución verificada | 0.2 tiene paquetes; rig Edge integrado en firmware, distribución dinámica nueva pendiente |
| Configuración de voz/mascota y preferencias persistentes | UI completa, settings autenticados y reinicio sin perder preferencias | Controles y persistencia NVS fuera de UI implementados, settings autenticados integrados; restauración/reconexión en Core pendiente |
| Datos/particiones, no microSD exigida, slots OTA intactos | Copia de flash, migración reversible, tabla verificada, rollback ensayado | Slots 4 MB/offsets conservados en candidato; datos cambian y migración sigue pendiente; sin quemado eFuse |
| OTA firmado, revisión infraestructura, preview voz/UI antes de despliegue | Hashes congelados/revisión otra familia, firma, rollback real y aceptación física | Actualizador portado/endurecido; revisión anterior no cubre estos cambios; J firmado y descargado por mTLS en Mac; descarga TUF falló por guest caído. Pruebas físicas G/H/I restauraron baseline0.2; J probado sin panic y con rollback físico confirmado a 0.2; K/L/M no flasheados ni promovidos |
| Estabilidad 24 h y todas las latencias hardware | Ventana completa sin reinicios/stale/errores/tendencias, prueba de carga independiente | Soak 0.2+Docker interrumpido y preservado; supervisor retirado y automatización pausada durante pruebas físicas. Ninguna ventana24h aceptada; no valida Edge |
| Arquitectura FreeRTOS, código completo, plantillas, guía de memoria/credenciales/build | Documentos coherentes con código final y compilación reproducible | Artefactos presentes; actualización e integración en curso |

## Prueba física J y candidato M

El 13 de octubre, J arrancó sin panic durante 95 segundos, marcó su app como válida y retornó mediante el procedimiento revisado al slot baseline 0.2.0. Lecturas confirmaron app/metadata y conservación de provisioning/tabla/boot; la telemetría posterior volvió a 0.2. No demuestra prueba de voz, cámara o gestos físicos ni estabilidad 24 horas.

Nueve muestras frescas de 40 segundos midieron **13.847–15.701 FPS de SPI completado**, por debajo de 30. CPU 49.9–73.2 %, mínimo interno observado 40935 bytes; eventos IMU→última transferencia reportaron 46–64 ms (primera muestra sin evento: 0). Se conservan `edge-physical-j-observation.json`, `physical-trial-j-execution.log` y `physical-trial-j-post-rollback.json`.

M evita llamar los setters LVGL del emoji y texto MIC cuando el valor ya coincide. LVGL 9.4 invalida la imagen al principio de `lv_image_set_src`, incluso con el mismo puntero. El avatar mantiene sus invalidaciones propias y se conserva la prioridad de estados. Es una optimización preparada: su mejora de FPS aún no ha sido medida en hardware.

## Orden de cierre

Completar funcionalidades/UI y rutas reales; resolver el modelo wake genuino y configuración segura; preparar migración y pruebas reversibles; congelar fuentes y ejecutar revisión independiente; mostrar galería/voz; desplegar release firmada con respaldo; verificar hardware y latencias; iniciar la ventana de estabilidad de la versión final. No se mueve el objetivo a «candidato compilado» para cerrar pendientes.
