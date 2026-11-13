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

1. **Registros señalados en el EDA:** revisar la tabla de registros con señal de revisión y contrastar sus valores con Excel. Hay valores contabilizados cuya precisión todavía no está confirmada.
2. **Columna de fecha:** crear una columna de fecha que sustituya a `Year`, `Week` y `Jour` para facilitar el análisis temporal.

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
