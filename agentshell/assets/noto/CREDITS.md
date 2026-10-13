# Animated Noto Emoji

Artwork and animations by **Google**, licensed under **Creative Commons Attribution 4.0 International (CC BY 4.0)**.

- Original collection and documentation: https://googlefonts.github.io/noto-emoji-files/
- License and disclaimer: https://creativecommons.org/licenses/by/4.0/
- Original CDN URLs and SHA-256 hashes: `manifest.json`.

AgentShell adaptations: resized, sampled to approximately 10 FPS, composited on a navy background, palette reduced to 128 colours and converted to RGB565. The original downloaded GIF files are included here. No endorsement by Google is implied. Attribution also appears on the terminal screen.

Regenerate with `python agentshell/scripts/export-noto.py` (Pillow required). Downloads are not performed during firmware compilation; the packed bytes and metadata are checked into the project.

The complete catalog and Spanish/English annotations are indexed locally. CLDR 48 annotations use the Unicode license (`catalog/UNICODE-LICENSE.txt`). Static Noto artwork is also distributed under Apache 2.0 (`catalog/APACHE-LICENSE.txt`); animated images are credited under CC BY 4.0. Google catalog technical components without a standalone drawing are marked unavailable.

The local multilingual encoder is `Xenova/paraphrase-multilingual-MiniLM-L12-v2` (Apache 2.0), revision `2c4055b12046f11709e9df2c122e59ffbdc2f900`; weights are provisioned privately and not embedded in firmware.
