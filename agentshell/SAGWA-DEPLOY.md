# Sagwa v2 — aceptación y despliegue

Solicitud original: negro #000000 en todas las vistas; solamente avatar transparente136px, emoji28px a la derecha y respuesta blanca Inter16px en principal. Respuestas habituales5–10 palabras, resultados completos sin recortar aprobaciones. Todos los menús, voz, sensores, mascota, tareas, cámara, autorizaciones y errores. Gestos desde bordes, caricia del avatar y PWR para voz. Doce estados nuevos Imagegen preservan identidad; los originales están intactos en .private/sagwa/originals. Reacciones locales offline, frescura600ms, histéresis, sonidos suaves separados5s. Las lecturas no ejecutan herramientas.

Voz: Chatterbox LATAM V3 en RTX4060 WSL infra; lease GPU coord exclusivo, libera tras60s sin uso. Kokoro ef_dora CPU Mac mini. OpenRouter Eleven Flash v2.5 bella únicamente Mac, presupuestoSQLite transaccional compartido5USD/mesUTC, reserva previa conservadora, tarifa consultada antes de cada petición en APIoficial y fallo cerrado. Los intentos y pruebas se cobran a la reserva completa aunque fallen. API MP3 decodificada a PCM16k mono; evita asumir sample rate de PCM remoto. `/tts/stream` chunked, reproducción progresiva y cancelación por generación; no cambia de voz después del primer audio. Mantiene STT, /tts y /tts/contextual.

Paquetes SAV1 por estado≤1.184MB, cada clip actual148KB.12 archivos,1.776MB. Firmware embebe33 fotogramas1.221MB+sonidos~63KB; caché3clipsPSRAM. mTLS, origen y ruta exactos de gateway, SHA256, formato/tamaño/campos verificados; sin redirecciones. Sin SD y particiones OTA intactas. No usa el avatar contextual para sustituir a Sagwa. No replica la actividad global de Muse: /identity devuelve403.

## Secuencia y alcance
1. Construir y ejecutar pruebas; mostrar galería/muestra al usuario.
2. Registrar tarea/rolinfra y adquirir locks propios svc-agentshell, proj-agentshell-sagwa y coordinación cuando disponible. No liberar locksajenos.
3. Revisar ADR/código/scripts con Grok de otra familia. Nunca leer secretos en el informe.
4. Preparar nueva imagen Docker aislada, pesos y referencia sintética Kokoro en TUF. No sustituir voz vigente antes de prueba del candidato. /opt/agentshell y _coord solo dentro de locks propios. Ningún sitio público/DNS/Traefik cambiado.
5. Backup coherente de dist/config/voz/LaunchDaemon/systemd y firmwarefirmadoanterior. Mantener Whisperactual. Solo gatewaysMac/TUF cambian; lenlab conserva etcd y su servicio. El nuevo gateway interpreta respuestas JSON también del coordinador anterior.
6. Instalar Kokoro aislado, Chatterboxcandidato y probar mTLS, primeras muestras, fallos, presupuesto y cancelación. Habilitar nueva voz después de pruebas. Credenciales solo rutas privadas, permisos600; paidLLMs no activados.
7. Publicar release0.2.0 firmado mediante mecanismoexistente; ofertaOTAalCore. Confirmación localboot y rollback ya existentes. USB no cambia particiones.
8. Validar sensores, audio y navegación, iniciar soak24h y observar resultado posteriormente. No declarar passed antes24h. Preguntar al usuario por prueba táctil/voz física cuando haga falta.

## Reversión
Detener los servicios nuevos antes de restaurar. Restaurar dist/config y scriptsvoicecopiados de la precopia; restaurar unidadesLaunchDaemon/systemd; reiniciar una instancia por servicio. Ofrecer el hashfirmadoanterior por OTA (no reflashear tabla). Guardar el SQLitebudget nuevo: borrarlo reiniciaría el gasto permitido. Liberar solo el leaseGPUpropio y lockspropios después de detenerChatterbox. Verificar /health, tresnodostelemetry y firmwareprevio. Antes de aplicar, ensayar que el tar backup recupera hashes y que el manifiestoreleaseanterior verifica su firma.

