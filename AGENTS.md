# Reglas comunes para todos los agentes de Sagwa

## Incorporación obligatoria

1. Leer `README.md`, `docs/OBJECTIVE.md`, `docs/STATUS.md`, `docs/ROADMAP.md`, `coord/README.md` y el handoff más reciente. Las guías técnicas históricas no sustituyen el estado actual.
2. Comprobar `git status`, rama, servicios y disponibilidad reales cuando la tarea dependa de ellos. No inferir autenticación de un ejecutable instalado.
3. Usar un ID único por sesión: `codex-ui-01`, `claude-audio-01`, `grok-review-01`, `agy-router-01`. Registrar familia, equipo y rol mediante `scripts/coord.py`.
4. Consultar tablero, inbox y últimos registros. Escribir un plan con criterio de aceptación **antes** de editar; registrar cambios, pruebas, errores y pendientes al entregar.

## Orquestación intercambiable

El usuario decide qué agente dirige. Cualquier familia registrada puede reclamar la concesión; solo puede existir una vigente. El orquestador descompone el objetivo, asigna recursos y revisores, integra entregas y mantiene el estado. Ser orquestador no amplía las autorizaciones del usuario. Muse principal del producto y orquestador de desarrollo son funciones distintas.

Hasta tres tareas de implementación simultáneas. Todos los agentes tienen el mismo acceso al repositorio bajo la cuenta autorizada del usuario; los roles organizan el trabajo, no son barreras de seguridad. No compartir tokens entre proveedores ni guardar credenciales en prompts, mensajes o bitácora.

## Trabajo y comunicaciones

- Reclamar una tarea asignada y los recursos afectados antes de cambiar archivos. Recursos sugeridos: `firmware-legacy`, `edge-ui`, `edge-audio`, `gateway`, `voice-mac`, `voice-tuf`, `assets-sagwa`, `device-usb`, `git-integration`.
- Los bloqueos son **locales y consultivos**. Los worktrees del mismo repositorio usan el tablero de la raíz principal. Otro clon/equipo no comparte bloqueos: debe trabajar en ramas independientes y coordinar el destino con su operador.
- Crear un worktree por tarea cuando haya edición concurrente. Usar rama `codex/<tarea>`, `claude/<tarea>`, `grok/<tarea>` o `agy/<tarea>`. Codex conserva su prefijo `codex/`. No resetear trabajo ajeno ni fusionar mientras otro agente edita la rama de integración.
- `coord/journal` es append-only. Cada registro declara hechos observables, decisiones o planes; nunca razonamiento privado del modelo. No reescribir registros anteriores para hacerlos parecer exitosos.
- Toda comunicación de trabajo relevante se registra con `message`; el destinatario responde indicando `--reply-to`. Herdr transporta avisos, el repositorio conserva el contenido. No considerar un mensaje entregado como trabajo completado.
- Entregar commit/hash, pruebas ejecutadas con alcance, limitaciones y handoff. Separar preparado, probado, desplegado y aceptado. Un PASS estático no certifica el hardware ni una ventana de 24 horas.
- Al terminar, liberar bloqueos, registrar resultado/handoff y marcar sesión inactiva. La concesión de orquestador se libera antes de que la asuma otro agente. Una caducidad requiere comprobar que el propietario dejó de trabajar; no autoriza robar recursos.

## Cambios y autorizaciones

R0: lectura/documentación. R1: código local reversible. R2: servicios, despliegue, USB o cambios de infraestructura; requieren revisión independiente de otra familia, artefacto exacto, alcance autorizado y reversión verificable. R3: irreversible, destructivo, gasto nuevo o ampliación de acceso; requiere autorización humana específica. Estas etiquetas ayudan a coordinar; no reemplazan las políticas del sistema o del equipo destino.

La autorización ya concedida en la sesión se conserva: no volver a pedirla por rutina. Una instrucción del usuario prevalece sobre esta guía. No enviar comunicaciones externas, comprar, contratar o usar proveedores de pago por iniciativa propia. La publicación de **este repositorio Sagwa** está autorizada; no implica publicar archivos privados ni enviar otro correo a Espressif.

Para TUF, leer además `C:\Users\terrerov\Projects\_coord\AGENTS.md`, registrarse allí y respetar sus bloqueos y revisión de infraestructura. El orquestador de Sagwa no sustituye a sysops en servicios compartidos. SSH autorizado: `ssh terrerov@tuf-1`.

## Invariantes actuales del producto

- Conservar CoreS3 0.2.0 como referencia recuperable. N2 no es candidato de publicación. No ejecutar `idf.py flash`, USB monitor, cambios de particiones, quemado eFuses o activación de servicios compartidos como parte de documentación/tests locales.
- Abrir el USB reinicia esta placa. Las pruebas físicas necesitan una ventana explícita y no se mezclan con una validación de estabilidad.
- Codec real: ES7210 micrófono y AW88298 altavoz; no ES8388. Un único BSP administra buses. Sensor sin dato fresco no produce reacción.
- WakeNet «Sagwa» no existe aún en el proyecto. No renombrar otra palabra ni presentar un detector simulado como verdadero.
- Claves de pago nunca en firmware sin el vault seguro requerido. No habilitar Flash Encryption/Secure Boot automáticamente. La configuración actual no acredita una migración de particiones.
- Presupuesto TTS API compartido US$5/mes: reserva antes de solicitar, tarifas verificables, bloqueo al agotar. No crear otro ledger o saldo.
- Mantener confirmación de fotos, cancelación y autorizaciones; sensores y animaciones no ejecutan comandos remotos.
- Preservar originales de Muse. Recursos nuevos de Higgsfield están identificados como derivados, todavía sin integración en firmware.

## Publicación

Antes de commit/push: revisar archivos staged, ejecutar `python3 scripts/check-publication.py`, pruebas pertinentes y comprobar que no hay privados/binaries de recuperación. No usar `git add .` sin inspección. Nunca eliminar evidencia para hacer pasar aceptación. No cambiar visibilidad, permisos GitHub o credenciales globales sin necesidad y autorización.
