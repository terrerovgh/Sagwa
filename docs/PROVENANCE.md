# Procedencia y límites de redistribución

- Código propio de AgentShell/Sagwa se publica por instrucción del dueño del proyecto. No se ha añadido una licencia general de explotación al proyecto por iniciativa del agente.
- Muse Gadget SDK: upstream `facebookincubator/muse-gadget-sdk`, revisión fijada en `dependencies/muse-gadget-sdk/provenance.json`, Apache2.0 conservada; patch y overlay preservan cambios históricos. El checkout original con `.git` no se publica como gitlink accidental.
- BSP, LVGL, ESP-SR, fuentes Inter, Noto, modelos y SFX conservan manifests/licencias/atribuciones de origen. Ver `agentshell/assets/sagwa/ATTRIBUTION.md`, `agentshell/assets/noto/CREDITS.md` y `agentshell/edge-firmware/ATTRIBUTION.md`. Licencias distintas no se sustituyen por una licencia raíz.
- Imágenes derivadas de Sagwa: ImageGen previo y Higgsfield nuevo, con hashes/procedencia. Foto de referencia real y originales de Muse permanecen privados; no se han cambiado.
- Higgsfield saludo H264 es nuevo recurso derivado, no exportación de animaciones originales Muse. No garantiza transparencia o bucle perfecto; no está instalado.
- Pesos Chatterbox/Kokoro/Whisper/Qwen se descargan por herramientas/manifests y se conservan fuera de Git. No incluir cuentas, claves de proveedores, identidad SMTP o correos como documentación pública.

Este repositorio conserva fuentes/configuraciones necesarias, recursos pequeños compilados y evidencia resumida segura. Los builds, paquetes grandes de ensayo y backups se guardan localmente; hashes en el estado/historial permiten relacionarlos sin publicar datos privados.
