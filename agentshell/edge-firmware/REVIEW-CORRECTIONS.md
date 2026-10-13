# Correcciones de la primera revisión

La primera revisión Grok fue FAIL; se conserva íntegra en review-grok.txt. Este pase revisa el candidato actual sin desplegar. No hereda un PASS.

1. SkinManager/apply/select, páginas y rebuild comparten el mutex BSP; callbacks encolan selección, UI_Task aplica. No lecturas de catálogo fuera del dominio LVGL.
2. Separados origen de swipe y último punto de caricia, limitada al rectángulo 136x136.
3. Menú y comando cancelar abren confirmación; solo Sí incrementa generación/corta.
4. Hallazgo NVS contrastado con fuente real IDF 6.0.1: nvs_flash_init_partition llama init_partition sin cifrado. El API nvs_flash_init() sí autoelige cifrado: NO se llama en este proyecto. Soporte NVS_ENCRYPTION necesario para vault; guardia eFuse+keys y secure_init_partition. Error de provisión ya no aborta modos locales. Se adjunta fuente exacta para revisión, no asumir equivalencia de APIs.
5. post_turn y Reply llevan generación original; task/UI/error requieren ID de tarea y turno vigente.
6. SNTP ya existía en transporte copiado; ahora se expone callback de sincronización y frescura2h. Aprobar se bloquea hasta sincronización; época guardada no basta.
7. Se libera models_ al fallar matching; m se destruye en cada salida. Solo modelo de una palabra exacta Sagwa.
8. Wake ACK respeta sound_enabled; si silenciado empieza captura sin sonido.
9. Guardias ACK >=640B/paridad y write_checked; no underflow.
10. Estado FFT persistente separado para mic/playback. Errores I2S y starvation3s detienen playback y reportan fallo.
11. Entrada separada: texto8KB/audio160044B (5s) antes de base64; JSON salida peticion224KB; respuesta64KB; result32KB. JSON liberado antes HTTP.
12. TaskStatus_t[64] BSS estático.
13. Centinela RMS>.22 reacciona visualmente sin red ni tools, cooldown5s; calibración pendiente.
14. Diagrama WakeNet desactivado; README pruebas endpoint sin credenciales, no CredentialStore hardware. Parser usa require_null_terminated=true e incluye test trailing PASS.
Extras: on_event plugins, working state, status emoji todas páginas, buffers de tokens borrados, privacidad palabras ASCII/latinas mayúsculas normalizadas; PWR durante autocaptura termina; unmount explícito de plugins. Telemetría sin IMU mantiene métricas reales y omite movimiento.

Pendientes declarados: hardware FPS/acústica/DMA/PSRAM/sensores, modelo Sagwa, arte Muse final, APIs reales, OAuth adapter, AFE/AEC, portar cámara/paquetes/OTA. Se entrega candidato compilado, no release comercial ni firmware instalado.

## Segunda revisión: cuatro correcciones adicionales

Se conserva el segundo FAIL en review-grok-current.txt. La cola PCM llena ya no cancela: Audio_Task deja comandos en la cola cuando pending alcanza 32; Network_Task conserva una trama/fin de audio y reintenta antes de consumir más paquetes. El gateway0.2 ya limita la emisión a tiempo real+300ms; la prueba de congestión física0.3 sigue pendiente.

send_request usa un ID candidato, publica task solo tras envío completo y envía task.cancel ordenado detrás de media.start si aborta. El gateway candidato libera el upload cancelado y omite inicio, tramas y final de IDs cancelados, incluso si el control adelanta su cadena asíncrona. Debe desplegarse ese cambio compatible antes del firmware0.3.

Todos los clips pasan guardias de longitud positiva/par y cursor; un clip inválido cede CPU20ms y señala fallo. Pomodoro conserva su inicio en Runtime, independiente de mount/unmount.

Extras: se borran las claves XTS de la pila; privacidad incluye password. Caricia y mirada siguen el rectángulo reducido del avatar en modo asistente. Desactivado el monitor LVGL permanente de rendimiento para conservar pantalla negra mínima. Ninguno de estos cambios se ha flasheado.

## Tercer pase

ACK exactamente640B termina por finish_clip y abre captura, sin tratar cursor==longitud como error. Cursor mayor/impar y clip inválido sí fallan y ceden20ms. Los fallos de playback cercan la generación de PCM: pending se limpia y PCM/end_stream pendientes se descartan al drenarse la cola, preservando controles de nuevas generaciones. Network descarta blocked_audio de la generación fallida antes de reintentar y manda stop solo de esa generación.

La sugerencia secundaria de marcar vault `encrypted` se contrastó con IDF6.0.1: lookup_nvs_encrypted_partition devuelve ESP_ERR_NVS_WRONG_ENCRYPTION si esp_partition->encrypted. Por tanto vault no lleva ese flag; usa NVS-XTS mediante secure_init_partition. Solo nvs_keys requiere encrypted. Se conserva fuente exacta en el siguiente pase; no se quema ninguna eFuse.
