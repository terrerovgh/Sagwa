# Operación y recuperación

## Acceso

Mac mini es el host del desarrollo. TUF Windows: `ssh terrerov@tuf-1`; validar host-key existente, leer `_coord/AGENTS.md` y registrar tarea/bloqueos antes de cambios remotos. El Linuxinfra existente no debe recrearse, importarse ni sustituirse. Una caída SSH requiere diagnóstico real y handoff, no cambio de cuenta Tailscale o VM por inferencia.

Los certificados, tokens, Wi-Fi, modelos, snapshots y claves permanecen en `agentshell/.private`, `.state` o ApplicationSupport/AgentShell del host, con permisos privados. Los agentes usan herramientas de operación que leen las referencias necesarias sin imprimir valores. No copiar credenciales al repo ni pegar sesiones OAuth.

## Salud sin interacción

```sh
curl -fsS http://127.0.0.1:9493/health
curl -fsS http://127.0.0.1:9450/health
/Applications/Docker.app/Contents/Resources/bin/docker stats --no-stream sagwa-core-s3-voice
```

Estas lecturas no sintetizan audio ni llaman API. El gateway mTLS usa sus helpers autenticados. Voz TUF está coordinada mediante concesiones GPU; no detener modelos/servicios ajenos para acelerar una prueba.

## Firmware

0.2.0 es baseline recuperable. Backups de flash contienen secretos: no publicar. Las pruebas app-only M/N2 escribieron únicamente app inactiva y metadatos OTA de prueba, tras revisión; rollback a 0.2 obligatorio. No usarlas para migrar la tabla. `physical-edge-trial*.py` no es una tarea de incorporación de agentes.

Antes de una prueba nueva: congelar artefacto/hash, revisión independiente, ventana autorizada, backup verificado y rollback concreto. USB monitor reinicia el Core. No modificar eFuses, secureboot, encryption, particiones o credenciales al abrir un entorno de desarrollo.

## Estabilidad y correo

No reiniciar la validación de24 h durante esta consolidación documental. Los registros previos se preservan; no son24 h válidas ni prueba de carga continua. Para reanudar hace falta candidato final revisado y nueva ventana sin USB/reinicios, con telemetría fresca y tendencias de memoria.

La consulta empresarial WakeNet ya fue enviada una vez. Guardar respuestas/latch en el espacio privado; comprobar antes de cualquier seguimiento. No reenviar por timeout o ausencia de respuesta aparente. No hay contrato/pago ni modelo recibido confirmado.

Los incidentes TUF/voz y recuperación ya completados no autorizan iniciar servicios compartidos detenidos. El ruido histórico sigue sin causa concluyente; no afirmar bucle basándose solo en ventiladores.
