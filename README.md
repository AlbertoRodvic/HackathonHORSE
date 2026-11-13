# 🏭 Reto LOSSIA: Detección Inteligente de Máquinas Penalizantes

## 🎯 El reto

En la línea 5 de montaje de Valladolid, no todas las paradas son iguales. El objetivo de este proyecto es transformar los datos brutos de producción en un análisis end-to-end que permita al jefe de taller identificar rápidamente la causa real de las pérdidas de tiempo.

La solución distingue entre:

- **Parada propia (TAP):** la máquina falla por sí sola.
- **Parada inducida (TAI):** provocada por desabastecimiento (DES) o saturación (SAT) derivados de otras máquinas.

El objetivo no es penalizar a la máquina que más se detiene, sino identificar la que genera un efecto dominó en el resto de la línea.

**Criterio clave de priorización:** las máquinas paradas que no están en situación de DES ni de SAT son las más problemáticas. Al no estar su parada explicada por desabastecimiento o saturación, deben investigarse como posibles fallos propios.

## 📊 KPIs y métricas principales

El modelo calcula automáticamente los indicadores de referencia para cada operación:

| Indicador | Descripción | Objetivo o cálculo |
| --- | --- | --- |
| **Disponibilidad (Dp)** | Porcentaje de tiempo productivo. | `>= 90 %` |
| **Tiempo de Ciclo (Tcy)** | Tiempo que tarda la operación en producir una pieza, en centésimas de minuto. | `<= 80 cmin` |
| **Frecuencia de Parada (Fpm)** | Número de paradas por cada mil piezas reales producidas. | `(NAP / NPR) * 1000` |
| **Microparadas vs. averías** | Ratio para diferenciar atascos rápidos de averías graves. | `TAP / NAP` |

## 🔎 EDA: análisis exploratorio de datos

En este apartado recogeremos las consideraciones iniciales del análisis exploratorio de datos antes de definir y validar el modelo.

### Consideraciones iniciales

- **Estructura y cobertura:** revisar el número de registros, las líneas, operaciones y periodos incluidos en los datos.
- **Calidad de datos:** identificar valores ausentes, duplicados, tipos incorrectos y valores fuera de rango.
- **Distribuciones:** explorar `TBF`, `TAP`, `DES`, `SAT`, `NAP` y `NPR` para detectar patrones y posibles anomalías.
- **Balance diario de tiempos:** sumar el tiempo de trabajo y el tiempo de parada de cada día y operación. Como referencia, el total esperado es de 22 horas; totales inferiores o superiores deben revisarse como posibles datos incompletos, duplicados o problemas de unidades.
- **Microparadas y paradas largas:** comparar la duración de las paradas con su frecuencia. Las paradas largas pueden presentar menos FPM y menos NAP; conviene analizar también la duración media por parada (`TAP / NAP`) para distinguirlas de muchas microparadas.
- **Relación entre ficheros:** comprobar que cada combinación de `Linea` y `Operacion` de los datos de producción tenga correspondencia en la configuración y un `Orden_OP` válido.
- **Agrupación por operación:** realizar los cálculos y comparaciones por `Operacion` (cada pieza/estación del proceso), además de por día cuando corresponda, para no mezclar máquinas distintas.
- **Paradas propias e inducidas:** analizar las máquinas paradas que no están en situación de DES ni de SAT, ya que son prioritarias para investigar como posibles fallos propios.
- **Evolución temporal y posición en línea:** comparar los indicadores por día y por `Orden_OP` para buscar concentraciones de paradas y señales de propagación entre operaciones vecinas.

### Observaciones del equipo

> Añadiremos aquí los hallazgos del EDA, las hipótesis que queramos comprobar y las decisiones que afecten a la limpieza o al análisis.

## 📝 Por hacer

