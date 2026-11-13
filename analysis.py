"""Indicadores y patrones explicables; sin dependencias de Streamlit."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from cleaning import DAY_KEYS, FLAGS, OP_KEYS, TIMES, VALUES

STATUS_COLORS = {
    "Parada propia": "#dc4848", "Desabastecimiento": "#e6bd32",
    "Saturación": "#ed8738", "Mixto": "#9570b7", "Ciclo elevado": "#4b87bb",
    "Sin alertas": "#339d78", "Sin producción": "#98a4b5", "Revisar datos": "#667085",
    "Sin datos": "#b8c0cc",
}
TIME_COLORS = {"TBF": "#339d78", "TAP": "#dc4848", "DES": "#e6bd32", "SAT": "#ed8738"}


@dataclass(frozen=True)
class Settings:
    availability_target: float = 90.0
    cycle_target_cmin: float = 80.0
    loss_threshold_pct: float = 10.0
    short_stop_minutes: float = 2.0
    long_stop_minutes: float = 15.0
    stop_rate_base: int = 1000


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
    grid["observed_days"] = grid.observed_days.fillna(0).astype(int)
    grid[FLAGS + ["time_reference_mismatch"]] = grid[FLAGS + ["time_reference_mismatch"]].fillna(0)
    return metrics(grid, settings)


def classify(operations, settings):
    result = operations.copy()
    own = result.availability_pct.lt(settings.availability_target) | result.TAP_pct.ge(settings.loss_threshold_pct)
    induced = result.induced_pct.ge(settings.loss_threshold_pct)
    des = induced & result.DES.ge(1.5 * result.SAT)
    sat = induced & result.SAT.ge(1.5 * result.DES)
    result["own_alert"] = own & result.eligible
    result["des_alert"] = result.DES_pct.ge(settings.loss_threshold_pct) & result.eligible
    result["sat_alert"] = result.SAT_pct.ge(settings.loss_threshold_pct) & result.eligible
    result["status"] = np.select(
        [result.observed_days.eq(0),
         result.coverage_pct.lt(100) | result.production_without_runtime.gt(0),
         result.NPR.eq(0) & result.TBF.eq(0), result.NPR.eq(0),
         (own & induced) | (induced & ~des & ~sat), own, des, sat,
         result.cycle_cmin.gt(settings.cycle_target_cmin)],
        ["Sin datos", "Revisar datos", "Sin producción", "Revisar datos", "Mixto",
         "Parada propia", "Desabastecimiento", "Saturación", "Ciclo elevado"], default="Sin alertas")
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


def recommendation(row):
    actions = {
        "Parada propia": "Revisar las causas propias y los registros de mantenimiento.",
        "Desabastecimiento": "Revisar suministro y operaciones que alimentan este puesto.",
        "Saturación": "Revisar salida, buffers y operaciones receptoras.",
        "Mixto": "Separar las incidencias propias de las esperas externas antes de intervenir.",
        "Ciclo elevado": "Validar unidades, contador, producto y capacidad de la operación.",
        "Sin alertas": "Mantener seguimiento con los umbrales y periodo seleccionados.",
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
            and 0 < settings.short_stop_minutes < settings.long_stop_minutes):
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
