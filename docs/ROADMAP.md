# Hoja de ruta para el siguiente orquestador

El orden reduce dependencias y evita confundir preparación con aceptación. Los IDs están sembrados en `coord/board.json`; asignarlos a sesiones reales cuando comiencen.

| Tarea | Entrega / aceptación |
|---|---|
| S-101 · Fluidez | Investigar regresión N2 y contención UI/LVGL/DMA. Propuesta medible, sanitizers y revisión; hardware30+FPS sostenidos con SPI completado, sin degradar audio/gestos |
| S-102 · WakeNet | Esperar/obtener modelo genuino Sagwa por canal autorizado; licencia, hash, falsos positivos/negativos y latencia local. No enviar otro correo sin comprobar latch/respuesta |
| S-103 · Arte Sagwa | Integrar derivados Higgsfield conservando identidad, alfa negro, capas/FSM y offline fallback; medir PSRAM/tamaño y vistas completas |
| S-104 · Voz y cámaras | Pruebas Core PWR, stop/cancel, STT/TTS streaming, cambio host, música/SFX, fotos confirmadas y latencia por etapa; sin consumo API nuevo no reservado |
| S-105 · Clima físico | Comprobar oferta WSS, vencimiento/omisión y visualización real de Ray City; no reconfigurar ciudad |
| S-106 · Datos/seguridad | Diseñar migración compatible storage/model/vault, backup y rollback. Cambios irreversibles separados y autorizados; jamás quemar eFuses como un paso de build |
| S-107 · Release | Revisión de pantallas y voz por usuario, artefacto firmado, rollback real y24 h del candidato final, con aceptación y límites explícitos |

Prioridad actual: **S-101**. M fue mejor que N2 pero tampoco alcanzó todas las muestras≥30 FPS. Conservar ambos datos. N3 solo es una hipótesis; establecer presupuesto temporal/memoria/CPU y pruebas de contención antes de elegir una solución.

Preparación local posterior: N3a solicita wake del port tras dibujo, con métricas acotadas y cadencia28ms; rig Higgsfield13capas integrado. Build y galería host pasan; todavía no hay medición física N3a. S-201/S-203/S-204/S-205 registran esta entrega local, sin cerrar la aceptación física S-101 ni S-107.

Los trabajos de documentación/arte no deben abrir USB ni detener servicios. Las revisiones de infraestructura TUF siguen `_coord`; las entregas host pueden avanzar independientemente mientras falte WakeNet o revisión de hardware.
