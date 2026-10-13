# AgentShell

Estado canónico: [docs/STATUS.md](../docs/STATUS.md). Esta guía también contiene historia: M/N2 tuvieron pruebas app-only con retorno a0.2.0; N2 fue rechazado y ningún Edge está promovido.

Terminal independiente para M5Stack CoreS3 y coordinador privado de agentes. Interfaz, voz y mensajes de usuario en español. Las claves, certificados privados, Wi-Fi, modelos y copias completas de flash están excluidos de Git.

## Instalación actual

Sagwa **0.2.0** está instalada en el CoreS3. Véase [SAGWA-DEPLOY.md](SAGWA-DEPLOY.md) para evidencia de pantalla, audio, rollback y el estado de estabilidad. La reestructuración LVGL/ESP-SR/skins y router directo está en [edge-firmware](edge-firmware/README.md), versión **0.3.0-dev experimental, probada brevemente por etapas y sin promoción**. Los modelos dedicados de Docker Desktop se describen en [MAC-DOCKER.md](voice/MAC-DOCKER.md); consulte la evidencia de promoción antes de asumir que un candidato está instalado.

| Nodo | Servicios |
|---|---|
| `tuf-infra` | gateway, coordinador, ejecutor, objetos, etcd y voz; dentro del espacio de red Tailscale existente |
| Mac mini | gateway, ejecutor, objetos, etcd, voz y puente Muse; LaunchDaemons del sistema |
| `lenlab` | coordinador de recuperación, ejecutor, objetos, etcd, voz y puente restringido Hermes; systemd |
| MacBook Air M1 | acceso SSH verificado; incorporación como worker pendiente |

El Core usa WSS con certificados de dispositivo hacia `192.168.4.64:9443` y `192.168.4.82:9443`. Los servicios se comunican por Tailscale y mTLS. El relé Windows/WSL mantiene el Linux existente `infra`, propiedad de `tufinfra`. No se creó otra distribución. La tarea de arranque existente actualiza el relé al cambiar la IP de WSL.

Panel: `https://100.68.191.53:9443/`. Instalar la CA de aplicación de la configuración privada en el navegador que vaya a usarlo. El token administrativo se lee de `agentshell/.private/admin-token`; se introduce en el panel y permanece únicamente en memoria. Las reglas automáticas empiezan vacías; las reglas temporales de aceptación están desactivadas.

## Compilar

Node.js 24 LTS, pnpm y dependencias exactas en `package.json`/`pnpm-lock.yaml`:

```sh
cd agentshell
pnpm install --frozen-lockfile
pnpm build
pnpm test
```

Firmware ESP-IDF 6.0.1, M5Unified 0.2.24 y M5GFX 0.2.32:

```sh
source ./activar-muse.sh
cd agentshell/firmware
idf.py -B build -D AGENTSHELL_RELEASE_VERSION=0.2.0 build
idf.py -B build-repro -D AGENTSHELL_RELEASE_VERSION=0.2.0 build
shasum -a 256 build/agentshell.bin build-repro/agentshell.bin
```

`sdkconfig.defaults`, `dependencies.lock` y el manifiesto fijan configuración y componentes. `esp32-camera` se fijó en 2.1.8 por compatibilidad con IDF 6. La versión instalada es 0.2.0. `AGENTSHELL_TEST_BOOT_FAILURE` y `AGENTSHELL_RELEASE_VERSION` son opciones de compilación para ensayar rollback; no hay un comando remoto que active el fallo local.

La HAL del firmware instalado es la única propietaria de buses y periféricos. Sagwa 0.2.0 usa fondo negro, Inter blanco con acentos, avatar transparente, emoji de estado a la derecha y gestos de borde. Conserva captura PCM mono 16 kHz, cámara solo por petición, sensores y OTA firmada. PWR inicia voz al mantener, envía al soltar y detiene reproducción; las caricias nunca graban. Las autorizaciones, fotos y cancelaciones requieren confirmación. La descripción técnica y vistas están en [SAGWA-INTERFAZ.md](SAGWA-INTERFAZ.md) y `evidence/sagwa-v2/index.html`. Las credenciales se aprovisionan por USB:

```sh
python agentshell/scripts/core-usb.py provision
```

