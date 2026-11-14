# Informe de análisis y limpieza de datos
## Proyecto LOSSIA · Línea de montaje VLL_MONTAJE_L5

**Fecha de elaboración:** 14 de noviembre de 2026  
**Periodo analizado:** semanas 40 a 43 de 2026, días codificados del 1 al 5 de cada semana.  
**Finalidad:** explicar el enfoque del equipo, el procedimiento aplicado y las decisiones que condicionan la interpretación de los resultados.

### 1. Objetivo y enfoque del trabajo

Nos hemos centrado en identificar dónde se acumulan las pérdidas de tiempo y qué operaciones conviene investigar primero. Para ello, hemos separado las paradas propias de cada operación de las esperas que pueden depender del funcionamiento del resto de la línea.

La pregunta que guía el análisis es: **durante el tiempo en que estaba previsto producir, dónde se pierde capacidad y qué evidencia justifica una investigación?** La operación que más tiempo permanece detenida no tiene por qué ser la que origina el problema.

Hemos trabajado sobre dos fuentes: `datos_hackaton.csv`, con registros diarios de producción y paradas, y `config_hackaton.csv`, con el catálogo de operaciones y su orden configurado. La unidad de análisis es una combinación de línea, operación, año, semana y día.

| Alcance comprobado | Resultado |
| --- | --- |
| Registros de producción | 1.820 |
| Líneas incluidas | 1: VLL_MONTAJE_L5 |
| Operaciones en datos y configuración | 91 |
| Jornadas registradas | 20, repartidas en cuatro semanas |
| Cobertura del catálogo | Las 91 operaciones aparecen en las 20 jornadas |

### 2. Cómo hemos elaborado el análisis

El trabajo combina exploración, preparación de datos y cálculo de indicadores. El notebook `initial_exploration.ipynb` documenta las preguntas, las comprobaciones y las hipótesis. Los módulos `cleaning.py` y `analysis.py` convierten esas comprobaciones en un procedimiento reutilizable. La aplicación y los informes permiten consultar los resultados y volver al registro que los sustenta.

La secuencia seguida ha sido:

1. Revisar la estructura, los tipos de datos, las unidades y la correspondencia con el catálogo.
2. Buscar duplicados, valores inválidos y combinaciones incoherentes de tiempos y contadores.
3. Estudiar el balance diario de tiempos y los días sin actividad de toda la línea.
4. Comparar escenarios de calendario antes de interpretar los indicadores.
5. Agrupar por operación y periodo, distinguir tipos de pérdida y priorizar comprobaciones.

Los resultados numéricos de este informe se han recalculado sobre los archivos actuales con el procedimiento de preparación y análisis del proyecto, sin aportar calendario de fábrica ni tabla de conexiones.

<!-- pagebreak -->

### 3. Limpieza: qué hemos comprobado y cómo lo tratamos

Hemos planteado la limpieza como una preparación auditable. Conservamos los archivos originales y distinguimos entre registros que no se pueden utilizar, señales que requieren revisión y exclusiones que dependen del escenario elegido.

**Estructura e identificadores.** Eliminamos espacios exteriores en cabeceras e identificadores, comprobamos las columnas obligatorias y convertimos a numérico los campos de tiempos, contadores y periodo. Conservamos guiones, guiones bajos y sufijos en los nombres de las operaciones: su formato no permite deducir que dos códigos representen la misma máquina.

**Duplicados y validez.** El procedimiento retira únicamente copias idénticas. Si existen varias filas diferentes para una misma clave diaria, las aparta para revisión, sin sumarlas arbitrariamente. También aparta claves inválidas, valores ausentes o no finitos, cantidades negativas, contadores no enteros y operaciones sin correspondencia en configuración.

En los datos actuales no hemos encontrado valores ausentes en las columnas de origen, copias idénticas ni registros que activen estas reglas de exclusión: **los 1.820 registros son utilizables estructuralmente**. Esto no significa que todos sean coherentes desde el punto de vista operativo.

**Coherencia entre producción, funcionamiento y paradas.** Hemos creado señales específicas para localizar las siguientes situaciones:

| Comprobación | Registros en el conjunto completo |
| --- | --- |
| Producción sin funcionamiento: NPR > 0 y TBF = 0 | 4 |
| Funcionamiento sin producción: TBF > 0 y NPR = 0 | 65 |
| Paradas contadas sin tiempo propio: NAP > 0 y TAP = 0 | 16 |
| Tiempo propio sin paradas contadas: TAP > 0 y NAP = 0 | 364 |

Estas señales pueden solaparse y no equivalen a errores confirmados. Por ejemplo, el tiempo de parada sin incidencias contadas puede corresponder a un cierre o a una parada iniciada previamente. Por ello, conservamos los valores y señalamos los casos para contrastarlos con el registro de planta.

