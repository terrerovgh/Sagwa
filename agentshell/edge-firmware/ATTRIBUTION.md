# Atribución de recursos

Inter, por Rasmus Andersson, SIL Open Font License 1.1: [proyecto](https://github.com/rsms/inter). La licencia está en `components/sagwa_edge/fonts/OFL.txt`. La fuente se convirtió a un subset LVGL de 16 px con caracteres españoles.

Emoji Noto por Google, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), [colección original](https://googlefonts.github.io/noto-emoji-files/). `badges.c` contiene el primer frame de nueve GIF originales ya guardados en `../assets/noto`, redimensionado a 28 px y compuesto en negro mediante `tools/export_badges.py`. Los hashes/URLs originales están en `../assets/noto/manifest.json`; cámara tiene su receipt en `reference/camera-emoji.json`.

Ronroneo: Peter Hull, [Cat purring](https://commons.wikimedia.org/wiki/File:Cat_purring.ogg), [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). `purr.pcm`: fragmento de 1.2 segundos, PCM mono 16 kHz, atenuación y fades; adaptación bajo la misma licencia.

Maullido: Dan Crosby / Dcrosby, gato Silas, [Meow](https://commons.wikimedia.org/wiki/File:Meow.ogg), [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). `meow.pcm`: fragmento de 0.8 segundos, PCM mono 16 kHz, atenuación y fades. `ack.pcm`: primeros 150 ms con fades de 10 ms; `complaint.pcm`: 450 ms derivados con velocidad/pitch 0.8 y ganancia 0.65. Estas tres adaptaciones conservan CC BY-SA 3.0. La variante grave es una señal de queja, no una grabación distinta del gato. No implican respaldo de sus autores ni son la voz de la gata real Sagwa.

BSP y ESP-IDF de Espressif, LVGL y cJSON conservan sus propias licencias en las dependencias fijadas y sus repositorios. Los sonidos y sus adaptaciones no cambian la licencia del código de aplicación por agregarlos a la imagen. El rig usa piezas transparentes nuevas generadas con ImageGen a partir de la referencia Sagwa autorizada por el usuario. Atlas, layout, hash y procedencia se conservan en `assets/sagwa-rig`; los vídeos originales de Muse no se incluyen como si fueran estos recursos nuevos.
