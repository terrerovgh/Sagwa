# Objetivo global y requisitos

Construir una compañera felina reconocible como Sagwa, fluida y agradable en un CoreS3, que responda al usuario y al entorno local y use capacidades autorizadas de Mac mini/TUF sin depender permanentemente de un ordenador. Interfaz y voz en español; respuestas habituales de 5–10 palabras, con cifras necesarias y detalle completo accesible.

## Experiencia

Pantalla 320×240, negro `#000000`, Inter blanco `#FFFFFF` con acentos; personaje transparente 136×136 arriba, emoji de estado 28×28 a la derecha y respuesta de 16px debajo, hasta tres líneas. Sin reloj, batería o botones permanentes en la principal. Los colores propios del gato/emoji se conservan.

Gestos de borde: izquierdo menú, derecho herramientas, superior configuración; secundarios vuelven desde izquierda. Texto deslizable y lectura ampliada al tocar; acariciar produce reacción de mascota, nunca grabación. PWR mantenido escucha, soltar envía y pulsar durante voz la detiene. Indicadores visibles de micrófono/cámara; fotos, cancelaciones y acciones autorizadas mantienen confirmación explícita. Filas táctiles ≥44px.

Rediseñar menú, herramientas, agentes, destinos, tareas, lectura, cámara, sensores, voz, preferencias, cancelación, autorización y errores. Estados importantes de conexión/escucha/trabajo/habla/aprobación/error prevalecen sobre reacciones de mascota.

## Motor Edge

FSM procedural por capas: respiración, parpadeo estocástico, orejas, pupilas y easing; doble buffer PSRAM y SPI DMA, objetivo **30+ FPS sostenidos medidos al terminar SPI**. Doce reacciones/poses: reposo, mirar, escuchar, pensar, hablar, trabajar, celebrar, ronronear, dormir, despertar, estirarse e inclinarse. La animación de habla sigue el audio real.

Diez skins: mascota, enfoque/Pomodoro, diagnóstico, noche, centinela, terminal, multimedia/FFT, trabajo, clima y recuperación. `SkinManager`, descriptores JSON validados y factories C++ mediante `SagwaPluginInterface`; hot-reload opcional SD/SPIFFS, sin ejecución de scripts descargados.

Wake-word genuino «Sagwa», ESP-SR/WakeNet 100% local. Maullido local inmediato antes de abrir red. SFX licenciados y atribuidos: caricia→ronroneo, proximidad→mirar/saludar, inclinación/levantar→despertar, sacudida→quejido, oscuridad sostenida→dormir. Suavizado/histéresis, frescura y pausa de cinco segundos entre sonidos espontáneos; conversación interrumpe SFX.

## Inteligencia y voz

Router local: capa 0 comandos mecánicos sin red; capa 1 OpenRouter standalone; capa 2 rigs autorizados; capa 3 adapters comerciales. Disponibilidad real, contexto privado y capacidades deciden destino. OAuth es una futura integración específica del proveedor, no una promesa de acceso API por suscripción de chat.

Muse conserva el rol principal del producto. Qwen local es auxiliar sin herramientas. Sensores no ejecutan comandos en hosts. Actividad global de Muse permanece limitada por HTTP403; no prometer sincronización sin acceso permitido.

TTS: Chatterbox latinoamericano GPU TUF → Kokoro `ef_dora` Mac Docker/nativo → OpenRouter ElevenFlash2.5 `bella`, con US$5/mes compartidos incluyendo pruebas. Audio PCM mono16kHz streaming, descarte de turnos cancelados y métricas separadas de Muse/síntesis/playback. Las claves/proveedores deben estar realmente habilitados y autorizados.

## Aceptación

Tacto<100 ms, sensores<250 ms, primer audio TTS<2s en condiciones normales; medir hardware, no inferir de tests host. Probar offline, sensores antiguos, voz interrumpida, cambio de host, reconexión, API caída y cuota agotada. Revisar todas las pantallas y muestras de voz antes del release; OTA firmada, rollback probado y 24 h de estabilidad **del release candidato**.

Conservar offsets/tamaños OTA y no exigir SD. La tabla de datos experimental Edge difiere de la instalada: migración pendiente, no autorizada por un build ni por las pruebas app-only. Las pruebas breves sobre la tabla antigua no aceptan WakeNet/storage/vault del producto final.
