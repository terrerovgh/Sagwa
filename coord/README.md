# Coordinación de desarrollo

`scripts/coord.py` funciona con Python3.9+, sin servicio ni credenciales. Usa `flock` y reemplazo atómico para evitar actualizaciones perdidas entre agentes del mismo Mac. Los worktrees resuelven la raíz común. **No es un lock distribuido ni una ACL**; GitHub comunica versiones, no bloquea equipos remotos.

## Incorporación y dirección

```sh
python3 scripts/coord.py --agent claude-audio-01 register --kind claude --role worker
python3 scripts/coord.py --agent claude-audio-01 status
python3 scripts/coord.py --agent claude-audio-01 inbox
python3 scripts/coord.py --agent agy-orch-01 register --kind agy --role orchestrator
python3 scripts/coord.py --agent agy-orch-01 orchestrator claim --note 'Sesión autorizada por el usuario'
```

Cualquier familia registrada puede dirigir. La concesión dura hasta 2 h, renovada con el mismo `claim`. El propietario libera con `orchestrator release` y escribe handoff. Si caduca, verificar por Herdr/host que dejó de trabajar, ejecutar `orchestrator recover --confirm-stopped --note 'Evidencia de parada...'` y después reclamar. Una caducidad no autoriza robar trabajo activo.

## Ciclo de tarea

```sh
# Orquestador crea y asigna.
python3 scripts/coord.py --agent agy-orch-01 task create S-200 --title 'Mejorar render' --acceptance '30 FPS sostenidos, sin regresión audio' --risk R2
python3 scripts/coord.py --agent agy-orch-01 task assign S-200 --owner claude-audio-01
# Responsable declara plan, bloqueo y ejecución.
python3 scripts/coord.py --agent claude-audio-01 journal --kind plan --task S-200 --note 'Hipótesis, archivos, pruebas y rollback...'
python3 scripts/coord.py --agent claude-audio-01 lock acquire edge-ui --task S-200
python3 scripts/coord.py --agent claude-audio-01 task state S-200 --state in_progress
# Entrega exacta y alcance.
python3 scripts/coord.py --agent claude-audio-01 task state S-200 --state review --artifact SHA_DEL_COMMIT --note 'Tests y resultados; limitaciones...'
python3 scripts/coord.py --agent claude-audio-01 lock release edge-ui
# Otro agente registrado: otra familia para R2/R3.
python3 scripts/coord.py --agent grok-review-01 task review S-200 --artifact SHA_DEL_COMMIT --verdict pass --note 'Evidencia y alcance de revisión...'
python3 scripts/coord.py --agent agy-orch-01 task state S-200 --state done --note 'Criterios satisfechos; evidencia...'
```

`changes` deja abierta revisión; volver a `in_progress` invalida revisiones previas. Cierre exige último dictamen PASS para el artefacto, aceptación documentada y bloqueos liberados. Hasta3 tareas en `in_progress`. Una tarea bloqueada declara causa y siguiente acción, no se marca terminada. El PASS estático no acepta hardware pendiente.

## Bitácora y comunicaciones

```sh
python3 scripts/coord.py --agent claude-audio-01 journal --kind progress --task S-200 --note 'Hallazgo observable...'
python3 scripts/coord.py --agent claude-audio-01 message --to agy-orch-01 --task S-200 --note 'Entrega lista; commit y límites...'
python3 scripts/coord.py --agent agy-orch-01 inbox
python3 scripts/coord.py --agent agy-orch-01 message --to claude-audio-01 --task S-200 --reply-to UUID_RECIBIDO --note 'Recibido; siguiente paso...'
```

Cada evento: UUID, fechaUTC, agente, tarea, tipo y nota. Mensajes se conservan también en journal; `reply_to` enlaza comunicaciones. `inbox` no borra mensajes. Herdr transporta avisos; el registro conserva contenido. Enviar/leer no acredita ejecución. Nada de claves, prompts privados, fotos o correspondencia comercial en este repo público.

Handoff: `coord/handoffs/YYYY-MM-DD-<agente>.md`, plantilla en `templates/handoff.md`. Perfiles preparados pero no ejecutados se registran inactivos; no inventar modelos/trabajadores.

## Persistencia

| Ruta | Función | Git |
|---|---|---|
| `coord/board.json` | Agentes y tareas, actualizado bajo lock | Sí |
| `coord/journal/.../*.json` | Planes/resultados/decisiones/comunicaciones | Sí, append-only |
| `coord/messages/<destinatario>/*.json` | Bandeja persistente | Sí |
| `coord/handoffs`, `docs/decisions` | Continuidad y ADR | Sí |
| `.coord/runtime` | Concesión, resource locks y layout Herdr | No |

El orquestador versiona tablero/bitácora en la raíz bajo `git-integration`. Antes de checkout/pull, acordar pausa de escritura y revisar diff. No commits concurrentes sobre el mismo índice. Otro clon/rig no comparte locks; coordinar ramas y reglas del destino. Copiar runtime no crea una concesión distribuida.
