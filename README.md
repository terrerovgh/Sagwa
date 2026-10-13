# Sagwa · compañera Edge-AI para CoreS3

Sagwa es una mascota interactiva para M5Stack CoreS3: personaje felino sobre negro puro, texto breve en español, gestos, sensores y voz natural, con capacidades de Mac mini y TUF-1. Muse sigue siendo el agente principal del **producto**. El orquestador de **desarrollo** puede ser Codex, Claude, Grok o AGY.

**Estado al 13 de octubre de 2026:** CoreS3 con **0.2.0**; Edge **0.3.0-dev experimental**, sin promoción. N2 fue probado y rechazado por rendimiento; el dispositivo volvió a 0.2.0. La prueba válida de 24 horas y el modelo WakeNet «Sagwa» están pendientes. [Estado y evidencia](docs/STATUS.md).

N3a y el rig articulado Higgsfield están integrados y compilados localmente; la galería de producción y su respaldo pasan sanitizers. La mejora de fluidez y la aceptación visual/física siguen pendientes.

## Empezar como agente

Lea [AGENTS.md](AGENTS.md), [objetivo](docs/OBJECTIVE.md), [estado](docs/STATUS.md) y [coordinación](coord/README.md), en ese orden. La [historia](docs/HISTORY.md) explica las decisiones y pruebas anteriores; el [handoff actual](coord/handoffs/2026-10-13-baseline.md) permite continuar sin reconstruir conversaciones.

```sh
python3 scripts/sagwa-herdr.py doctor
python3 scripts/coord.py --agent mi-agente register --kind codex --role worker
python3 scripts/coord.py --agent mi-agente status
```

Dentro de Herdr, seleccionar Sagwa y usar la pestaña **Codex vacía** para iniciar el orquestador en la pestaña Orquestación:

```sh
python3 scripts/sagwa-herdr.py setup
python3 scripts/sagwa-herdr.py start codex --role orchestrator
```

El último comando muestra el prompt de incorporación que debe enviar al agente. Cambie `codex` por `claude`, `grok` o `agy` cuando su CLI y autenticación estén disponibles. No cambia el proveedor ni inicia cuatro trabajos automáticamente. [Guía de Herdr](docs/HERDR.md).

## Código y documentación

| Ruta | Contenido |
|---|---|
| `agentshell/firmware` | Firmware 0.2.0 del producto existente |
| `agentshell/edge-firmware` | Candidato 0.3.0-dev: LVGL, FSM, skins, plugins, router y audio |
| `agentshell/src`, `agentshell/test` | Gateways, coordinación de producto, permisos, clima y tests TypeScript |
| `agentshell/voice` | TTS/STT, Docker Mac, Chatterbox TUF, presupuesto y cancelación |
| `agentshell/assets` | Fuentes, emojis y recursos derivados de Sagwa con atribución |
| `agentshell/scripts` | Compilación, provisión, validación y despliegue del producto |
| `coord`, `scripts/coord.py` | Desarrollo por agentes: tareas, mensajes, bitácora y bloqueos |
| `dependencies/muse-gadget-sdk` | Referencia upstream fijada y cambios históricos preservados |
| `muse-life-service` | Experimento auxiliar de telemetría Muse, con acceso global todavía limitado |

[Compilar y probar](docs/DEVELOPMENT.md) · [Arquitectura](docs/ARCHITECTURE.md) · [Interfaces](docs/UI-CATALOG.md) · [Operación y recuperación](docs/OPERATIONS.md) · [Hoja de ruta](docs/ROADMAP.md).

El repositorio es público. Credenciales, sesiones de agentes, imágenes completas de flash, fotos de referencia, correo y evidencia operativa sin depurar permanecen locales y fuera de Git. Las pruebas resumidas aquí tienen alcance y fecha explícitos; no equivalen a una aceptación comercial. Las licencias de componentes y recursos se conservan en sus directorios; [procedencia](docs/PROVENANCE.md).
