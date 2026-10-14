# Estado verificable · 2026-10-13

Este archivo es la entrada canónica de estado y prevalece sobre frases antiguas de preparación en guías/recibos. Las fechas siguientes son observaciones históricas UTC, no comprobaciones de salud en vivo.

| Área | Hecho observado | Pendiente / límite |
|---|---|---|
| CoreS3 | N3a 0.3.0-dev instalado para prueba manual a 2026-10-14 01:52:52Z; boot_verified y telemetría fresca | 0.2.0 preservado; aceptación del usuario y 24 h pendientes |
| Edge 0.3 | Código compilado, tests host y pruebas app-only G/H/I/J/M/N2/N3a | Ningún Edge promovido; N2 rechazado |
| UI host | 33 pantallas,21 gestos y14clips; rig Higgsfield y respaldo pasan ASan/UBSan | No prueba óptica/táctil completa del release |
| Rendimiento M | 26.392–31.280 FPS, mediana31.189; máximo gap129.734 ms | No alcanza30 FPS en todas las muestras |
| Rendimiento N2 | 24.826–26.653 FPS, mediana25.242; máximo gap126.149 ms | Regresión; **no publicar** |
| Voz | TUF Chatterbox principal, Docker Mac Kokoro respaldo detrás de9450; promoción/reversión ensayadas | Nuevo Edge: aceptación acústica, interrupciones y latencias finales |
| Clima | NWS Ray City desplegado en ambos gateways a 18:15:51Z; smoke módulo instalado | Packet WSS y visualización física sin verificar |
| WakeNet | Consulta empresarial enviada una vez y aceptada por transporte SMTP | Modelo «Sagwa» todavía no recibido; inbox del destinatario no demostrado |
| Higgsfield | Rig nativo13capas derivado de idle, integrado y flasheado con N3a; originales12poses y saludo preservados | Aprobación visual del usuario pendiente; saludo sin integrar |
| Desarrollo | Claude Opus5.5, Grok4.7 High y AGY Gemini3.8 Flash High participaron desde Herdr; coordinación persistente | Dictámenes locales no sustituyen aceptación del producto |

## Versión instalada y candidatos

0.2.0: SHA256 `88e9c70d2b1f521c48f928e146aa442a94b403ddb6227f94db2043fa3a9231ba`, 2,797,472 bytes, `ota_1@0x420000`. Es la referencia recuperable. Las pruebas no cambiaron particiones, bootloader o eFuses.

M: SHA256 `532115adda0c4163eeb077721c88003a693d5539ac54cda9e40c819378a104ac`;9 muestras/40.8s. Optimización de setters LVGL redundantes; resultado insuficiente para estabilidad30 FPS.

N2: SHA256 `acc0ff4b0ae2aee1b14dc80d7872869fcd4f63f29e9f7fd6387c06866db2d680`;11 muestras/52.2s dentro de ensayo95s y rollback obligatorio. Prueba real18:39:33–18:42:58Z. Sin panic observado; retorno confirmado a 0.2.0. La cadencia28ms sigue siendo experimental.

N3a + rig: compilación local ESP-IDF6.0.1, 2,381,072 bytes, SHA256 `7bcd4a04d6990bf4b545c60694f527d46ef40fb1f9087222c2086fe0fa46c1ea`. Solicita despertar LVGL tras dibujar y añade ventanas de métricas; no fuerza refresco inmediato ni acredita mejora de FPS. Rig13capas,78,404bytes de texturas en flash; mismo targetRGB565 de36,992bytes. Neutral conserva todos los píxeles visibles fuera de ojos/boca. Uniones solapadas con píxeles del original evitan costuras durante el movimiento. **Instalado para prueba manual; sin promoción ni aceptación visual del usuario.** [Diseño y límites](decisions/2026-10-13-n3a-rig.md).

## Prueba manual N3a · 2026-10-14 UTC (13 oct local)

Solicitud expresa del usuario: dejar la versión nueva en CoreS3 para probarla. Procedimiento `physical-edge-trial-n3a.py`, SHA256 `68bf6ad436788f8d0c3f3baf0f32174f634a1a2bc6fe11a4139a5c1676f523d0`; 18 tests host PASS y revisión independiente final Grok/AGY PASS. La revisión encontró y corrigió antes del USB una ruta de error que podía ofrecer el baseline mientras N3a seguía vivo.

Se escribieron únicamente app `ota_0@0x20000` (2,381,072 bytes) y sector0 OTA `0x1d000` (4,096 bytes). Lectura posterior del candidato exacta; bootloader, tabla, NVS y baseline `ota_1` intactos antes del reset. Consola durante 45.151 s: un arranque 0.3.0-dev, sin panic/backtrace observado; ninguna reapertura USB tras el éxito. Telemetría fresca a 01:53:38Z: `boot_verified=true`, uptime de 90.09 s, heap interno de 40,523 bytes. Dos ventanas frescas, a 35 y 90 s de uptime: 23.278/23.833 FPS; **no cumple la aceptación de 30+ FPS** ni demuestra estabilidad sostenida.

Oferta firmada N3a compartida y descargas mTLS verificadas en ambos gateways. Mientras el candidato siga instalado, conservar su propia oferta para que OTA no sobrescriba la referencia recuperable. Rollback local preparado mediante checkpoint privado validado; no se ejecutó un retorno físico en esta sesión porque el usuario pidió dejar N3a. No hubo migración, eFuses, cambios de servicios ni gasto API. Pantalla, audio, gestos y 24 h permanecen por aceptar.

[Recibos públicos acotados](evidence/README.md). Los archivos privados y las instantáneas originales se conservan localmente; no son necesarios para consultar el estado ni deben subirse a GitHub.

## Lo que no está aceptado

- 30+FPS sostenidos y experiencia óptica/pupilas/gestos/SFX completa en hardware.
- Wake-word Sagwa genuino, producto comercial de OAuth/credenciales, migración de datos Edge.
- 24 h continuas del candidato final. La ventana0.2Docker quedó interrumpida y preservada; supervisor retirado y automatización pausada. Un reset accidental fue confirmado por el usuario; otra pérdida de telemetría TUF no tiene causa histórica demostrada.
- La causa del ruido de TUF. La observación posterior de voz con CPU/GPU bajas no demuestra qué ocurrió antes ni mide ventiladores acústicamente.
- Sincronización de actividad global de Muse; la restricción403 sigue siendo un límite.

## Continuar

Seguir [ROADMAP.md](ROADMAP.md), reclamar tarea y recurso en el [tablero](../coord/board.json), y leer el [handoff](../coord/handoffs/2026-10-14-codex-flash-01.md). No reiniciar ni flashear equipos para ponerse al día.

Consolidación publicada en GitHub: `terrerovgh/Sagwa`. Lectura y escritura Git verificadas con deploy key limitada al repositorio, privada solo Mac. 18 tests de desarrollo, 60 TypeScript/build y cuatro suites nativas con sanitizers pasaron; revisión independiente acotada PASS. Sin despliegue del producto por esta consolidación.
