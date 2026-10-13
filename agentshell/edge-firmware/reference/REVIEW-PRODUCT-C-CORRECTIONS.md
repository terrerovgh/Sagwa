# Correcciones y contraste del dictamen C

Se conserva el FAIL de Grok4.7 (sesión01a1337b-a088-7de1-8b1e-08521cf915c5) en review-product-c.txt. No constituye aprobación de hardware o de despliegue.

## Audio histórico y cursor

El gateway bloquea el poll hasta completar hello/snapshot/settings. Snapshot lee la secuencia antes de obtener tareas: un resultado emitido durante la recuperación no se pierde. Se avanza el cursor a esa frontera y los eventos de un poll ya iniciado nunca lo retroceden. ForegroundTurn rechaza tareas ajenas incluso sin selección; la síntesis automática requiere secuencia posterior a la frontera y tarea seleccionada. Un nuevo snapshot aborta audio pendiente. La repetición explícita por el administrador conserva su autorización independiente.

El Core rechaza audio.start sin secuencia válida o en/antes de la frontera recibida, y checkpoint del cursor se solicita con cada avance. Storage_Task agrupa escrituras NVS cada dos segundos, fuera de UI/audio/network, conserva el máximo y reintenta errores. Un corte de alimentación anterior al commit sigue protegido por la frontera del snapshot; la persistencia no es la única barrera contra replay.

La prueba device-recovery.test.ts ejecuta el método real device del servicio con un socket y fetch simulados: hello queda pendiente mientras pasa un poll500ms; no se leen eventos ni se sintetiza. Después de snapshot100, un speech.ready99 no se reproduce y el101 sí; no se repite en polls posteriores. Sin proveedor real ni gasto API.

## CRC y auditor

El punto de C que pide CRC de28bytes no coincide con ESP-IDF6.0.1. bootloader_support/src/bootloader_common_loader.c:69 ejecuta esp_rom_crc32_le(UINT32_MAX, (uint8_t*)&s->ota_seq,4). esp_flash_partitions.h documenta CRC de ota_seq únicamente. app_update/otatool.py calcula binascii.crc32 sobre cuatro bytes y escribe el CRC en offset28. Se conserva ese algoritmo; ota_state se valida aparte.

La nueva prueba ejecuta switch_ota_partition del otatool oficial con un target enteramente en memoria, sin constructor/USB/esptool. Elimina el registro anterior, confirma el nuevo registro generado y comprueba que pasa el auditor; el CRC de28bytes se rechaza. Siete pruebas del auditor pasan. Esto no sustituye otadata leída del Core.

El auditor exige --candidate-sha256, que debe provenir del recibo de revisión del binario exacto. Rechaza una modificación del cuerpo aunque conserve descriptor/version. El preflight de fuentes se regenera con ese hash; no debe usar una imagen de otra iteración. El auditor sigue declarando deployment_approved=false y no valida origen físico ni firma de release: publicación firmada/rollback son gates separados.

## Enfoque utilizable

FocusTimer pasa a Runtime y solo UI_Task lo modifica. Pantalla Enfoque: iniciar/pausar/continuar, cambiar a descanso5min o enfoque25min, reiniciar. El reloj no empieza al dibujar el widget; no reinicia al cambiar de pantalla y no inicia otra fase automáticamente. Finalización única y aritmética monotónica uint32 con rollover. Snapshot versionado12bytes, sin padding sin inicializar; restore valida y deja un reloj antes activo en pausa. Storage_Task guarda en NVS tras controles/finalización y checkpoints cada60s al correr; se puede perder hasta un minuto más la cola pendiente si se corta la alimentación. No se inventa tiempo apagado. Errores NVS conservan RAM y se registran; reinicio real sigue pendiente.

Harness de producción LVGL: treinta vistas, diecisiete gestos, flujo completo de Enfoque y autorizaciones con ACK. Las fixtures de autorización se limpian entre vistas y Recuperación simula una desconexión real del renderer. No es hardware ni medición eléctrica.

## La voz entra al router del Core

Capacidad client_routes_transcripts se negocia explícitamente como transcript_routing=client en settings/snapshot. Sin ACK del gateway se conserva la conducta anterior, evitando enviar la misma orden dos veces al mezclar versiones. STT sigue local en los servicios existentes; no se promete ASR español general sin red en el ESP32.

Con negociación, media.end devuelve una transcripción limitada4096bytes y no crea aún tarea Muse. Core la acepta una sola vez y en la misma generación, conserva destino/capacidad/preferencia/privacidad capturados y pasa el texto a Router_Task. Comandos de mascota pueden resolverse allí; solicitudes de herramientas/privadas no se interceptan como comandos de mascota. Homelab crea un UUID durable nuevo. Transcripciones antiguas, fotos, texto vacío/NULL/oversize se rechazan. Si desconecta/cambia de turno o transcurren15s, se descarta la espera y se informa del fallo. Las pruebas del método real gateway cubren negociación, flujo nuevo sin envío automático y compatibilidad legacy; el router portable prueba contexto/privacidad/gen y comando local.

## Alcance pendiente

Las fuentes nuevas no están desplegadas. Core sigue0.2; revisión D pendiente. WakeNet genuino, voz/rutas reales Edge, widgets restantes (terminal/clima), distribución de rig dinámica, provisión cloud segura, recorrido físico, 30+FPS/latencias, firmware firmado/rollback y estabilidad24h de la versión final siguen pendientes.