**Unidades y trazabilidad.** En esta ejecución hemos tratado TBF, TAP, DES y SAT como horas, conforme a la configuración del proyecto. El procedimiento admite conversión desde minutos o segundos. Cada registro preparado conserva una referencia a su fila de origen. Los valores no definidos por denominador cero se mantienen como tales, sin sustituirlos por cero.

No hemos completado tiempos para forzar una jornada de 22 horas ni imputado producción o paradas inexistentes. Tampoco hemos eliminado una fila únicamente por tener TBF igual a cero: podría representar una parada total relevante.

<!-- pagebreak -->

### 4. Calendario y balance de tiempos: decisiones que cambian el análisis

**Días sin actividad de toda la línea.** Hemos localizado cuatro jornadas con cobertura completa de operaciones, sin funcionamiento ni producción: `2026-S40-D1`, `2026-S41-D5`, `2026-S42-D1` y `2026-S42-D5`. Sus 364 registros contienen 22 horas de TAP y ninguna parada contada. Coinciden con los 364 casos de tiempo propio sin paradas contadas del conjunto completo.

No disponemos de un calendario de fábrica que confirme la causa. Las etiquetamos como **sin actividad, pendientes de confirmar**. El escenario exploratorio las excluye provisionalmente; permanecen disponibles en el conjunto preparado. Si se aporta un calendario que indique producción prevista, se conservan aunque toda la línea estuviera parada.

| Escenario | Jornadas | Registros | Mediana de disponibilidad propia* |
| --- | --- | --- | --- |
| Todos los registros utilizables | 20 | 1.820 | 76,19 % |
| Excluir solo cierres confirmados | 20 | 1.820 | 76,19 % |
| Excluir también días sin actividad por confirmar | 16 | 1.456 | 98,37 % |

*Mediana sobre las 84 operaciones elegibles en ambos escenarios: cobertura completa, funcionamiento y producción positivos y sin producción registrada sin funcionamiento. No es la disponibilidad global de la línea.*

La diferencia muestra que la planificación condiciona fuertemente la evaluación. Sin confirmar si había que producir, un cierre registrado como TAP puede hacer parecer poco fiable a una operación. Por eso, las prioridades del escenario de 16 jornadas son provisionales. Excluir solo cierres confirmados no cambia los datos porque no hemos aportado calendario.

**Balance diario.** Hemos comparado `TBF + TAP + DES + SAT` con una referencia configurable de 22 horas. Con una banda de ±1,2 minutos, el conjunto completo se distribuye así:

| Etiqueta de balance | Registros |
| --- | --- |
| Exacto o compatible con redondeo | 722 |
| Déficit de tiempo | 919 |
| Exceso de tiempo | 163 |
| Sin tiempo asignado | 16 |

La banda de 1,2 minutos es una hipótesis compatible con cuatro campos redondeados a centésimas de hora; no certifica la corrección del dato. La exploración también utiliza una tolerancia más amplia de seis minutos: con ella, 1.030 registros presentan discrepancias. Son dos criterios distintos y no se deben confundir sus recuentos.

Los 16 registros sin tiempo asignado corresponden a `ST_0030`. Debemos confirmar si esa operación estaba fuera de servicio o si falta información. Los déficits y excesos se conservan y se cuentan diariamente para evitar que se compensen al agregar. No atribuimos el tiempo que falta a microparadas sin evidencia adicional.

<!-- pagebreak -->

### 5. En qué hemos centrado el análisis operativo

**Paradas propias frente a esperas inducidas.** TBF representa tiempo de funcionamiento; TAP, parada propia; DES, desabastecimiento; y SAT, saturación. Consideramos `TAI = DES + SAT` como tiempo de espera inducida. Esta separación orienta actuaciones diferentes: revisión de la propia operación o investigación del flujo, suministro y evacuación de piezas.

**Indicadores comparables.** Sumamos primero los tiempos y contadores de cada operación y periodo y calculamos después los ratios. Así evitamos dar el mismo peso a jornadas con exposiciones muy distintas.

| Indicador | Cálculo e interpretación |
| --- | --- |
| Disponibilidad propia | 100 × TBF / (TBF + TAP). Excluye DES y SAT del denominador. |
| Peso de cada tiempo | 100 × tiempo / TR, siendo TR = TBF + TAP + DES + SAT registrados. |
| Frecuencia de parada, FPM | 1.000 × NAP / NPR: paradas por cada mil piezas de la operación. |
| Duración media de parada | 60 × TAP / NAP: minutos por parada contada. |
| Ciclo de funcionamiento | 6.000 × TBF / NPR: centésimas de minuto por pieza. |
| Recurrencia | Semanas evaluables en las que se repiten señales propias, DES o SAT. |

