# Clima de Sagwa

El candidato L añade un pronóstico horario NWS al modo Entorno. Es distinto de la luz/proximidad del CoreS3 y de una temperatura medida: el hardware no aporta temperatura ambiental. El avatar conserva su rig y recibe un tinte suave; las pequeñas variaciones de orejas solo se aplican en reposo. Los indicadores de micrófono, cámara, autorización y error conservan su prioridad.

La configuración es opcional y está desactivada por ausencia. Ejemplo para una ubicación fija, sin GPS ni seguimiento:

```json
{
  "weather": {
    "provider": "nws",
    "city": "Ray City, GA",
    "latitude": 31.0749,
    "longitude": -83.1999
  }
}
```

Las coordenadas del ejemplo necesitan confirmación antes del despliegue. No se cambió ninguna configuración de los gateways activos. NWS cubre Estados Unidos; el proveedor de otro país requerirá un adapter adicional. Su API es gratuita para cualquier uso según [la documentación oficial](https://www.weather.gov/documentation/services-web-api). No consume el presupuesto compartido de voz ni transmite datos de la conversación.

`WeatherService.snapshot()` devuelve inmediatamente una copia y comienza una única consulta asíncrona compartida por conexiones. Consulta HTTPS exclusivamente a `api.weather.gov`, rechaza redirecciones/enlaces externos y limita cuerpo a 512 KiB y tiempo a cinco segundos. Refresca cada diez minutos; tras fallos, espera al menos un minuto. No bloquea el protocolo de voz ni el dibujo.

El contrato `device.settings.weather` / `device.snapshot.weather` usa `schema:1`, `available`, `source:nws`, `kind:forecast`, ciudad ASCII de hasta 40 caracteres, temperatura entera en centésimas Celsius, condición de catálogo y TTL entero de 1–900 segundos. No envía URLs al firmware. Se requiere un período horario actualmente válido, publicación `updateTime` de hasta seis horas y temperatura entre −90 y 60 °C. La caché vence al acabar el período, llegar a seis horas de publicación o transcurrir quince minutos, lo que ocurra antes. Un error no renueva esa validez.

El firmware valida el paquete dentro del canal WSS autenticado y guarda una copia bajo `status_mutex`. UI copia el dato bajo su bloqueo LVGL; Sensor_Task no lo produce. El vencimiento utiliza resta monotónica de 32 bits con rollover. Cuando falta o vence, se oculta la temperatura y aparece «sin dato reciente». No ejecuta comandos ni emite sonidos por clima.

Pruebas: parser portátil con ASan/UBSan, fechas/unidades/frescuras inválidas, SSRF, una consulta concurrente, corte/apagado, caché vencida y dos vistas LVGL con pronóstico vigente/vencido. La primera consulta real reveló el campo incorrecto `updated`: se corrigió a `updateTime` y se conservó la prueba fallida. El sondeo corregido de la coordenada pública de ejemplo NWS obtuvo HTTP 200 y un paquete válido; no demuestra funcionamiento en el CoreS3. El fixture público capturado preserva este contrato real. La galería utiliza 25 °C sintéticos claramente identificados.

No se publica ni flashea L hasta congelar fuentes, revisión independiente y pruebas reversibles. Tampoco sustituye la recuperación WSL/Mailcow en curso ni el modelo WakeNet genuino todavía pendiente.
