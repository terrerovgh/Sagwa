# Compilación, pruebas y trabajo concurrente

Requisitos fijados: Python3.9+ para coordinación; Node24/pnpm para gateways; ESP-IDF6.0.1 esp32s3, LVGL9.4.0, BSP4.1.0 y ESP-SR2.6.0 para Edge. Los lockfiles y manifests son la fuente de versiones. No se necesitan claves para tests locales de coordinación.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/sagwa-herdr.py doctor
cd agentshell
pnpm install --frozen-lockfile
pnpm build
pnpm test
```

ESP-IDF: activar su `export.sh`; en la Mac existente se dispone de `source ./activar-muse.sh`. El helper acepta `SAGWA_IDF_EXPORT`/`SAGWA_TOOLS_BIN` para otros equipos.

```sh
idf.py -C agentshell/edge-firmware -B build/edge build
agentshell/edge-firmware/tests/run.sh
```

Para UI host: ver `agentshell/edge-firmware/tests/ui-host/CMakeLists.txt` y `agentshell/edge-firmware/README.md`; la dependencia LVGL debe estar descargada por Component Manager. Las vistas con reloj simulado pueden diferir aunque no cambie el personaje. Para0.2 use `agentshell/firmware` y su versión de release explícita. **Compilar no flashea, firma ni publica**.

## Worktrees

Esta Mac tiene una deploy key con lectura/escritura **solo Sagwa**, compartida por las CLI bajo el usuario local. La privada permanece en Application Support/AgentShell, fuera de Git. El checkout principal ya está configurado; los worktrees comparten configuración. En un clon nuevo de esta misma Mac:

```sh
python3 scripts/setup-git-access.py
git ls-remote origin
```

El helper comprueba origin exacto y usa la llave existente sin leer sus bytes. Escribe un archivo SSH privado, exige validación estricta con el archivo de host-keys oficiales preparado anteriormente y modifica config local/pushurl. No crea claves, cambia permisos GitHub o copia credenciales a otro equipo. El acceso Git no incluye login de proveedores ni funciones administrativas de GitHub.

El checkout principal guarda tablero/bitácora compartidos. Ejecutar `coord.py` desde un worktree resuelve el Git common-dir hasta esa raíz. No incluir el directorio `.coord/runtime` en Git.

```sh
git worktree add ../Sagwa-ui -b codex/ui-fluidez
```

Crear ramas desde la revisión de integración acordada; workers hacen commits solo de su código y entregan SHA. El orquestador integra bajo `git-integration`, revisa conflictos y versiona tablero/bitácora desde la raíz. Otro clon no tiene el mismo lockfile: la coordinación remota se resuelve por asignación/ramas y las reglas del destino.

Antes de subir:

```sh
git diff --cached --stat
python3 scripts/check-publication.py
```

El guard comprueba blobs staged y evita imprimir valores detectados. Es una comprobación adicional; inspeccionar nombres y configuración sigue siendo responsabilidad del agente. No guarda GitHub/API keys, correo, NVS o flash completa en el repo.
