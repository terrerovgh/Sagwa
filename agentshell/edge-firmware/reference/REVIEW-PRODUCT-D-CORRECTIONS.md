# Correcciones de la revisión D

D devolvió FAIL sobre `fc5800638acba7c7a9f894ce554c4a456c34dd3b329c13b66fc85538c7ba3c7d`.
Ese binario, el prompt, el manifiesto y el dictamen permanecen conservados.
Las correcciones siguientes pertenecen a otro candidato; no cambian el firmware
0.2.0 instalado ni los gateways en servicio.

1. **Enfoque:** `row_cb` solo encola `focus_control`. Únicamente `ui_task`
   modifica el temporizador y copia sus snapshots para StorageTask. Tick,
   lectura/render y publicación del estado visible comparten el lock de LVGL;
   ninguna copia de `visible_status` ocurre mientras otro callback la lee.
   Los controles de Enfoque no se descartan por cambiar una conversación.
   Cada mutación lee tiempo monotónico reciente: un snapshot puede avanzar
   el anchor después del timestamp inicial del frame.
2. **Recuperación:** `sendSnapshot` mantiene un contador durante todo el
   snapshot y las lecturas de tareas. Incrementa un epoch y aborta TTS al
   comienzo y justo antes de instalar la frontera. El poll no entra durante
   recuperación y un poll pendiente vuelve a comprobar epoch después de I/O
   y de consultar una tarea. No emite audio ni resultados de la vista anterior.
3. **Repetición autorizada:** `audio.start` incluye un `control_sequence`
   monotónico independiente por sesión y `explicit_replay`. Solo `replay`,
   validado contra tarea seleccionada, cancelación y disponibilidad, crea esa
   excepción. `voice.sample` usa la misma ruta. La reproducción automática
   mantiene la frontera del cursor durable; una repetición explícita requiere
   un control nuevo válido. `AudioStartGate` rechaza control repetido/inferior
   y no baja la frontera. No se inventan eventos ni se adelanta NVS al reproducir.
   El Core valida sesión, UUID de tarea/stream, generación, parada de voz y
   formato antes de aceptar el control. Reinicia su namespace al cambiar sesión.
4. **Guía:** exige las fuentes completas de `agentshell/src` y hashes de la
   revisión correspondiente. `gateway-compat.patch` queda solo como archivo
   histórico; no se aplica como sustituto del gateway actual.

Pruebas nuevas: handler real con WebSocket y fetch simulados, poll bloqueado en
eventos o tarea durante `device.resume`, repetición en la frontera seguida de
evento durable nuevo y muestra de voz; puerta portable de audio bajo ASan/UBSan;
callback real de LVGL que conserva el reloj hasta la siguiente iteración de UI.
Estas pruebas no certifican scheduling, audio, latencia o pantalla físicos.

Pendientes: revisión independiente del candidato exacto, preflight físico,
modelo Sagwa genuino, paquetes dinámicos, clima configurado, integración Qwen,
APIs provisionadas, migración de almacenamiento, rollback y validación 24 h de
la versión final. Sin autorización de eFuses, compras o entrenamiento de pago.
