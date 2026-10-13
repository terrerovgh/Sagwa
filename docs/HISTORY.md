# Bitácora consolidada de trabajo anterior

Reconstrucción de hechos y recibos conservados al13 oct 2026. Esta síntesis no es un log de comandos completo ni una transcripción de conversaciones privadas. Los ensayos fallidos permanecen registrados; un recibo de preparación no se convierte retrospectivamente en evidencia de despliegue.

## Producto inicial y Sagwa 0.2

Se construyó AgentShell: gateways autenticados, tareas, broker de agentes, política de autorizaciones, transporte WSS/mTLS, objetos durables, reconexión, protocolo de media y OTA con firma/rollback. Se incorporó Muse principal y herramientas autorizadas de hosts; adapters comerciales permanecen desactivados cuando no existe configuración/autorización real.

Sagwa 0.2 llevó al Core interfaz negra, Inter con español, avatar transparente, emoji fijo de estado, gestos de borde y lectura; PWR para voz, caricias separadas del micrófono, confirmación de fotos/cancelaciones/aprobaciones. Se preservaron originales Muse y backups de flash privados. Las herramientas de despliegue y pruebas son código, no permiso automático para ejecutar cambios.

Voz: streaming16kPCM, cancelación y fallback; Chatterbox TUF GPU coordinada, Kokoro/Whisper Mac nativos y después Docker Desktop ARM64. Contenedor propio limitado2 CPU/3 GiB/128 procesos, solo localhost 9493 detrás del router 9450, sin claves de pago ni Docker socket. Promoción y rollback reales ensayados. Qwen3 4B de Model Runner quedó como auxiliar sin herramientas; el0.6B fue descartado por falta de salida útil. No se incorporó automáticamente al router de tareas.

Las dos ventanas de estabilidad no acreditan24 h válidas: la anterior se preservó tras reset accidental Core y caída de telemetría TUF. La monitorización propia quedó pausada/retirada antes de ensayos físicos. No confundir telemetría periódica con estrés continuo de voz/cámara.

## Reestructuración Edge 0.3

Se creó firmware ESP-IDF independiente con LVGL9.4, BSP4.1, ESP-SR2.6, tareas/colas FreeRTOS, rig felino procedural, skins, factories JSON, routing, cámara, vault y mantenimiento. Se corrigió la suposición de hardware: CoreS3 usa **ES7210/AW88298**, no ES8388. Un solo BSP gestiona los buses.

Revisiones por etapas corrigieron límites, concurrencia, autorizaciones, privacidad, audio, temporización, sensores, recuperación y pruebas. Los tests host cubren lógica/C++ con sanitizers y UI de33 pantallas/21 gestos; la revisión externa Grok se vinculó a paquetes/hashes concretos, sin certificar aceptación comercial.

| Etapa | Cambio/observación | Resultado |
|---|---|---|
| G | Primera prueba app-only breve | Aproximadamente8 FPS; retorno0.2 |
| H | Ajustes gráficos | 16.6–16.7 FPS; retorno0.2 |
| I | Ensayo de arranque | Fallo de inicio AW88298 observado; causa no concluida |
| J | Hasta4reintentos de inicio AW | 13.847–15.701 FPS, sin panic visto; retorno0.2 |
| K | Enfoque25/5 con checkpoint pausa/restore; diagnóstico64códigos,18filas | Tests/revisión acotados; sin promoción |
| L | Clima fijo, parser NWS validado y backend | Tests host y despliegue backend posterior |
| M | Evitar setters LVGL repetidos de estado/mic | Mediana31.189 FPS; mínimo26.392, objetivo estable falla |
| N/N2 | Cadencia UI32→28 ms; N2 sincronizó docs/paquete | Mediana25.242 FPS, regresión; rechazado y rollback0.2 |

Pruebas M/N2 fueron **diagnósticos app-only95s con rollback obligatorio**, revisados antes de USB. Dos backups16 MiB coincidentes; particiones OTA4 MiB conservadas. Verificaciones de bytes protegidos fueron anteriores al runtime; no afirman que NVS no haya escrito durante ejecución. No se ensayó modelo WakeNet ni se migró storage/vault. Abrir el puerto USB reinicia la placa.

