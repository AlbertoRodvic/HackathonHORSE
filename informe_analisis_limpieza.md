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

Los resultados numéricos de este informe se han recalculado sobre los archivos actuales con el procedimiento de preparación y análisis del proyecto, sin aportar calendario de fábrica ni tabla de conexiones. La descripción corresponde a la versión actual de Streamlit, con objetivo de funcionamiento/TR del 90 %, clasificación por pérdida predominante, ciclo de referencia de 80 cmin/pieza y escenario provisional de 16 jornadas.

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

La banda de 1,2 minutos es una hipótesis compatible con cuatro campos redondeados a centésimas de hora; no certifica la corrección del dato. Se mantiene como valor predeterminado del procesamiento, pero se ha retirado su control de la barra lateral y no hay un filtro de balance en el mapa. El diagnóstico PDF conserva el balance y los registros diarios de la operación. La exploración también utiliza una tolerancia más amplia de seis minutos: con ella, 1.030 registros presentan discrepancias. Son dos criterios distintos y no se deben confundir sus recuentos.

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

**Objetivo de funcionamiento y clasificación.** El control principal de Streamlit es el objetivo de **funcionamiento sobre TR**, inicialmente del 90 %. No es la disponibilidad propia: `TBF/TR` incluye TAP, DES y SAT en el denominador, mientras que `TBF/(TBF + TAP)` excluye las esperas inducidas. El reparto sobre TR utiliza tiempo registrado; no supone que todas las jornadas tuvieran exactamente 22 horas planificadas.

El objetivo y el ciclo de referencia de 80 cmin/pieza son configurables. El umbral de significación de los mapas de recurrencia se calcula como `100 − objetivo de funcionamiento`, por lo que vale el 10 % con el objetivo inicial. El color de cada máquina depende del funcionamiento/TR y de la pérdida predominante, sin exigir otro umbral individual a TAP, DES o SAT. La clasificación se aplica en este orden:

1. Se revisan primero cobertura, coherencia y ausencia de datos o producción. Estos casos se agrupan como **Otros**, sin asignarles automáticamente una avería.
2. Para activar una señal TAP, DES o SAT se exige que `TBF/TR` sea **estrictamente inferior al objetivo**. Exactamente al 90 % no se activa ninguna señal de parada con el objetivo inicial.
3. Entre las operaciones bajo el objetivo se compara el tiempo perdido en TAP, DES y SAT. Si TAP es el mayor, incluido un empate, se asigna Parada propia y rojo. La disponibilidad propia se mantiene como indicador, pero no decide el color.
4. Si TAP no es el mayor, predomina DES en amarillo o SAT en naranja. Si la mayor de estas dos pérdidas es menor que 1,5 veces la otra, se consideran próximas y se muestran ambos colores, conservando el estado interno **Mixto** exclusivamente para la combinación DES/SAT.
5. Con funcionamiento/TR igual o superior al objetivo se presenta **Funcionamiento aceptable en verde**: Buen funcionamiento si el ciclo no supera el objetivo y Elemento lento si lo supera. La distinción de ciclo se consulta al desplegar Funcionamiento aceptable y no añade colores a la leyenda. Mixto tampoco tiene una entrada separada en la leyenda.

Con las 16 jornadas del escenario provisional, la clasificación del periodo es:

| Categoría | Operaciones |
| --- | ---: |
| Parada propia | 7 |
| Saturación | 11 |
| Desabastecimiento | 28 |
| Mixto | 10 |
| Buen funcionamiento | 22 |
| Elemento lento | 6 |
| Revisar datos | 5 |
| Sin producción | 2 |
| Sin datos | 0 |
| **Total** | **91** |

El resumen de líneas cuenta **56 máquinas con señales de parada**, una vez por operación, coincidiendo ahora con las operaciones elegibles bajo el objetivo. No suma las seis lentas ni los siete casos de datos o planificación como fallos. Las señales inducidas tampoco prueban una avería de la máquina que espera.

La gráfica de **Máquinas más problemáticas** reproduce el apartado 4 del notebook: filtra y dibuja **disponibilidad propia = TBF/(TBF + TAP) <90 %**, con cinco operaciones elegibles. El primer panel muestra ese porcentaje y el segundo desglosa sus horas TAP en rojo, DES en amarillo y SAT en naranja. DES y SAT quedan fuera del denominador de disponibilidad propia. La clasificación y el orden del mapa se mantienen basados en TBF/TR; sus 56 señales no son el número de barras de esta gráfica. Ambos indicadores se presentan con su nombre y denominador para evitar confundirlos.

