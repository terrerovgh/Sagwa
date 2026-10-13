# ADR-0001 · Desarrollo por agentes y continuidad

Adoptado por instrucción del usuario13 oct 2026.

Problema: trabajo repartido en agentes/máquinas/recibos/conversaciones y guías antiguas con estados de preparación desactualizados.

Decisión: GitHub Sagwa contiene fuentes/documentación saneadas; AGENTS común. Herdr ofrece tabs/readiness/transporte. Tablero bajo flock, journal append-only, mensajes versionados, concesión de orquestador y bloqueos con propietario previenen colisiones de buena fe. Worktrees separan índices/código; registros compartidos en raíz principal.

Límites: no lock distribuido, ACL o identidad criptográfica de modelos. Misma cuenta Git implica acceso común y protocolo voluntario. Auth CLI independiente; infraestructura TUF mantiene_coord; producto mantiene autorizaciones AgentShell. No sincronizar claves/sesiones/logs privados.

Consecuencia: cualquier agente continúa por objetivo/estado/tablero/handoff; tests/revisión/despliegue/aceptación siguen separados. Concesión caducada solo recuperable después de comprobar parada anterior.