Usamos como referencias iniciales una disponibilidad del 90 %, un ciclo de 80 cmin/pieza y un umbral de pérdidas del 10 % sobre TR. Son parámetros configurables. El reparto sobre TR utiliza tiempo registrado; no supone que todas las jornadas tuvieran exactamente 22 horas planificadas.

**Frecuencia y duración de las interrupciones.** Contrastamos FPM con la duración media para distinguir muchas interrupciones breves de paradas prolongadas. En el módulo operativo, la señal de interrupciones frecuentes y breves combina una media inferior a dos minutos con FPM igual o superior al percentil 75 de la línea y contadores consistentes. En el escenario provisional aparecen 20 operaciones con esa señal agregada.

El notebook también explora un umbral de un minuto. Son hipótesis de exploración distintas; los resultados deben acompañarse siempre del umbral empleado. Una media breve puede mezclar paradas cortas y largas, por lo que no confirma eventos individuales de microparada. Una incoherencia entre NAP y TAP impide usar esa media para clasificar con fiabilidad.

**Paradas totales y ciclo elevado.** Las operaciones sin producción se revisan por separado, para que no desaparezcan al exigir producción positiva en los indicadores. Las operaciones con ciclo elevado se contrastan con su producción, balance horario y posible funcionamiento en paralelo antes de interpretarlas como cuellos de botella.

**Relaciones entre operaciones.** Comparamos señales propias con DES y SAT de otras operaciones. Cuando hay suficientes días con y sin señal, contrastamos ambos grupos y exploramos asociaciones. El orden configurado sirve para presentar operaciones; no demuestra conexiones físicas ni propagación. Sin eventos temporales y topología validada, las coincidencias generan hipótesis de investigación.

<!-- pagebreak -->

### 6. Qué aporta el trabajo y cómo continuar

El resultado es una base preparada y trazable, con indicadores por operación y periodo, señales de calidad, comparación de escenarios y vistas que distinguen pérdidas propias de esperas externas. La aplicación, los CSV y los informes permiten revisar una prioridad y consultar los datos que la explican.

Los principales aprendizajes son:

1. **El calendario es decisivo.** Los cuatro días sin actividad cambian sustancialmente la disponibilidad observada. Confirmar su planificación es previo a cerrar un diagnóstico.
2. **La calidad de datos necesita una revisión propia.** No encontrar duplicados ni valores ausentes no elimina las incoherencias entre tiempos, contadores y producción.
3. **Las pérdidas requieren respuestas distintas.** TAP, DES y SAT ayudan a orientar la investigación hacia mantenimiento, suministro o flujo de materiales.
4. **Un único indicador no basta.** Frecuencia, duración, ciclo, cobertura y recurrencia aportan información complementaria para ordenar la revisión.
5. **La priorización es explicable, pero provisional.** Los agregados diarios permiten localizar candidatas; no prueban qué máquina originó una pérdida en el resto de la línea.

### 7. Validaciones pendientes

La siguiente fase debe centrarse en contrastar la información con el contexto de planta:

- Aportar el calendario de fábrica y confirmar qué operaciones debían trabajar cada jornada, incluidos cierres, turnos especiales y cambios de planificación.
- Revisar los cuatro casos de producción sin funcionamiento, los 65 de funcionamiento sin producción y los 16 de paradas contadas sin tiempo propio.
- Confirmar la situación de `ST_0030` y explicar los déficits y excesos de balance antes de interpretar esos tiempos como pérdidas recuperables.
- Validar unidades, significado de NAP y NPR y objetivos de ciclo según operación, producto y posibles ramas paralelas.
- Incorporar conexiones reales, información de buffers y registros de eventos con hora de inicio, fin y causa para estudiar propagación y averías concretas.
- Tras una intervención, comparar TAP/TR, FPM y recurrencia en periodos con carga, planificación y producto comparables.

Con cuatro semanas de datos diarios no podemos confirmar causalidad, identificar todas las averías repetidas ni prometer predicción de fallos. Tampoco sumamos las piezas de todas las operaciones como producción final de línea, ni equiparamos las horas de espera de varias máquinas con horas de producción recuperables.

### 8. Documentación y reproducibilidad

| Elemento del proyecto | Función en el trabajo |
| --- | --- |
| initial_exploration.ipynb | Exploración, hipótesis y comprobaciones detalladas. |
| cleaning.py | Preparación, trazabilidad, señales de calidad y escenarios de calendario. |
| analysis.py y diagnostics.py | Indicadores, clasificación y comprobaciones operativas. |
| app.py | Consulta visual y revisión de operaciones y periodos. |
| run_analysis.py y reports.py | Generación de tablas, gráficos e informes. |

El procedimiento cuenta con pruebas automatizadas para reglas como duplicados, claves conflictivas, cierres, paradas totales, unidades, balances y cálculo de ratios. Este informe se ha elaborado revisando el código y recalculando los recuentos sobre los CSV actuales; no incorpora validación de causas por parte de planta.