La configuración local de Wi-Fi está en `.private/wifi-import.json`; la contraseña nunca forma parte del firmware. Abrir el puerto USB reinicia esta placa: no usar el monitor USB durante la prueba de estabilidad.

## Protocolos y autorización

JSON v1 incluye `message_id`, `session_id`, `task_id`, `type`, `sequence` y `payload`. Los frames multimedia ASB1 llevan identidades y secuencia, con colas y límites acotados. Al reconectar se obtiene una instantánea; el audio de otra sesión o de una tarea cancelada se descarta.

MCP negocia las versiones compatibles del SDK 1.32.1, con versión preferida `2025-11-25`. A2A usa JSON-RPC 0.3.0. API administrativa: `/v1/tasks`, `/v1/nodes`, `/v1/agents`, `/v1/resources`, `/v1/artifacts`, `/v1/actions`, `/v1/approvals`, `/v1/policy/rules`, `/v1/control/handoff` y `/v1/firmware/*`. `/v1/tasks/<id>/changes` permite revisar el diff del worktree.

La política determina el riesgo en el servidor. Lecturas automáticas; cambios tipados sobre recursos exactos requieren una regla vigente o aprobación física. Las operaciones destructivas también requieren confirmación administrativa. Cada aprobación vincula hash, parámetros, destino y caducidad; se consume por CAS una sola vez. Las operaciones destructivas sin implementación tipada devuelven `unsupported`.

La concesión de autoridad dura 45 segundos y se renueva cada 5 segundos. Los ejecutores comprueban época y quórum, serializan por recurso y guardan los resultados por `action_id`. Una operación incierta no se repite automáticamente. La API de reconciliación comprueba el artefacto instalado y la salud antes de confirmar el resultado. TUF vuelve como standby; la devolución del control se solicita desde el panel.

Conversaciones, tareas y auditoría se guardan como objetos SHA-256 durante 30 días, con dos copias durables antes de confirmar. Firmware, descriptores y chunks de artefactos se conservan para recuperación. La poda se suspende cuando falta quórum. Los journals locales mantienen deduplicación; no se promete ejecución exactamente una vez.

## Integraciones

| Agente | Estado y contrato |
|---|---|
| Codex | App Server por stdio detrás de un broker durable; cambio real en worktree y sandbox comprobados |
| Muse | principal para todas las actividades; transporte Noise en macOS, delegación, diagnóstico tipado y foto solicitada, sin shell |
| Hermes | API nativa restringida a herramientas MCP; proveedor OpenRouter existente autorizado específicamente |
| OpenCode | cliente generado 1.19.0 y broker preparados; desactivado mientras no haya proveedor autenticado configurado |
| Claude | SDK oficial Anthropic 0.133.0; conversación por API con credencial compatible; desactivado |
| Grok API | Responses API, conversación sin herramientas de host; desactivado |
| Grok Bot | aplicación instalada en Mac mini; pendiente conectar un transporte compatible |

Solo Hermes tiene autorización específica para usar su proveedor de pago existente. Claude/Grok permanecen bloqueados aunque se omita `paid_api` en su configuración. No se cambia automáticamente a un proveedor de pago. Los adaptadores Claude/Grok actuales admiten conversación; no ejecutan cambios de código ni infraestructura.

## Operación y recuperación

`scripts/deploy-gateways.py` despliega código y dependencias conservando etcd y voz. `scripts/install-macos-boot.sh` instala los LaunchDaemons mediante sudo. `scripts/acceptance-ha.py --abrupt` congela únicamente el gateway AgentShell de TUF y restaura los servicios en `finally`; no apaga Windows ni los servicios de producción.

`scripts/publish-firmware.py` firma y replica una imagen; `--offer` la ofrece al Core. Dos particiones OTA de 4 MB, verificación RSA/hash, prueba local de arranque y rollback. La confirmación no necesita backend. Los eFuses no se modifican. Una oferta fallida se registra en NVS para evitar reintentos repetidos; una nueva oferta obtiene otro identificador.

