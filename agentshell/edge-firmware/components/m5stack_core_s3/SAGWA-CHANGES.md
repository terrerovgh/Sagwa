# CoreS3 BSP 4.1.0: correcciones locales

Fuente upstream Apache2.0 conservada. Con BSP_ERROR_CHECK=n se corrigen dos macros con tipo de retorno equivocado: PMU devuelve esp_err_t; IO expander devuelve handle/null. Comprobar handle del expansor antes de feature_enable evita llamar al driver con null. No se alteran buses, pines ni formatos del fabricante. Parche reproducible en ../../reference/bsp-4.1.0-error-return.patch. Esta copia local permite fallo controlado de cámara/audio y conserva los errores originales.

Se conserva también el handle IO creado por el BSP y se expone un getter prestado para métricas del callback SPI de finalización. No se crea otro bus/driver ni se cambia su propietario. El callback Sagwa conserva lv_display_flush_ready y reporta solo datos atómicos sin asignar memoria en ISR.

El BSP inicializa el único handle AXP2101 antes de arrancar tareas y lo presta a Sensor_Task. También se inicializa el expansor una sola vez antes de UI/Audio. Los cambios de voltaje y read/modify/write del registro LDO se agrupan con mutex del BSP. Se conservan los registros/pines del fabricante. IDF6.0.1 no rechaza de por sí dos handles a la misma dirección: el problema que se evita es la propiedad/duplicación y la carrera de lazy-init, sin atribuir un fallo de dirección no comprobado.