**Frecuencia y duración de las interrupciones.** Contrastamos FPM con la duración media para distinguir muchas interrupciones breves de paradas prolongadas. En el módulo operativo, la señal de interrupciones frecuentes y breves combina una media inferior a dos minutos con FPM igual o superior al percentil 75 de la línea y contadores consistentes. En el escenario provisional aparecen 20 operaciones con esa señal agregada.

La nube de Streamlit representa **79 puntos para 91 operaciones**: un único agregado por operación y periodo, con producción y funcionamiento positivos, cobertura completa y duración media consistente. Los días y las semanas no se añaden como puntos independientes. El código comprueba la unicidad de línea y operación antes de dibujar. Los 20 puntos con indicios se listan de menor a mayor duración media; el tamaño de las burbujas representa horas de TAP.

Debajo de la nube se genera un texto a partir de los datos de la línea, con número de operaciones, TAP acumulado y hasta tres candidatas por grupo, priorizadas por TAP. La plantilla utiliza cuatro casuísticas:

| Casuística | Criterio sobre los puntos fiables | Línea de actuación |
| --- | --- | --- |
| Muchas paradas cortas | FPM ≥ P75 y media < 2 min | Contrastar eventos, sensores, alimentación y atascos repetidos. Priorizar el TAP acumulado. |
| Muchas paradas largas | FPM ≥ P75 y media ≥ 2 min | Revisar incidencias repetidas y tiempos de recuperación. |
| Pocas paradas cortas | FPM < P75 y media < 2 min | Mantener seguimiento y estandarizar ajustes; vigilar aumentos de frecuencia o TAP. |
| Pocas paradas largas | FPM < P75 y media ≥ 2 min | Revisar las incidencias de mayor duración y el procedimiento de recuperación. |

Las fronteras cambian con los umbrales configurados; «muchas» se refiere a paradas por pieza respecto al P75, no al número absoluto de eventos. «Largas» en esta plantilla significa superiores al umbral breve; no equivale a alcanzar el umbral de parada prolongada, inicialmente de 15 minutos. En estos datos ninguna media fiable alcanza 15 minutos, lo que no excluye eventos largos aislados.

`ST2235` acumula el mayor TAP entre las operaciones con indicios: 236,95 horas, unas 9.246 paradas por cada 1.000 piezas y una media de 0,040 minutos por parada. Estos valores justifican revisar sus registros y condiciones de funcionamiento. No confirman por sí solos un fallo de sensor, un atasco ni que sea el origen de pérdidas en otras operaciones.

El notebook también explora un umbral de un minuto. Son hipótesis de exploración distintas; los resultados deben acompañarse siempre del umbral empleado. Una media breve puede mezclar paradas cortas y largas, por lo que no confirma eventos individuales de microparada. Una incoherencia entre NAP y TAP impide usar esa media para clasificar con fiabilidad.

**Paradas totales y ciclo elevado.** Las operaciones sin producción se revisan por separado, para que no desaparezcan al exigir producción positiva en los indicadores. `PM2130` tiene TBF y producción iguales a cero, con **351,87 horas de TAP** en las 16 jornadas incluidas. Permanece en **Sin producción**, dentro de Otros, y se destaca al principio del mapa como parada total propia registrada. Debemos confirmar si debía trabajar antes de concluir que estuvo averiada durante todo ese tiempo. `ST_0030` también está en Sin producción, pero sus tiempos registrados son cero; no se presenta como una parada propia con TAP positivo. Si una operación registra piezas con TBF cero, pasa a Revisar datos.

Las operaciones con ciclo elevado y funcionamiento/TR aceptable se presentan como **Elemento lento** dentro de Funcionamiento aceptable y conservan el verde. Se contrastan con su producción, balance horario y posible funcionamiento en paralelo antes de interpretarlas como cuellos de botella.

**Relaciones entre operaciones.** La ficha de la operación compara señales propias con DES y SAT de otras operaciones en los mismos días. El desplegable permite filtrar desabastecimiento en otras operaciones, saturación en otras operaciones o posibles fuentes de espera de la seleccionada. No muestra la columna de distancia ni el sufijo «conexión por confirmar»; mantiene la explicación de que son coincidencias diarias sin causalidad demostrada. El selector para cargar conexiones se ha retirado de Streamlit. El orden configurado sirve para presentar operaciones y no se utiliza para inventar conexiones físicas. Las comparaciones exploratorias con días de control siguen disponibles en los módulos de análisis e informes, pero no constituyen una pestaña de pérdidas propias en la interfaz actual.