Las copias USB de Muse y AgentShell contienen secretos: están en `.private/recovery` y en `/opt/agentshell/private/recovery` de Lenovo/TUF, con permisos privados. `scripts/replicate-recovery.py` verifica sus hashes. Para restaurar por USB, usar esptool con la imagen completa correspondiente; conservar siempre la tabla de particiones incluida en esa imagen. La vinculación original de Muse había caducado y se renovó desde su firmware original. El SDK Linux no se ejecuta como daemon en macOS: el puente implementa el transporte portable.

`scripts/soak.py` toma telemetría cada 30 segundos durante 24 horas. Registra uptime, heap y RSS de los gateways sin abrir USB ni llamar a modelos. El informe distingue prueba en curso, aprobada y fallida; no sustituye una prueba de carga de cámara/voz. Véase [ACEPTACION.md](ACEPTACION.md) para resultados y pendientes.

Para revisar los diez estados y las animaciones con el mismo compositor C++ y los mismos glifos de la pantalla:

```sh
python agentshell/scripts/preview-ui.py
```

La vista previa requiere un compilador C++17 y Pillow en el host. Genera `evidence/ui/states.png`, `animation.gif` y las cuadrículas ASCII, con texto ilustrativo. No modifica el dispositivo ni llama a servicios externos.

## Emoji mágico y decisiones

Esta sección documenta el selector contextual de versiones anteriores. Sagwa 0.2.0 conserva el personaje y usa un emoji fijo para el estado; no sustituye su mascota por figuras contextuales.

La pantalla principal de 0.1.13 muestra un emoji contextual, estado breve, texto de conversación y dos controles de 40 píxeles de alto. Mantener el botón de voz o PWR graba; soltar envía el audio, con límite de ocho segundos. Mientras se reproduce una respuesta, el mismo botón muestra «Detener voz» y no cancela la tarea. El botón «Menu» abre opciones visibles de agente, destino, actividad, cámara y cancelación. Se retiraron los cambios cíclicos ocultos y los seis botones pequeños de la pantalla principal.

`device.settings` y `device.refresh` actualizan agentes, disponibilidad de nodos y referencias de repositorios desde el coordinador, sin exponer rutas o credenciales. Los agentes desconectados se muestran desactivados. Automático refleja el router real para la actividad elegida; si no tiene un agente disponible, la pantalla ofrece «Elegir agente». Para código se selecciona un repositorio configurado, en lugar de enviar un nombre de equipo como si fuera un repositorio. Las selecciones se conservan durante la sesión y se muestran inmediatamente en el menú.

«Tomar foto» captura localmente y muestra una vista previa de 160×120 en PSRAM, con indicador visible durante la captura. Se envía únicamente al pulsar «Enviar foto» y si Muse está disponible; sin Muse se puede revisar, repetir y descartar la foto. La captura se serializa con el micrófono y detiene la reproducción. «Cancelar tarea» aparece activo solo durante una tarea y abre una confirmación independiente. Las autorizaciones requieren comenzar la pulsación dentro del botón y mantener 1,5 segundos; salir del botón reinicia la espera y la caducidad se comprueba localmente además del servidor. El texto largo tiene controles explícitos de anterior/siguiente, también durante una autorización.

`check-ui-controls.cpp` prueba el controlador utilizado por el firmware con coordenadas reales de sus botones, incluyendo soltar/arrastrar, PWR, límites de grabación, disponibilidad, cancelación y aprobación. `acceptance-device-settings.mjs` comprueba el intercambio WSS real sin crear tareas. Las vistas de `evidence/ui/minimal/` utilizan el compositor y fuente reales; son ilustrativas. La telemetría incluye página, selecciones, disponibilidad y número de interacciones para comprobar la respuesta al tacto.

El catálogo oficial contiene 3.988 entradas. Se prepararon 3.958 dibujos para visualización; las otras 30 entradas son componentes Unicode sin dibujo independiente en el CDN (indicadores regionales, marca de tecla, signos y un identificador privado). Se conservan en el catálogo con `renderable:false`. Las 881 animaciones oficiales se reproducen; los dibujos estáticos utilizan una transición de 300 ms, sin presentar esa transición como una animación oficial.