1. **Registros señalados en el EDA:** revisar la tabla de registros con señal de revisión y contrastar sus valores con Excel. Hay valores contabilizados cuya precisión todavía no está confirmada. Interpretar también los rangos de valores de las tablas para distinguir microparadas de paradas largas.
2. **Columna de fecha:** crear una columna de fecha que sustituya a `Year`, `Week` y `Jour` para facilitar el análisis temporal.
3. **Días sin actividad y festivos:** investigar por qué hay días sin actividad. La revisión manual indica que no todos coinciden con festivos. Para escalar el análisis a otras líneas, países, ciudades y periodos, habrá que usar calendarios de festivos adecuados a cada lugar y año e incluir los festivos establecidos por convenio en el gremio correspondiente.
4. **Operaciones no registradas:** investigar por qué algunas operaciones de la cadena no aparecen en los datos, aunque sí formen parte del proceso.
5. **Tiempo medio por parada y clasificación:** añadir una columna calculada como `(TAP / NAP) * 60` para estimar el tiempo por parada. Usar como hipótesis inicial que las microparadas tienen un `NAP` muy alto y menos de 1–2 minutos por parada; las paradas largas o averías suelen tener un `NAP` bajo, un `TAP` total alto y más de 15 minutos por parada. Estos rangos son ejemplos que habrá que validar y ajustar por línea u operación.
6. **Agrupación por zonas de fábrica:** investigar si las operaciones de `config_hackaton.csv` se pueden agrupar en zonas para identificar en qué partes de la fábrica se concentran las máquinas problemáticas. Validar cualquier agrupación propuesta con información fiable de la línea.
7. **Frecuencia de microparadas:** comprobar si un FPM muy elevado identifica operaciones con muchas microparadas. Contrastar esta señal con la duración media por parada y definir umbrales con datos, ya que un FPM alto por sí solo no demuestra que sean microparadas.
8. **Esquema visual de la línea:** crear un diagrama en el orden real de producción y colorear tanto la operación que origina una señal como la operación afectada: rojo para quien provoca SAT y amarillo para quien la sufre; morado para quien provoca DES y verde para quien la sufre. Usar el esquema de direcciones SAT/DES de la presentación del reto como hipótesis inicial y validar las conexiones con la topología real. Definir el periodo, la media y los umbrales usados para asignar colores; permitir señales múltiples cuando corresponda.
9. **Análisis generalizable a otras líneas y periodos:** definir un método que incluya:
   - Calendario de producción y operaciones que debían trabajar.
   - TAP, DES y SAT como porcentaje del tiempo requerido, junto con disponibilidad, ciclo, frecuencia y duración media de las paradas.
   - Clasificación de patrones: pérdidas propias, desabastecimiento, saturación, problemas mixtos o ciclo elevado.
   - Objetivos configurables por línea u operación y comparación con periodos históricos equivalentes.
   - Priorización según magnitud de las pérdidas, recurrencia y confianza en los datos.
   - Recomendaciones explicables que distingan acciones de mantenimiento de problemas de flujo.
   - Análisis de propagación que contraste TAP con SAT aguas arriba y DES aguas abajo, usando conexiones reales y respetando ramas paralelas. Con acumulados diarios, presentar solo indicios; demostrar causalidad requiere eventos con marcas temporales.
   - Identificar primero las operaciones responsables de DES y SAT mediante la topología y las señales de propagación; después priorizar las máquinas por parada propia (TAP), para no confundir causas con operaciones afectadas.
10. **Operaciones lentas:** detectar operaciones con ciclo elevado que pueden tener un `NPR` bajo porque tardan mucho en producir, y distinguirlas de operaciones sin actividad o con falta de piezas.
11. **Picking, kitting y causas humanas o logísticas:** localizar esas actividades en la línea y comprobar si una falta o demora de preparación/suministro deja operaciones posteriores en DES; estudiar también si la acumulación de producto puede causar SAT en operaciones anteriores. Analizar como hipótesis si corregir fallos mecánicos aumenta el ritmo hasta el punto de saturar una operación manual y generar DES aguas abajo. No atribuirlo a una persona ni clasificarlo como avería de máquina sin evidencias adicionales; contrastar con incidencias de material, registros de picking/kitting y marcas temporales. La lógica de bloqueo y desabastecimiento depende del flujo y los buffers, así que debe validarse para cada conexión.
12. **Análisis semanal:** agregar los indicadores por semana para distinguir fallos puntuales de operaciones que fallan habitualmente y comparar también su comportamiento diario.
13. **Limpieza de los datos:** eliminar duplicados, aplicar `strip()` a los campos de texto para quitar espacios al inicio y al final, normalizar tipos y valores ausentes, validar rangos y unidades, y documentar las filas corregidas o descartadas.
14. **Disponibilidad y tiempo por pieza:** señalar operaciones por debajo del objetivo de disponibilidad del 90 % para investigarlas, sin asumir automáticamente que sean defectuosas. Crear una variable de tiempo por pieza a partir del tiempo de funcionamiento o del tiempo requerido y `NPR`, aclarar cuál representa el ciclo real, convertir las unidades y evaluar cómo ayuda a detectar operaciones lentas.
15. **EDA del Jupyter:** usar la nube de puntos del apartado 5 para analizar microparadas e incorporar el apartado 6 y sus conclusiones finales al análisis. El notebook no está actualmente en este repositorio, así que falta disponer de ese archivo para revisar e integrar sus resultados concretos.