## Estado verificado al 12 de octubre de 2026

Sagwa **0.2.0 aplicado** en CoreS3 y servicios Mac mini/TUF. Firmware firmado SHA-256 `88e9c70d2b1f521c48f928e146aa442a94b403ddb6227f94db2043fa3a9231ba`, 2,797,472 bytes, 33% de margen OTA. Lenlab conserva sus servicios. Los respaldos y el manifiesto firmado anterior verificaron sus hashes antes de aplicar.

Revisión independiente Grok PASS en tres etapas: implementación, latencia y limpieza de GPU/stream. Evidencia y hashes en `evidence/sagwa-v2/review-receipt.json`. Pasaron 44 pruebas TypeScript, 22 Python y el controlador C++. No se repitieron pruebas sin un cambio que lo justificara.

En hardware: cámara local de 153,600 bytes, captura de micrófono de 53,120 bytes en la prueba, reproducción reconocida por el dispositivo sin fallos; 78 acciones táctiles registradas. Touch→fin de dibujo 31 ms y lectura de sensor→fin de dibujo 18–89 ms en las muestras conservadas. No son mediciones desde el contacto físico/acústico inicial. El readback SPI del LCD no funciona; la verificación de negro/transparencia es del compositor y la confirmación visual humana sigue pendiente.

Primer PCM de Chatterbox local-only: **1.3769 s**, audio de 3.8 s. Kokoro después del reinicio final: **0.3833 s**. Respaldo Mac con gateway TUF apagado: aproximadamente **0.325 s**; se restauró TUF después de comprobar el cambio automático del Core. Bella API: **1.4067 s**, una prueba con reserva de US$0.00088 en el mismo ledger. Estos tiempos de síntesis no incluyen Muse: la conversación de prueba de Muse tardó 20.119 s y devolvió siete palabras.

La prueba de estabilidad de 24 horas empezó **2026-10-12 23:17:11 UTC**. `soak.json` contiene progreso/fallos actuales. LaunchAgent `ai.agentshell.sagwa-soak` supervisa el monitor; la automatización `validar-sagwa-24-horas` revisa el resultado sin avisos repetidos. No se declara completada hasta reunir 86,400 segundos válidos. No es una prueba de estrés continua de cámara/voz.

La nueva solicitud de arquitectura LVGL/WakeNet/router está en `edge-firmware`, versión **0.3.0-dev**, y permanece como candidato sin flashear. Su build y pruebas no validan las capacidades físicas de ese proyecto ni alteran esta prueba de 0.2.0.

## ADR de GPU y recuperación
WSL infra no puede leer _coord por ACL Windows. No se modifican esas ACL. Un broker fijo en Mac usa SSH Windows existente y coord.ps1, exclusivamente para gpu. Solo el certificado node:tuf-infra puede llamar la ruta mTLS. Identificadores fijos validados; cada lease UUID queda en Scope dentro del CreateNew atómico y en dos estados persistentes privados. Una llamada perdida puede repetirse con el mismo UUID. Nunca libera un UUID diferente ni roba locks vencidos. El proceso Chatterbox conserva CUDA durante60s inactivo, descarga el modelo antes de liberar. Reinicio del contenedor único puede recuperar su propio UUID persistido; reaper libera la reserva del proceso anterior una vez muerto. La reversión detiene el contenedor antes de liberar el lease propio y conserva el ledger de gastos. El broker no acepta comandos ni rutas del dispositivo.

Instalador concreto: scripts/deploy-sagwa.py. Prepara backups privados, compara sus bytes y copia solo dist/voz/bridge/config de Mac y TUF. Conserva supervisores actuales y el venv anterior; el servicio de Mac usa un launcher hacia venv-sagwa aislado. El servicio TUF conserva red privada, usuario999, cap-dropALL, read-only y montajes de modelos/TLS. El único estado writable añadido es voice-state. Lenlab, etcd, puertos públicos y otros servicios quedan fuera del alcance.