**Organización de la aplicación.** El mapa conserva cajas con el nombre de cada operación y permite ordenar por configuración o **Por urgencia de reparación**. Esta última opción agrupa por color en orden **TAP → SAT → DES → Mixto → Funcionamiento aceptable**, con los casos de datos aparte. Dentro de cada grupo ordena de **menor a mayor porcentaje TBF/TR**; Buen funcionamiento y Elemento lento se mezclan en el mismo grupo verde. Los empates se resuelven por orden configurado y nombre; los porcentajes no definidos quedan al final de su grupo. La gráfica de tiempos conserva la ordenación global por TBF/TR. El filtro de Otros permite desplegar Sin producción, Revisar datos y Sin datos, y Funcionamiento aceptable permite distinguir Buen funcionamiento y Elemento lento. Se ha retirado el selector intermedio de disponibilidad de datos.

El detalle de la operación seleccionada aparece inmediatamente después del botón de descarga de criterios de clasificación y colores. Los posibles efectos se muestran antes del botón de diagnóstico PDF. Los registros diarios, su balance y la explicación del color se consultan en ese PDF; no ocupan secciones adicionales de la ficha de Streamlit. También se ha retirado el mensaje que pedía seleccionar una operación y la descarga de indicadores de línea mostrados en la versión anterior.

**Revisión de datos**, con el desplegable Otros, aparece al final del mapa de operaciones, después de la ficha seleccionada y antes de Análisis de la línea.

El análisis de línea queda dividido en tres apartados:

| Apartado | Contenido actual |
| --- | --- |
| Microparadas | Nube con un punto por operación, recuentos explícitos, plantilla de acciones adaptada a la línea y lista de indicios por duración media creciente. |
| Máquinas más problemáticas | Gráfica de cinco máquinas comparables con disponibilidad propia TBF/(TBF + TAP) <90 %, con desglose TAP/DES/SAT, y mapas semanales de recurrencia. |
| Tiempos todas las máquinas | Reparto porcentual de TBF, TAP, DES y SAT por operación, ordenable por configuración o por porcentaje TBF/TR de menor a mayor, coincidiendo con las barras. |

Los mapas de recurrencia solo incluyen operaciones que alcancen el umbral de porcentaje significativo del tipo de pérdida en al menos una semana comparable bajo el objetivo de funcionamiento. Se han retirado la tabla posterior, el reparto diario de horas-máquina y los gráficos adicionales de frecuencia, ciclo y media de las prioritarias. La plantilla de cuatro casuísticas se conserva únicamente en Microparadas. Calendario y calidad y Pérdidas propias ya no son pestañas de Streamlit; la preparación, los escenarios, el calendario opcional y la trazabilidad se conservan en el procesamiento.

<!-- pagebreak -->

### 6. Qué aporta el trabajo y cómo continuar

El resultado es una base preparada y trazable, con indicadores por operación y periodo, señales de calidad, comparación de escenarios y vistas que distinguen pérdidas propias de esperas externas. La aplicación y los informes permiten revisar una prioridad y consultar los datos que la explican. La interfaz distingue explícitamente las señales de parada, las operaciones bajo el objetivo de funcionamiento y los casos de calidad o planificación; no presenta todos esos recuentos como averías.

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

Las fuentes de metodología son `initial_exploration.ipynb`, `cleaning.py`, `analysis.py` y `diagnostics.py`. La consulta visual se realiza mediante `app.py`; las tablas, gráficos e informes se generan con `run_analysis.py` y `reports.py`.

La versión descrita ha superado **56 pruebas automatizadas**, incluidas reglas de duplicados, claves conflictivas, cierres, paradas totales, unidades, balances, cálculo de ratios, orden de categorías, filtros y navegación. Las comprobaciones específicas verifican la pérdida predominante, la combinación exclusiva DES/SAT, la leyenda verde unificada, la ordenación por porcentaje TBF/TR, que la gráfica de Máquinas más problemáticas filtre y dibuje disponibilidad propia, que la nube tenga un único punto por operación, que los cuatro grupos de la plantilla no se solapen y que los mapas semanales excluyan operaciones sin porcentajes significativos.

Además se ha recorrido Streamlit con los CSV actuales para comprobar las 91 cajas del mapa, los 79 puntos de la nube, las cinco barras bajo el objetivo de disponibilidad propia, la ausencia de duplicación de esa gráfica, la ordenación por TBF y el diagnóstico de `PM2130`. Este informe no incorpora validación de causas por parte de planta.