## 🧠 Enfoque: algoritmo de propagación

Para resolver el reto de forma original y escalable, proponemos un algoritmo que recorre la topología de la línea usando el `Orden_OP` de la tabla de configuración.

Una máquina se considera una posible **máquina penalizante** cuando, durante un día de producción, se cumplen simultáneamente estas condiciones:

1. Está parada y no se encuentra en situación de DES ni de SAT; estas máquinas tienen prioridad de investigación.
2. Registra un tiempo alto de Parada Propia (TAP).
3. La propagación entre estaciones vecinas muestra Saturación (SAT) en la máquina inmediatamente anterior y Desabastecimiento (DES) en la inmediatamente posterior.

El **Índice de Culpa** combina estas señales para ayudar al jefe de taller a priorizar la investigación del origen del problema. La ausencia de DES y SAT identifica una parada que no parece estar inducida por las señales consideradas.

## ⚙️ Plan de acción: pipeline de datos

1. **Limpieza:** filtrar anomalías y días sin tiempo de buen funcionamiento (`TBF = 0`) para evitar desviaciones estadísticas.
2. **Contextualización:** combinar (`merge`) los datos de tiempos acumulados con la tabla de configuración para incorporar el orden de las máquinas en la línea.
3. **Cálculo de variables:** generar el TAI a partir de SAT y DES y convertir las unidades de horas a centésimas de minuto.
4. **Detección de propagación:** usar desplazamientos temporales (`shift`) agrupados por día para relacionar los fallos entre estaciones adyacentes.
5. **Priorización:** calcular el Índice de Culpa y ordenar las operaciones para señalar dónde conviene actuar primero.

### Lógica base de propagación

```python
# SAT de la máquina anterior
df['SAT_previo'] = (
    df.groupby(['Year', 'Week', 'Jour'])['SAT']
      .shift(1)
      .fillna(0)
)

# DES de la máquina siguiente
df['DES_siguiente'] = (
    df.groupby(['Year', 'Week', 'Jour'])['DES']
      .shift(-1)
      .fillna(0)
)

# Métrica para clasificar la gravedad de la máquina
df['Indice_Culpa'] = df['TAP'] + df['SAT_previo'] + df['DES_siguiente']
```

El cálculo requiere que los registros estén ordenados por día y por `Orden_OP` antes de aplicar `shift`, de modo que las filas adyacentes correspondan a máquinas vecinas de la línea.

## 🚀 Próximos pasos y escalabilidad

- **Dashboard interactivo:** crear una interfaz sencilla que muestre las operaciones prioritarias y permita al equipo de mantenimiento actuar sobre ellas.
- **Alertas de mantenimiento:** destacar directamente la operación con mayor prioridad para cada día de producción.
- **Escalabilidad:** mantener el código modular para incorporar datos de otras líneas (por ejemplo, L6) o plantas, leyendo su configuración y detectando el flujo sin reescribir la lógica.

## 📁 Estructura actual del proyecto

- `data/`: datos de producción para el análisis.
- `cleaning.py`: módulo previsto para la limpieza y preparación de datos.
- `app.py`: punto de entrada previsto para la aplicación o dashboard.
- `requirements.txt`: dependencias del proyecto.