Correcciones tras revisión: warmupGPUfuera deHTTP, fallofríoinmediato; cancelación entre tokens/frases; first_audio_timeoutconservamodelo; renovacióndel leaseenreaper45s ydescarga60s, reintentosdurables; TUFborra APIheredada; contextualeligeunsolomotorlocal; rollbackvalidabackupsantesdepararyrestauramboshostsapesardefallounlock. APIverificatambiénproveedorElevenLabsúnico ytarifaigualantesdereservar.

### Interrupción de la prueba

El 12 de octubre a las 20:21 EDT se registró un reinicio del Core, con `reset_reason=1` (arranque por alimentación). Reconectó a Mac mini y siguió reportando 0.2.0. Desde las 20:23 EDT la telemetría de tuf-infra está antigua; las muestras del monitor fallan por ese nodo, no por pérdida del Core. El SSH Windows de TUF responde, pero el SSH a WSL no. La prueba actual **no demuestra 24 horas continuas**; se conservan las muestras y hay que identificar la interrupción antes de repetirla. No se reinició ni flasheó el Core durante la preparación de edge-firmware.

El usuario confirmó que pulsó por accidente el botón de reinicio del Core. No se atribuye ese reinicio al firmware. Diagnóstico TUF: RTX4060 al0%,36°C; vmmemWSL PID20372 CPU6.641s/1s y15.5GB RAM; host~1.2GB libres. No hay evidencia suficiente para atribuirlo al TTS. Sonda WSL por runner preexistente no devolvió datos; se detuvo exclusivamente la ejecución temporal propia y se restauró Mount-DataDisk.ps1 byte a byte SHA256 e030c8afcf9805c590d31b5134c0b6aee0ed49a031f5340a5777d5a94fd2d4cd. No se detuvieron VMs, Docker ni servicios de negocios.

### Recuperación observada de TUF

La sesión Linux volvió a responder y la telemetría se recuperó tras un arranque del guest ocurrido fuera de esta tarea, aproximadamente a las 20:50 EDT. En la muestra de las 21:17 EDT, WSL tenía unos 7.3 GB disponibles, el contenedor de voz consumía 0.01% CPU y 283 MiB, y la RTX 4060 estaba al 0% y 39 °C. No se observó un bucle activo de voz. La causa de la carga anterior permanece sin identificar; no se atribuye a Sagwa por inferencia. Véase `evidence/sagwa-v2/tuf-diagnostic.json`.

### Docker Desktop de Mac mini

El worker de voz dedicado y el modelo auxiliar están preparados y probados. Su estado de promoción, hashes y reversión real se registran en `evidence/sagwa-v2/mac-docker.json`. La guía reproducible está en [voice/MAC-DOCKER.md](voice/MAC-DOCKER.md). No confundir una imagen Docker saludable con un cambio ya conectado al servicio de voz instalado.

La promoción Docker Mac ya está aplicada y verificada: orden Chatterbox TUF, Kokoro Docker, Kokoro nativo y API. Primer PCM a través del router instalado: 0.7106 s; transcripción de la frase de prueba: 1.1047 s. Con el worker detenido, el respaldo nativo produjo PCM en 0.34 s. La reversión restauró los tres hashes originales y el proceso supervisado; después se reaplicó el candidato revisado. El ledger conserva una única reserva previa de US$0.00088, sin gasto nuevo en estas pruebas. El Core reprodujo una respuesta posterior al cambio sin fallos de altavoz registrados.

Se detuvo el monitor anterior conservando sus archivos y marcando su resumen como `interrupted`. La nueva ventana separada usa `soak-docker.json` y el LaunchAgent `ai.agentshell.sagwa-docker-soak`; la automatización existente fue actualizada, sin duplicarla. Esta prueba está en curso, no aprobada.
