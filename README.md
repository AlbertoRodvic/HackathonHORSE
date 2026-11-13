# 🏭 Reto LOSSIA: Detección Inteligente de Máquinas Penalizantes

## 🎯 El reto

En la línea 5 de montaje de Valladolid, no todas las paradas son iguales. El objetivo de este proyecto es transformar los datos brutos de producción en un análisis end-to-end que permita al jefe de taller identificar rápidamente la causa real de las pérdidas de tiempo.

La solución distingue entre:

- **Parada propia (TAP):** la máquina falla por sí sola.
- **Parada inducida (TAI):** provocada por desabastecimiento (DES) o saturación (SAT) derivados de otras máquinas.

El objetivo no es penalizar a la máquina que más se detiene, sino identificar la que genera un efecto dominó en el resto de la línea.

## 📊 KPIs y métricas principales

El modelo calcula automáticamente los indicadores de referencia para cada operación:

| Indicador | Descripción | Objetivo o cálculo |
| --- | --- | --- |
| **Disponibilidad (Dp)** | Porcentaje de tiempo productivo. | `>= 90 %` |
| **Tiempo de Ciclo (Tcy)** | Tiempo que tarda la operación en producir una pieza, en centésimas de minuto. | `<= 80 cmin` |
| **Frecuencia de Parada (Fpm)** | Número de paradas por cada mil piezas reales producidas. | `(NAP / NPR) * 1000` |
| **Microparadas vs. averías** | Ratio para diferenciar atascos rápidos de averías graves. | `TAP / NAP` |

## 🧠 Enfoque: algoritmo de propagación

Para resolver el reto de forma original y escalable, proponemos un algoritmo que recorre la topología de la línea usando el `Orden_OP` de la tabla de configuración.

Una máquina se considera una posible **máquina penalizante** cuando, durante un día de producción, se cumplen simultáneamente estas condiciones:

1. Registra un tiempo alto de Parada Propia (TAP).
2. Provoca Saturación (SAT) en la máquina inmediatamente anterior.
3. Provoca Desabastecimiento (DES) en la máquina inmediatamente posterior.

El **Índice de Culpa** combina estas señales para ayudar al jefe de taller a priorizar la investigación del origen del problema.

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
