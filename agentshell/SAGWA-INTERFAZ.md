# Sagwa en CoreS3

La interfaz v2 utiliza negro puro y blanco Inter. En la pantalla principal aparecen Sagwa sin círculo blanco, un emoji fijo de estado a la derecha y hasta tres líneas de respuesta. Las vistas completas y las animaciones están en [la galería](evidence/sagwa-v2/index.html).

## Navegación

- Borde izquierdo hacia dentro: menú. En vistas secundarias: volver.
- Borde derecho hacia dentro: herramientas.
- Borde superior hacia abajo: configuración.
- Deslizar el texto: avanzar o retroceder; tocarlo: lectura ampliada.
- Acariciar o tocar a Sagwa: ronroneo local.
- Mantener PWR: hablar. Soltar: enviar. Pulsar durante reproducción: detener.

Menús y filas usan zonas de44px. Fotografías, cancelaciones y autorizaciones requieren una acción explícita. Una autorización se lee completa mediante desplazamiento y se confirma manteniendo1.5s la zona indicada. La cámara y el micrófono conservan indicadores. Las reacciones de mascota ceden ante escucha, trabajo, habla, autorización o error.

## Animación y sensores

Las doce animaciones nuevas proceden de Imagegen y conservan la identidad del avatar original: reposo, mirar, escuchar, pensar, hablar, trabajar, celebrar, ronronear, dormir, despertar, estirar e inclinar. El atlas transparente original generado y el brief están en assets/sagwa/generated. Las imágenes y vídeos originales exportados de Muse están intactos en .private/sagwa/originals; las nuevas poses se identifican como generated_sagwa_v2.

Los clips completos se alojan en Mac mini y TUF. El dispositivo acepta solamente sus gateways mTLS, verifica SHA256 y mantiene tres clips en PSRAM. El firmware incorpora33fotogramas de respaldo y sonidos pequeños. No necesita microSD. El dibujo se limita a15FPS; estos clips tienen cuatro poses por segundo. La boca sigue la energía del audio que reproduce realmente el altavoz.

Las caricias, proximidad, movimiento y oscuridad sostenida producen reacciones locales. Se suavizan los sensores, se aplica histéresis y se descartan lecturas de más de600ms. Los sonidos espontáneos tienen una pausa mínima de5s. No se ejecutan comandos desde sensores. Los sonidos grabados de Peter Hull y Dan Crosby conservan sus licencias y créditos en assets/sagwa/ATTRIBUTION.md y en Acerca de Sagwa.

## Voz y texto

Muse permanece como agente principal. Se solicitan respuestas habituales de5–10palabras; cuando hace falta detalle, se conservan cifras, instrucciones y el resultado completo en lectura ampliada. El transporte del texto completo se pagina sin romper UTF8. Un gesto de lectura nunca autoriza una acción.

Chatterbox español latinoamericano utiliza la RTX4060 de TUF con reserva exclusiva deGPU mediante _coord. Kokoro ef_dora funciona en CPU del Mac mini. El último respaldo utiliza OpenRouter Eleven Flash v2.5 bella, con reserva transaccional previa y máximo compartido deUS$5por mesUTC, incluidas pruebas. Tarifas desconocidas y presupuesto agotado bloquean llamadas. El ledger se conserva durante una reversión.

El audio se entrega en PCM mono16kHz y se reproduce conforme llegan muestras. Un turno cancelado no puede volver a reproducir audio. Las mediciones separan tiempo del agente, síntesis y primera trama; reaction_timing mide desde la detección local hasta terminar el dibujoLCD, sin afirmar que incluye el movimiento previo del dedo.

## Verificación y despliegue

El procedimiento y la reversión están en SAGWA-DEPLOY.md. Galería y muestra de voz se presentan antes de publicar firmware firmado. Los resultados se guardan en evidence/sagwa-v2; la validación de24h solo se considera aprobada cuando termina. La actividad global de la aplicación Muse sigue sin sincronizarse: /identity devuelveHTTP403.
