# Muse en M5Stack CoreS3

Firmware oficial: `muse-gadget-sdk`, revisión `812c46f`.
Herramientas: ESP-IDF 6.0.1 para ESP32-S3, instaladas en
`/Users/terrerov/esp/esp-idf-v6.0.1`.

Dispositivo comprobado: ESP32-S3, 16 MB de flash y 8 MB de PSRAM.
Nombre Bluetooth: **MuseGadget-4D5F7C**.
Puerto durante la instalación: `/dev/cu.usbmodem21101` (puede cambiar).

## Vincular y usar

En la app Muse, con tu cuenta iniciada, abre Settings > Devices, activa
Developer mode y añade MuseGadget-4D5F7C. Confirma con una pulsación breve
de PWR, en el lateral izquierdo, y configura tu Wi-Fi desde la app.

Para hablar, mantén PWR mientras dices tu consulta y suéltalo al terminar.
Las respuestas del SDK estándar aparecen como texto en pantalla.
Desliza a la izquierda para abrir los ajustes táctiles.
Para reiniciar la vinculación, usa la opción correspondiente de los ajustes
táctiles; durante el emparejamiento basta una pulsación breve de PWR.

## Compilar, actualizar y consultar

Desde esta carpeta, activa las herramientas:

```sh
source ./activar-muse.sh
cd muse-gadget-sdk/esp32
python tools/muse/ports.py --list
python tools/muse/chat.py --port /dev/cu.usbmodem21101 --status
tools/muse/board.sh build cores3
tools/muse/board.sh flash cores3 /dev/cu.usbmodem21101
```

El token está en `.sdk-token` dentro del repositorio y en la configuración
generada `esp32/build-muse-m5stack-cores3/sdkconfig`. Ambos están excluidos
de Git. No publiques esos archivos ni el firmware binario, que incorpora
el token. Conserva el sdkconfig si recompilas; si lo borras, introduce de
nuevo el token en CONFIG_GADGET_SDK_TOKEN antes de compilar.

## Copia y recuperación

La copia completa original, de 16 MB, está en
`muse-gadget-sdk/backups/cores3-original-80456b4d5f7c.bin`.
El JSON del mismo nombre contiene su tamaño y SHA-256.

El firmware anterior usaba una tabla de particiones distinta. Para instalar
Muse se preparó únicamente la nueva zona NVS, de 0x11000 a 0x1cfff;
no se ejecutó un borrado completo de la flash.

Para restaurar el firmware original (esto reemplaza Muse y su configuración):

```sh
source ./activar-muse.sh
python -m esptool --chip esp32s3 -p /dev/cu.usbmodem21101 -b 460800 \
  write-flash 0 muse-gadget-sdk/backups/cores3-original-80456b4d5f7c.bin
```

Si el dispositivo no responde para grabarlo, mantén RST en el borde inferior
durante 3 segundos, hasta que se encienda el LED verde, y vuelve a identificar
el puerto USB.

## Comprobaciones realizadas

- Firmware compilado y grabación verificada por hash.
- Tamaño del firmware: 0x201000 bytes, dentro de la partición de 4 MB.
- Arranque correcto, 8 MB de PSRAM, pantalla y táctil detectados.
- Códec y micrófonos inicializados, incluida su comprobación de captura.
- 222 pruebas del SDK: OK, con 1 omitida por faltar la biblioteca PSA Crypto
  del sistema anfitrión.

- Vinculación guardada y Wi-Fi conectado, con estado **Online** confirmado
  desde el CoreS3.
- Consulta enviada a Muse desde el CoreS3 por USB: respuesta recibida,
  **«Conexión correcta.»**.

- Consulta de voz comprobada: el botón PWR activó el micrófono, se envió una
  grabación de 2,74 segundos y Muse devolvió una respuesta en pantalla.
  El usuario confirmó que la respuesta era visible.

Los fallos iniciales de autenticación Wi-Fi se resolvieron al repetir la
configuración desde la app.

Documentación: https://github.com/facebookincubator/muse-gadget-sdk/blob/main/esp32/README.md
