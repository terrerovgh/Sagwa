# Estado verificable · 2026-10-13

Este archivo es la entrada canónica de estado y prevalece sobre frases antiguas de preparación en guías/recibos. Las fechas siguientes son observaciones históricas UTC, no comprobaciones de salud en vivo.

| Área | Hecho observado | Pendiente / límite |
|---|---|---|
| CoreS3 | 0.2.0 restaurado y telemetría fresca a 18:54:56Z | Nueva aceptación física y 24 h válidas |
| Edge 0.3 | Código compilado, tests host y pruebas app-only G/H/I/J/M/N2 | Ningún Edge promovido; N2 rechazado |
| UI host | 33 pantallas,21 gestos y14clips; rig Higgsfield y respaldo pasan ASan/UBSan | No prueba óptica/táctil completa del release |
| Rendimiento M | 26.392–31.280 FPS, mediana31.189; máximo gap129.734 ms | No alcanza30 FPS en todas las muestras |
| Rendimiento N2 | 24.826–26.653 FPS, mediana25.242; máximo gap126.149 ms | Regresión; **no publicar** |
| Voz | TUF Chatterbox principal, Docker Mac Kokoro respaldo detrás de9450; promoción/reversión ensayadas | Nuevo Edge: aceptación acústica, interrupciones y latencias finales |
| Clima | NWS Ray City desplegado en ambos gateways a 18:15:51Z; smoke módulo instalado | Packet WSS y visualización física sin verificar |
| WakeNet | Consulta empresarial enviada una vez y aceptada por transporte SMTP | Modelo «Sagwa» todavía no recibido; inbox del destinatario no demostrado |
| Higgsfield | Rig nativo13capas derivado de idle, integrado y compilado localmente; originales12poses y saludo preservados | Aprobación visual del usuario y hardware pendientes; saludo sin integrar |
| Desarrollo | Claude Opus5.5, Grok4.7 High y AGY Gemini3.8 Flash High participaron desde Herdr; coordinación persistente | Dictámenes locales no sustituyen aceptación del producto |

## Versión instalada y candidatos

0.2.0: SHA256 `88e9c70d2b1f521c48f928e146aa442a94b403ddb6227f94db2043fa3a9231ba`, 2,797,472 bytes, `ota_1@0x420000`. Es la referencia recuperable. Las pruebas no cambiaron particiones, bootloader o eFuses.

M: SHA256 `532115adda0c4163eeb077721c88003a693d5539ac54cda9e40c819378a104ac`;9 muestras/40.8s. Optimización de setters LVGL redundantes; resultado insuficiente para estabilidad30 FPS.

N2: SHA256 `acc0ff4b0ae2aee1b14dc80d7872869fcd4f63f29e9f7fd6387c06866db2d680`;11 muestras/52.2s dentro de ensayo95s y rollback obligatorio. Prueba real18:39:33–18:42:58Z. Sin panic observado; retorno confirmado a 0.2.0. La cadencia28ms sigue siendo experimental.

N3a + rig: compilación local ESP-IDF6.0.1, 2,381,072 bytes, SHA256 `7bcd4a04d6990bf4b545c60694f527d46ef40fb1f9087222c2086fe0fa46c1ea`. Solicita despertar LVGL tras dibujar y añade ventanas de métricas; no fuerza refresco inmediato ni acredita mejora de FPS. Rig13capas,78,404bytes de texturas en flash; mismo targetRGB565 de36,992bytes. Neutral conserva todos los píxeles visibles fuera de ojos/boca. Uniones solapadas con píxeles del original evitan costuras durante el movimiento. **Sin flash, ensayo físico, promoción o aceptación visual del usuario.** [Diseño y límites](decisions/2026-10-13-n3a-rig.md).

[Recibos públicos acotados](evidence/README.md). Los archivos privados y las instantáneas originales se conservan localmente; no son necesarios para consultar el estado ni deben subirse a GitHub.

## Lo que no está aceptado

- 30+FPS sostenidos y experiencia óptica/pupilas/gestos/SFX completa en hardware.
- Wake-word Sagwa genuino, producto comercial de OAuth/credenciales, migración de datos Edge.
- 24 h continuas del candidato final. La ventana0.2Docker quedó interrumpida y preservada; supervisor retirado y automatización pausada. Un reset accidental fue confirmado por el usuario; otra pérdida de telemetría TUF no tiene causa histórica demostrada.
- La causa del ruido de TUF. La observación posterior de voz con CPU/GPU bajas no demuestra qué ocurrió antes ni mide ventiladores acústicamente.
- Sincronización de actividad global de Muse; la restricción403 sigue siendo un límite.

## Continuar

Seguir [ROADMAP.md](ROADMAP.md), reclamar tarea y recurso en el [tablero](../coord/board.json), y leer el [handoff](../coord/handoffs/2026-10-14-codex-integrate-02.md). No reiniciar ni flashear equipos para ponerse al día.

Consolidación publicada en GitHub: `terrerovgh/Sagwa`. Lectura y escritura Git verificadas con deploy key limitada al repositorio, privada solo Mac. 18 tests de desarrollo, 60 TypeScript/build y cuatro suites nativas con sanitizers pasaron; revisión independiente acotada PASS. Sin despliegue del producto por esta consolidación.