`build-noto-catalog.py` combina el catálogo de Google con nombres y palabras clave de CLDR 48 en español e inglés. `prepare-emoji-index.mjs` indexa todas las entradas con `Xenova/paraphrase-multilingual-MiniLM-L12-v2`, revisión `2c4055b12046f11709e9df2c122e59ffbdc2f900`, ONNX q8 local. El selector recupera candidatos de todo el catálogo; el modelo de decisión elige entre esos candidatos y solo puede devolver un identificador permitido. No tiene herramientas ni permisos de infraestructura.

El proveedor activo es OpenRouter y el modelo es `inception/mercury-decide:free`, mediante `/api/alpha/decisions`. Devuelve una decisión tipada entre hasta 20 candidatos recuperados del catálogo completo. Las pruebas reales en los tres hosts confirmaron decisiones remotas y coste informado de 0 USD; seis frases en español cubren té, café, software, copias, tristeza y bicicleta (`evidence/emoji-openrouter.json`). Las descripciones distinguen el significado de la conversación de palabras impresas en signos o botones.

El selector consulta `/api/v1/models?output_modalities=decisions` cada minuto y exige tarifas explícitas de cero en todos los campos publicados. El identificador gratuito está fijado; no se cambia a su versión de pago. Si cambia la tarifa, falta autenticación, se agota la cuota, la respuesta no pertenece a los candidatos o la llamada falla, continúa el selector local. Hay como máximo dos llamadas simultáneas, cinco segundos de espera por petición y un minuto de pausa tras un fallo. La caché conserva decisiones durante 30 minutos y vuelve a probar decisiones locales de respaldo después de un minuto. Las métricas son del proceso actual. La clave vive en archivos privados con permisos 0600, fuera del firmware, Git y el navegador. Solo se envían el fragmento conversacional y un contexto breve; el modelo no decide permisos ni ejecuta acciones. Jev tiene tarifa y no hace falta activarlo mientras funciona Mercury gratuito. El adaptador Vercel queda disponible como alternativa de configuración, desactivado; ambos proveedores no pueden habilitarse simultáneamente.

`install-emoji-runtime.py` instala modelo, índice, caché y voz en los tres hosts, conservando el proveedor configurado. `deploy-gateways.py --code-only` instala código, configuración y la credencial del proveedor antes de reiniciar los gateways. El Core descarga los sprites por HTTPS con su certificado, acepta únicamente las direcciones exactas de sus gateways y comprueba SHA-256, dimensiones y tamaño. El transporte usa deflate para reducir la latencia; la expansión está limitada al tamaño declarado. Los búferes visuales y de descompresión se alojan en PSRAM para conservar memoria interna para TLS. Mantiene tres sprites en RAM; la cola de descarga conserva la solicitud más reciente. Cancelar una tarea o empezar otro turno invalida las descargas anteriores. Las expresiones de estado incluidas en el firmware funcionan sin backend.

La voz se divide en un máximo de 16 fragmentos sin descartar palabras. `/tts/contextual` devuelve PCM y posiciones exactas de inicio; el gateway cambia el emoji mientras envía cada fragmento, con al menos 1,8 segundos entre cambios. El panel incluye búsqueda en Noto, vista previa y una prueba de visualización en el Core sin ejecutar un agente. Las APIs `/v1/emoji/catalog`, `/v1/emoji/preview` y `/v1/emoji/display` requieren autenticación administrativa.

Los fragmentos se clasifican en grupos de dos para que el límite de concurrencia no excluya los siguientes de la selección remota. `acceptance-emoji-cues.mjs --openrouter` confirmó tres decisiones remotas gratuitas, cambios a tetera/ordenador/disquete en el tiempo marcado por Piper y ninguna trama ni figura tardía después de cancelar. Esta prueba usa coordinación simulada; la entrega de sprites al Core se verifica aparte por telemetría y la percepción física de LCD/altavoz sigue pendiente de revisión humana.

`preview-ui.py` produce también `evidence/ui/context.png` y `context.gif` a partir de los mismos sprites RGB565 y compositor del firmware. Son vistas previas ilustrativas, no fotografías. Los créditos y las licencias están en `assets/noto/CREDITS.md` y `assets/noto/catalog/`.


Muse es el principal para todas las actividades automáticas. Véase [MUSE-PRINCIPAL.md](MUSE-PRINCIPAL.md) para el contrato de delegación, disponibilidad actual y pruebas pendientes.
