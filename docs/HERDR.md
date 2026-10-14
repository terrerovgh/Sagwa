# Herdr para Sagwa

El modo de desarrollo elegido por el usuario es Herdr: **Codex dirige** y asigna trabajo a **Claude, Grok y AGY** cuando sus sesiones están disponibles. Un workspace dedicado tiene tabs **Orquestación, Codex, Claude, Grok, AGY**. Los roles siguen siendo intercambiables mediante entrega de la concesión; el tab expresa rol. Código/documentación comunes y worktrees por trabajo concurrente.

## Uso en esta Mac

CLI: `~/.local/bin/herdr`, versión observada 0.9.4, servidor existente 0.9.3 compatible; no reiniciado/actualizado. Abrir TUI y seleccionar workspace Sagwa:

```sh
export PATH="$HOME/.local/bin:$PATH"
herdr
```

En la pestaña **Codex vacía** del workspace Sagwa, raíz del proyecto:

```sh
python3 scripts/sagwa-herdr.py doctor
python3 scripts/sagwa-herdr.py setup
python3 scripts/sagwa-herdr.py start codex --role orchestrator
```

`setup` serializa llamadas concurrentes, crea una sola topología sin tomar foco y guarda IDs, socket/sesión y terminales retornados. Antes de reutilizar valida label e identidad/pertenencia de panes vivos. Al iniciar valida el cwd del destino: raíz, subdirectorio o worktree del mismo Git common-dir; un hermano trabajando en su worktree no bloquea el inicio. `resume-setup` completa tabs ausentes tras interrupción. Si fue cerrado un pane o cambió servidor, falla sin controlar otro terminal; recuperar el layout propio explícitamente.

`start` inicia **un** agente solo si existe su ejecutable; Herdr valida shell/readiness. Ejecute desde otra pestaña: el lanzador no puede ocupar el pane que intenta iniciar. Para el orquestador use Codex vacía; para un worker use otra pestaña disponible. Cada arranque tiene nombre único de sesión. Devuelve el comando `agent prompt` de incorporación, que se ejecuta después desde la pestaña de control. Login/trust/aprobaciones los resuelve el usuario en terminal; no se pulsan respuestas. Timeout no significa petición no entregada: inspeccionar antes de reenviar.

Setup/start exigen `HERDR_ENV=1`, no lo falsean. `doctor` permite lectura local fuera. Esta consolidación creó solo un workspace nuevo sin foco por autorización expresa, sin controlar el pane enfocado previo.

## Disponibilidad comprobada ·13 oct 2026

| Perfil | Mac mini | Login/modelo |
|---|---|---|
| Codex | CLI incluida en ChatGPT.app, 0.162.0-alpha.17.2 | Sesión ChatGPT confirmada con `codex login status` |
| AGY | ~/.local/bin/agy,1.3.3 | No comprobado |
| Claude | No encontrado en rutas comprobadas | Pendiente |
| Grok | No encontrado; sí se utilizó Grok enTUF anteriormente | Pendiente Mac |

Instalar/autenticar CLI faltantes por distribución oficial, sin copiar tokens entre agentes/TUF. Doctor vuelve a detectar disponibilidad; no sustituye proveedor o modelo. AccesoGitHub no autentica los proveedores.

Hooks opcionales (CLI local es autoridad):

```sh
herdr integration status
herdr integration install codex
herdr integration install claude
herdr integration install grok
herdr integration install antigravity-cli
```

Un hook no instala CLI ni demuestra login; puede modificar configuración del usuario. Revisar/backupear archivos existentes. Sin hook el estado puede quedarunknown: comprobar evidencia de trabajo.

## Orquestar

Registrar tarea/plan/mensaje en `coord.py`; iniciar worker disponible en tab/worktree. Usar nombres vivos únicos, no etiquetas de proveedor como identidad:

```sh
herdr agent prompt sagwa-claude 'Lee AGENTS.md y tu inbox. Atiende solo la tarea asignada; registra plan y entrega con commit/pruebas.' --wait --timeout 60000
herdr agent get sagwa-claude
herdr agent read sagwa-claude --source recent-unwrapped --lines 100
```

Idle no demuestra que terminaron subjobs. Mensaje/respuesta relevantes se conservan en `coord/messages`; resultado aparte en journal. No enviar mensajes externos ni responder aprobaciones del usuario. No parar server, matar Herdr, cerrar tabs ajenos, cambiar proveedores o borrar logs para resolver timeout. TUF tiene IDs/sesión propios: no reutilizar IDs Mac.

Acceso Git del proyecto: lectura/escritura verificada mediante llave dedicada a Sagwa, sin credenciales en Git. El checkout principal y sus worktrees comparten la configuración local; el login GitHub no autentica AGY/Claude/Grok.