N3 quedó como hipótesis: investigar sincronización del refresco LVGL con el mutex UI y transferencia SPI para reducir contención. No se escribió código N3. El candidato N2 permanece en el árbol para análisis, claramente rechazado.

## Clima y recuperación TUF

El usuario eligió **Ray City, Georgia**, ubicación fija sin rastreo. Backend NWS asíncrono, single-flight, TLS, límites de tamaño/plazo, vencimiento y omisión de datos antiguos. Se hicieron pruebas de despliegue y rollback reales en ambos hosts; hubo un intento diferido al caer SSH Windows, con rollback Mac completado. SSH volvió sin cambio de cuenta Tailscale por esta tarea. El último apply/auditoría confirmó ambos gateways con el candidato y forecast válido; falta confirmar packet WSS y pantalla física.

El usuario autorizó recuperar el entorno TUF existente y delegar por Herdr Windows. Un agente Codex dedicado realizó la recuperación con revisión Grok; se arrancó la tarea existente una vez, conservando SID/VHD y restaurando el script original. No se importó otra VM ni se amplió el trabajo a otros servicios. La causa histórica del ruido del PC quedó sin identificar; mediciones posteriores de voz baja CPU/GPU no prueban la causa.

## WakeNet

No hay modelo entrenado Sagwa. Se preparó consulta técnica y se envió con autorización. Espressif pidió identidad empresarial; el usuario confirmó su dirección y el servidor de correo TUF. Tras recuperación y revisión, se envió **un único mensaje a 15:13:19Z**, aceptado por Mailcow y relaySMTP2GO con TLS. No se contrató, pagó ni volvió a enviar. La aceptación SMTP no demuestra lectura o entrega en la bandeja del destinatario. Correspondencia y latch anti-duplicado permanecen privados.

## Recursos Higgsfield

El usuario autorizó Higgsfield para personaje/animación. El upload de la ilustración original Muse falló403; no se usó un ID pendiente como referencia. Se utilizó una foto real de Sagwa que ya pertenecía a su biblioteca para generar un atlas alfa de12 poses con GPTImage2.5. Cotización2.75créditos; originales intactos.

Conversión local: poses136×136 con alfa, revisión sobre negro, corrección de recortes que cortaban extremidades/traían fragmentos vecinos. Paquete con hashes copiado aTUF y verificado. Son poses estáticas, todavía sin incorporación a la FSM ni al firmware.

Después se generó un saludo con Seedance2.5:4.042s,960×960,24 FPS,H264,sin audio, cotización28créditos. Referencia real subida/confirmada, clip inspeccionado por contact-sheet. Fondo negro sin garantía de alfa ni loop perfecto. No se compraron créditos; coste cotizado total30.75 no equivale a balance facturado auditado. Clip local conservado, conversión para Core e integración pendientes.

## Nuevo sistema de desarrollo

El usuario creó `terrerovgh/Sagwa` y autorizó acceso común del proyecto. Se prepararon instrucciones comunes de agentes, historia/estado/arquitectura, tareas con aceptación, bitácora append-only, mensajes con reply, recursos con ownership, worktrees y orquestador intercambiable. Se creó un workspace dedicado Sagwa de Herdr sin tomar el foco ni cerrar terminales del usuario. Disponibilidad comprobada: Codex0.162.0-alpha.17.2 y AGY1.3.3; Claude/Grok Mac no encontrados en rutas conocidas. Autenticación de esos agentes no se da por demostrada.

Publicación completada: se inicializó README por el conector GitHub; después el usuario inició sesión web y se agregó una deploy key con lectura/escritura **solo Sagwa**. Se integraron ambas historias sin force-push. La privada está fuera de Git y no se cambió la configuración SSH global. Codex confirmó loginChatGPT; otros logins no se inventaron. Revisión de desarrollo detectó y corrigió aislamiento de sesión/pane, carreras de setup y filtro de publicación; 17testsPASS más 60testsAgentShell y cuatro suites C++ sanitizers. Se liberaron locks propios y se actualizaron registros/handoff de infraestructuraTUF, sin cambios a servicios.
