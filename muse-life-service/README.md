# Muse con voz y escenas en CoreS3

Servicio doméstico en `tuf-1`, Windows 11 + Docker Desktop. Muse sigue siendo el agente; Piper sintetiza sus respuestas. Sin API de voz de pago.

## Operación

Directorio Windows: `C:\Users\terrerov\muse-life-service`.

```powershell
cd $env:USERPROFILE\muse-life-service
$env:DOCKER_CONFIG="$PWD\.docker-local"
docker compose up -d --build
docker compose ps
docker compose logs --tail 30
docker compose restart
```

Docker Desktop se abre mediante `Muse Docker.lnk` en Inicio del usuario. Compose tiene reinicio `unless-stopped` y healthcheck. Requiere iniciar sesión en Windows; no funciona con tuf-1 apagado. La IP de tuf-1 debe seguir siendo `192.168.4.64`; si cambia, actualizar Compose y la URL local del firmware. Reservar esta IP en el router es recomendable.

`.docker-local/config.json` contiene únicamente la configuración de descarga anónima de imágenes públicas. No modifica las credenciales personales de Docker.

## Credenciales y red

`.env` contiene `MUSE_LIFE_TOKEN`, generado localmente. No es el token SDK. No compartirlo ni incluirlo en Git. El mismo secreto está en el `sdkconfig` local ignorado del CoreS3. Las llamadas `/context`, `/tts`, `/camera` y `/cancel` requieren Bearer. `/health` muestra únicamente estado; imágenes `/assets` usan identificadores aleatorios de 192 bits y caducan en una hora.

El contenedor escucha mediante `192.168.4.64:8765`. Windows permite el puerto únicamente desde `192.168.4.0/22` y bloquea explícitamente direcciones externas a esa subred. La regla previa de bloqueo TCP de Docker conserva todos los puertos salvo 8765. No se abre el router ni se publica el servicio en Internet. HTTP es local; esta configuración presupone una red doméstica de confianza.

No se persisten conversaciones, fotos originales ni audio. Las fotos preparadas caducan en una hora. La ciudad aproximada inferida por IP se guarda 24 horas. La geolocalización transmite la IP pública a ipwho.is, no GPS. Las consultas de tiempo usan Open-Meteo; las de Bitcoin, Kraken. Las URL de noticias se descargan sin credenciales; se rechazan redes privadas y redirecciones internas.

## Comandos de Muse

- `sensors.read`: lecturas de aceleración `g`, giro `deg/s`, magnetismo compensado `uT`, luz ADC a ganancia 1x, proximidad relativa, temperatura interna del BMI270, batería/alimentación, RTC, nivel de audio y reacción táctil. Valores con `age_s`, disponibilidad y estado; fallo o lectura antigua implica `value:null`. No equivale a temperatura ambiente. No hay humedad integrada.
- `sensors.read {"calibrate":"start"}`: girar el aparato por todos los ejes durante 30 s; solo guarda calibración si cada eje cubre un rango suficiente. `cancel` aborta. Compensación de offset y escala por ejes; no sustituye una calibración de laboratorio.
- `sensors.read {"effects":false}`: desactivar reacciones físicas y brillo ambiental; `true` reactiva. El brillo usa señal relativa ADC, sin inventar lux.
- `camera.capture`: foto solo al solicitarla. Indicador de cámara en pantalla, GC0308 320×240, JPEG base64 para el mecanismo del SDK. Cierra captura y libera buffers antes de enviarla al servicio.
- `context.get {"topic":"weather","city":"Madrid"}`: tiempo real en Celsius; `city` opcional. Sin ciudad, IP aproximada de casa. Si falla la ubicación, preguntar lugar. Mostrar ubicación aproximada como tal.
- `context.get {"topic":"bitcoin"}`: precio BTC/USD, variación entre primer punto de la ventana y precio actual, serie y gráfica ASCII de 24 h; fuente Kraken y hora UTC. Caché 60 s; identificar `stale:true`.
- `context.get {"topic":"news","article_url":"https://…"}`: busca `og:image`/`twitter:image` del artículo. Puede recibir `image_url` y `reference:true` para imagen temática. Si no hay imagen, escena ASCII y aviso explícito. Muse debe identificar el artículo; este servicio no inventa ni busca noticias por su cuenta.
- `display.present`: pasar `scene`, `title`, `data`, `ascii`, `image_url`; también acepta `frames` (máximo 8 cadenas) e `interval_ms` 100–5000. ASCII hasta 38 columnas ×16 filas, 1600 bytes por cuadro. Subtítulos conservan zona inferior.
- `display.draw_url` y `display.show_animation` siguen disponibles.

Para tiempo, Bitcoin y noticias, consultar contexto **antes** de responder; luego presentar el resultado. Para otros temas, crear ASCII pertinente y enviar `display.present`. No leer ASCII literalmente: separar el dibujo del texto hablado usando bloques de código.

Los resultados se asocian a la generación del turno. PWR interrumpe reproducción y cancela síntesis pendiente. El servidor puede terminar una inferencia de Piper ya en curso antes de reconocer la cancelación; su resultado se descarta. Al fallar el servicio, continúan Muse, subtítulos y personaje local.

## Firmware

Activar ESP-IDF v6.0.1 en la Mac (`source ../activar-muse.sh` desde la carpeta adecuada). En `esp32`, conservar `build-muse-m5stack-cores3/sdkconfig`, incluidos los tokens locales, y ejecutar:

```sh
idf.py -B build-muse-m5stack-cores3 build
idf.py -B build-muse-m5stack-cores3 -p /dev/cu.usbmodem21101 flash
```

Para una configuración nueva, cargar `devices/sdkconfig.muse-life-cores3` después del perfil CoreS3 e introducir ambos tokens localmente. No borrar NVS. Las copias originales y anteriores al cambio están en `muse-gadget-sdk/backups`, excluidas de Git; contienen configuración privada.

Consola USB para diagnóstico: `>life.sensors`, `>life.sensors={"calibrate":"start"}`, `>life.context={"topic":"weather"}`, `>life.present={"ascii":"…"}`, `>life.capture`, `>life.memory`. Captura devuelve imagen base64: no volcarla en el chat. Los comandos de captura siguen siendo explícitos.

## Fuentes

- [Piper](https://github.com/OHF-Voice/piper1-gpl) (GPL-3.0; revisar también MODEL_CARD de la voz al redistribuir).
- [Open-Meteo](https://open-meteo.com/en/docs).
- [ipwho.is](https://ipwhois.io/documentation).
- [Kraken ticker](https://docs.kraken.com/api-reference/market-data/get-ticker-information) y [OHLC](https://docs.kraken.com/api-reference/market-data/get-ohlc-data).
- Hardware: M5Unified, M5CoreS3 y Espressif m5stack_core_s3. El controlador Bosch BMM150 conserva su licencia BSD-3-Clause en `boards/bmm150`.
