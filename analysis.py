"""Indicadores y patrones explicables; sin dependencias de Streamlit."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from cleaning import BALANCE_COUNT_COLUMNS, DAY_KEYS, FLAGS, OP_KEYS, TIMES, VALUES, balance_counts

STATUS_COLORS = {
    "Parada propia": "#d94a4a", "Desabastecimiento": "#f2cf52", "Saturación": "#f08a35",
    "Mixto": "#f08a35", "Funcionamiento aceptable": "#339d78", "Buen funcionamiento": "#428bca",
    "Elemento lento": "#536579", "Otros": "#98a4b5", "Sin producción": "#98a4b5",
    "Revisar datos": "#667085", "Sin datos": "#b8c0cc",
}
MIXED_BACKGROUND = "linear-gradient(90deg, #f08a35 0 50%, #f2cf52 50% 100%)"
TIME_COLORS = {"TBF": STATUS_COLORS["Funcionamiento aceptable"], "TAP": STATUS_COLORS["Parada propia"],
               "DES": STATUS_COLORS["Desabastecimiento"], "SAT": STATUS_COLORS["Saturación"]}
OTHER_STATUSES = ("Sin producción", "Revisar datos", "Sin datos")


def map_categories(operations):
    """Conserva el motivo de calidad en status y lo agrupa solo para el mapa."""
    return operations.status.replace(dict.fromkeys(OTHER_STATUSES, "Otros"))


@dataclass(frozen=True)
class Settings:
    availability_target: float = 90.0
    cycle_target_cmin: float = 80.0
    loss_threshold_pct: float = 10.0
    short_stop_minutes: float = 2.0
    long_stop_minutes: float = 15.0
    stop_rate_base: int = 1000
    microstop_loss_threshold_pct: float = 1.0


@dataclass
class AnalysisResult:
    operations: pd.DataFrame
    weekly: pd.DataFrame
    daily: pd.DataFrame
    lines: pd.DataFrame


def _ratio(numerator, denominator):
    return numerator.div(denominator.where(denominator.gt(0)))


def metrics(frame, settings):
    result = frame.copy()
    result["TR"] = result[TIMES].sum(axis=1, min_count=1)
    result["TAI"] = result.DES + result.SAT
    result["availability_pct"] = 100 * _ratio(result.TBF, result.TBF + result.TAP)
    for column in TIMES:
        result[f"{column}_pct"] = 100 * _ratio(result[column], result.TR)
    result["induced_pct"] = result.DES_pct + result.SAT_pct
    result["own_stop_share_pct"] = 100 * _ratio(result.TAP, result.TAP + result.TAI)
    result["fpm"] = settings.stop_rate_base * _ratio(result.NAP, result.NPR)
    # Horas de TAP / número de paradas, convertidas a minutos.
    result["mean_stop_minutes"] = 60 * _ratio(result.TAP, result.NAP)
    result["stop_duration_reliable"] = (result.stops_without_own_time.eq(0)
                                         & result.own_time_without_stops.eq(0)
                                         & result.NAP.gt(0) & result.TAP.gt(0))
    result["cycle_cmin"] = 6000 * _ratio(result.TBF, result.NPR)
    result.loc[result.production_without_runtime.gt(0) | result.TBF.le(0), "cycle_cmin"] = np.nan
    result["tap_hours_per_1000"] = 1000 * _ratio(result.TAP, result.NPR)
    result["coverage_pct"] = 100 * _ratio(result.observed_days, result.expected_days)
    result["eligible"] = (result.coverage_pct.eq(100) & result.production_without_runtime.eq(0)
                            & result.NPR.gt(0) & result.TBF.gt(0))
    return result


def aggregate(records, days, configuration, settings, weekly=False):
    period = ["Year", "Week"] if weekly else []
    keys = OP_KEYS + period
    sums = records.groupby(keys, as_index=False)[VALUES + FLAGS + ["time_reference_mismatch"]].sum(min_count=1)
    counts = records.groupby(keys).size().rename("observed_days").reset_index()
    expected = days.groupby(["Linea"] + period).size().rename("expected_days").reset_index()
    # Partir de la configuración hace visibles operaciones completamente ausentes.
    grid = configuration.merge(expected, on="Linea", how="inner", validate="many_to_many")
    grid = grid.merge(sums, on=keys, how="left", validate="one_to_one")
    grid = grid.merge(counts, on=keys, how="left", validate="one_to_one")
    grid = grid.merge(balance_counts(records, keys), on=keys, how="left", validate="one_to_one")
    grid[list(BALANCE_COUNT_COLUMNS)] = grid[list(BALANCE_COUNT_COLUMNS)].fillna(0).astype(int)
    grid["balance_review_days"] = grid[["balance_deficit_days", "balance_excess_days", "balance_zero_days"]].sum(axis=1)
    grid["observed_days"] = grid.observed_days.fillna(0).astype(int)
    grid[FLAGS + ["time_reference_mismatch"]] = grid[FLAGS + ["time_reference_mismatch"]].fillna(0)
    return metrics(grid, settings)


def signal_conditions(frame, settings):
    """Una definición común para colores, filtros, informes y recurrencia."""
    own = frame.availability_pct.lt(settings.availability_target)
    des = frame.DES_pct.ge(settings.loss_threshold_pct)
    sat = frame.SAT_pct.ge(settings.loss_threshold_pct)
    # Si el conjunto inducido supera el umbral pero ninguna componente lo hace,
    # usar predominio 1,5; si están equilibradas conservar ambas señales.
    combined = frame.induced_pct.ge(settings.loss_threshold_pct) & ~des & ~sat
    dominant_des = frame.DES.ge(1.5 * frame.SAT)
    dominant_sat = frame.SAT.ge(1.5 * frame.DES)
    balanced = combined & ~dominant_des & ~dominant_sat
    des = des | (combined & dominant_des) | balanced
    sat = sat | (combined & dominant_sat) | balanced
    below_target = frame.TBF_pct.lt(settings.availability_target)
    return own & below_target, des & below_target, sat & below_target


def classify(operations, settings):
    result = operations.copy()
    own, des, sat = signal_conditions(result, settings)
    result["own_alert"] = own & result.eligible
    result["des_alert"] = des & result.eligible
    result["sat_alert"] = sat & result.eligible
    result["status"] = np.select(
        [result.observed_days.eq(0),
         result.coverage_pct.lt(100) | result.production_without_runtime.gt(0),
         result.NPR.eq(0) & result.TBF.eq(0), result.NPR.eq(0),
         (own & (des | sat)) | (des & sat), own, des, sat],
        ["Sin datos", "Revisar datos", "Sin producción", "Revisar datos", "Mixto",
         "Parada propia", "Desabastecimiento", "Saturación"], default="Buen funcionamiento")
    slow = result.status.eq("Buen funcionamiento") & result.cycle_cmin.gt(settings.cycle_target_cmin)
    result.loc[slow, "status"] = "Elemento lento"
    result["frequency_p75"] = np.nan
    result["frequency_p25"] = np.nan
    valid = result.eligible & result.stop_duration_reliable
    for line, group in result.loc[valid].groupby("Linea"):
        mask = result.Linea.eq(line)
        result.loc[mask, "frequency_p75"] = group.fpm.quantile(0.75)
        result.loc[mask, "frequency_p25"] = group.fpm.quantile(0.25)
    result["short_frequent_signal"] = (valid & result.fpm.ge(result.frequency_p75)
                                         & result.mean_stop_minutes.lt(settings.short_stop_minutes))
    result["stop_pattern"] = np.select(
        [~valid, result.short_frequent_signal,
         result.mean_stop_minutes.ge(settings.long_stop_minutes) & result.fpm.le(result.frequency_p25),
         result.mean_stop_minutes.ge(settings.long_stop_minutes)],
        ["Sin media fiable", "Frecuentes y breves", "Pocas y prolongadas", "Paradas prolongadas"],
        default="Sin patrón destacado")
    return result


def order_operations(operations, urgent=False):
    """Urgencia de investigación, no un impacto causal estimado en producción."""
    result = operations.copy()
    result["urgency_level"] = np.select(
        [result.own_alert, result.des_alert | result.sat_alert,
         result.status.isin(["Revisar datos", "Sin producción", "Sin datos"])],
        [3, 2, 1], default=0)
    result["loss_severity_pct"] = result[["TAP_pct", "DES_pct", "SAT_pct"]].max(axis=1)
    result["recurrence_total"] = result[["recurrence_own", "recurrence_des", "recurrence_sat"]].sum(axis=1)
    if urgent:
        result["category_order"] = result.status.map({"Parada propia": 0, "Saturación": 1,
            "Desabastecimiento": 2, "Mixto": 3, "Buen funcionamiento": 4, "Elemento lento": 4}).fillna(5)
        return result.sort_values(["category_order", "loss_severity_pct", "recurrence_total", "TAP", "Orden_OP", "Operacion"],
                                  ascending=[True, False, False, False, True, True], na_position="last")
    return result.sort_values(["Orden_OP", "Operacion"], kind="stable")


def state_explanation(row, settings):
    """Explicación numérica del mismo criterio que utiliza classify()."""
    if row["status"] == "Sin datos":
        return ["No hay registros utilizables de esta operación en el periodo seleccionado."]
    if row["status"] == "Revisar datos":
        return [f"Cobertura: {row.coverage_pct:.1f}%. Días con producción sin funcionamiento: "
                f"{int(row.production_without_runtime)}. Piezas registradas: {row.NPR:g}.",
                "La revisión de calidad tiene prioridad sobre asignar un estado operativo."]
    if row["status"] == "Sin producción":
        return ["No hay piezas ni tiempo de funcionamiento en el periodo. Confirmar si la operación debía trabajar; "
                "no se distingue una operación no planificada de una parada total sin contexto adicional."]
    own, des, sat = signal_conditions(pd.DataFrame([row]), settings)
    reasons = [f"TBF/TR: {row.TBF_pct:.2f}%; TAP/TR: {row.TAP_pct:.2f}%; "
               f"DES/TR: {row.DES_pct:.2f}%; SAT/TR: {row.SAT_pct:.2f}%."]
    reasons.append(f"Solo se activan señales de parada si TBF/TR < {settings.availability_target:g}%. "
                   "Al alcanzar el objetivo no se asignan señales TAP, DES ni SAT.")
    reasons.append(f"Señal propia: {'sí' if own.iloc[0] else 'no'}; disponibilidad propia "
                   f"{row.availability_pct:.2f}% frente al objetivo de {settings.availability_target:g}%.")
    reasons.append(f"Señal DES: {'sí' if des.iloc[0] else 'no'}; señal SAT: {'sí' if sat.iloc[0] else 'no'}. "
                   f"Umbral individual {settings.loss_threshold_pct:g}%. Si solo la suma inducida lo supera, "
                   "se usa predominio 1,5 o ambas señales cuando están equilibradas.")
    reasons.append("Dos o más señales propias/inducidas producen estado Mixto. Funcionamiento aceptable indica "
                   "que no se activan señales de parada con los criterios del periodo. "
                   f"Dentro de Funcionamiento aceptable, ciclo ≤ {settings.cycle_target_cmin:g} cmin/pieza indica buen funcionamiento; "
                   "un ciclo superior indica elementos lentos, sin atribuir una avería.")
    return reasons


def validate_connections(connections, configuration):
    if connections is None:
        return None
    result = connections.copy()
    result.columns = result.columns.str.strip()
    required = ["Linea", "Origen", "Destino"]
    if not set(required).issubset(result.columns):
        raise ValueError("Conexiones: se requieren Linea, Origen y Destino.")
    for column in required:
        result[column] = result[column].astype("string").str.strip().replace("", pd.NA)
    if result[required].isna().any().any() or result.Origen.eq(result.Destino).any():
        raise ValueError("Las conexiones tienen campos vacíos o una operación conectada consigo misma.")
    known = set(map(tuple, configuration[OP_KEYS].to_numpy()))
    if any((r.Linea, r.Origen) not in known or (r.Linea, r.Destino) not in known for r in result.itertuples()):
        raise ValueError("Las conexiones deben referirse a operaciones de la misma línea configurada.")
    return result[required].drop_duplicates()


def propagation_evidence(operation, records, settings, connections=None):
    """Coincidencia diaria: nunca se interpreta como causalidad ni retardo."""
    columns = ["Operacion", "Hipótesis", "Señal", "Días coincidentes", "Horas coincidentes", "Distancia"]
    if not operation.get("eligible", False):
        return pd.DataFrame(columns=columns)
    line = operation.Linea
    data = records.loc[records.Linea.eq(line) & ~records.day_status.isin(
        ["closed", "unconfirmed", "calendar_conflict"]) & records.production_without_runtime.eq(0)].copy()
    if data.empty:
        return pd.DataFrame(columns=["Operacion", "Hipótesis", "Señal", "Días coincidentes", "Horas coincidentes", "Distancia"])
    tr = data[TIMES].sum(axis=1)
    data["availability_pct"] = 100 * _ratio(data.TBF, data.TBF + data.TAP)
    data["TBF_pct"] = 100 * _ratio(data.TBF, tr)
    for kind in ["TAP", "DES", "SAT"]:
        data[f"{kind}_pct"] = 100 * _ratio(data[kind], tr)
    data["induced_pct"] = data.DES_pct + data.SAT_pct
    for column, signal in zip(["own", "des", "sat"], signal_conditions(data, settings)):
        data[column] = signal
    subject = data.loc[data.Operacion.eq(operation.Operacion)]
    connected = connections is not None and not connections.loc[connections.Linea.eq(line)].empty
    def reachable(reverse=False):
        if not connected:
            return {name: None for name in data.Operacion.unique() if name != operation.Operacion}
        edges = connections.loc[connections.Linea.eq(line)]
        distances, queue = {}, [(operation.Operacion, 0)]
        visited = {operation.Operacion}
        while queue:
            current, distance = queue.pop(0)
            candidates = edges.loc[edges.Destino.eq(current), "Origen"] if reverse else edges.loc[edges.Origen.eq(current), "Destino"]
            for name in candidates:
                if name not in visited:
                    visited.add(name)
                    distances[name] = distance + 1
                    queue.append((name, distance + 1))
        return distances
    upstream, downstream = reachable(True), reachable(False)
    cases = [("own", "sat", "SAT", upstream, "Posible efecto: SAT aguas arriba"),
             ("own", "des", "DES", downstream, "Posible efecto: DES aguas abajo"),
             ("des", "own", "TAP", upstream, "Posible origen del DES recibido"),
             ("sat", "own", "TAP", downstream, "Posible origen del SAT recibido")]
    unknown_labels = {("own", "sat"): "SAT coincide con TAP de la elegida; conexión por confirmar",
                      ("own", "des"): "DES coincide con TAP de la elegida; conexión por confirmar",
                      ("des", "own"): "TAP coincide con DES de la elegida; conexión por confirmar",
                      ("sat", "own"): "TAP coincide con SAT de la elegida; conexión por confirmar"}
    evidence = []
    for subject_signal, other_signal, time_column, neighbours, hypothesis in cases:
        dates = subject.loc[subject[subject_signal], DAY_KEYS].drop_duplicates()
        matching = data.loc[data.Operacion.isin(neighbours) & data[other_signal]].merge(dates, on=DAY_KEYS, how="inner")
        for name, frame in matching.groupby("Operacion"):
            evidence.append({"Operacion": name, "Hipótesis": hypothesis if connected else unknown_labels[(subject_signal, other_signal)],
                             "Señal": time_column, "Días coincidentes": len(frame),
                             "Horas coincidentes": frame[time_column].sum(), "Distancia": neighbours[name]})
    columns = ["Operacion", "Hipótesis", "Señal", "Días coincidentes", "Horas coincidentes", "Distancia"]
    return pd.DataFrame(evidence, columns=columns).drop_duplicates().sort_values(
        ["Días coincidentes", "Horas coincidentes"], ascending=False)


def recommendation(row):
    actions = {
        "Parada propia": "Revisar las causas propias y los registros de mantenimiento.",
        "Desabastecimiento": "Revisar suministro y operaciones que alimentan este puesto.",
        "Saturación": "Revisar salida, buffers y operaciones receptoras.",
        "Mixto": "Separar las incidencias propias de las esperas externas antes de intervenir.",
        "Elemento lento": "Revisar el ciclo y las condiciones de operación; un ciclo alto no confirma una avería.",
        "Buen funcionamiento": "Mantener el seguimiento de disponibilidad y el mantenimiento preventivo.",
        "Sin producción": "Confirmar si debía trabajar; puede estar no planificada o totalmente parada.",
        "Revisar datos": "Revisar cobertura y coherencia de tiempos y contadores antes de comparar.",
        "Sin datos": "Localizar los registros o confirmar si esta operación estaba prevista.",
    }
    text = actions[row["status"]]
    if row.get("short_frequent_signal", False):
        text += " Hay indicios de interrupciones breves: contrastar con eventos y sensores."
    if row.get("time_reference_mismatch", 0) > 0:
        text += " Verificar también el balance de horas registrado."
    return text


def analyse(records, days, configuration, settings=None):
    settings = settings or Settings()
    if not (0 < settings.availability_target <= 100 and settings.cycle_target_cmin > 0
            and 0 < settings.loss_threshold_pct <= 100 and settings.stop_rate_base > 0
            and 0 < settings.short_stop_minutes < settings.long_stop_minutes
            and 0 < settings.microstop_loss_threshold_pct <= 100):
        raise ValueError("Los objetivos o umbrales de análisis no son válidos.")
    operations = classify(aggregate(records, days, configuration, settings), settings)
    weekly = classify(aggregate(records, days, configuration, settings, weekly=True), settings)
    weekly["evaluable_week"] = weekly.eligible.astype(int)
    for kind in ["own", "des", "sat"]:
        weekly[f"recurrence_{kind}"] = weekly[f"{kind}_alert"].astype(int)
    recurrence_columns = ["evaluable_week", "recurrence_own", "recurrence_des", "recurrence_sat"]
    recurrence = weekly.groupby(OP_KEYS, as_index=False)[recurrence_columns].sum()
    operations = operations.merge(recurrence, on=OP_KEYS, how="left", validate="one_to_one")
    operations["recommendation"] = operations.apply(recommendation, axis=1) if not operations.empty else pd.Series(dtype=str)
    daily_keys = DAY_KEYS + ["Periodo"]
    daily = records.groupby(daily_keys, as_index=False)[TIMES].sum()
    daily["TR"] = daily[TIMES].sum(axis=1)
    for column in TIMES:
        daily[f"{column}_pct"] = 100 * _ratio(daily[column], daily.TR)
    lines = []
    for line, frame in operations.groupby("Linea"):
        comparable = frame.loc[frame.eligible]
        total = comparable[TIMES].sum().sum()
        lines.append({"Linea": line, "operations": len(frame), "comparable_operations": len(comparable),
                      "review_operations": int(frame.status.isin(["Revisar datos", "Sin datos"]).sum()),
                      "own_alerts": int(frame.own_alert.sum()), "des_alerts": int(frame.des_alert.sum()),
                      "sat_alerts": int(frame.sat_alert.sum()),
                      "own_loss_pct": 100 * comparable.TAP.sum() / total if total > 0 else np.nan})
    line_summary = pd.DataFrame(lines, columns=["Linea", "operations", "comparable_operations",
                                "review_operations", "own_alerts", "des_alerts", "sat_alerts", "own_loss_pct"])
    return AnalysisResult(operations.sort_values(["Linea", "Orden_OP"]), weekly, daily, line_summary)


def priorities(operations):
    """Lista de investigación de pérdidas propias, no prueba de responsabilidad."""
    return operations.loc[operations.eligible & operations.own_alert].sort_values(
        ["TAP_pct", "recurrence_own", "TAP"], ascending=False)
