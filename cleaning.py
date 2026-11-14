"""Preparación auditable de registros diarios; tiempos normalizados a horas."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

DAY_KEYS = ["Linea", "Year", "Week", "Jour"]
OP_KEYS = ["Linea", "Operacion"]
ROW_KEYS = DAY_KEYS + ["Operacion"]
TIMES = ["TBF", "TAP", "DES", "SAT"]
VALUES = TIMES + ["NAP", "NPR"]
FLAGS = ["production_without_runtime", "runtime_without_production",
         "stops_without_own_time", "own_time_without_stops"]
DAY_LABELS = {"planned": "Producción planificada", "closed": "Cierre confirmado",
              "unconfirmed": "Sin actividad: causa por confirmar", "unknown": "Planificación desconocida",
              "calendar_conflict": "Calendario de cierre con actividad registrada: revisar"}


@dataclass
class PreparedData:
    records: pd.DataFrame
    configuration: pd.DataFrame
    days: pd.DataFrame
    quarantine: pd.DataFrame
    duplicates: pd.DataFrame
    audit: pd.Series


def _text(frame, columns):
    for column in columns:
        frame[column] = frame[column].astype("string").str.strip().replace("", pd.NA)


def _headers(frame):
    result = frame.copy()
    result.columns = result.columns.str.strip()
    if result.columns.duplicated().any():
        raise ValueError("Hay cabeceras repetidas después de quitar espacios.")
    return result


def _require(frame, columns, name):
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{name}: faltan columnas {', '.join(sorted(missing))}.")


def _valid_day(frame):
    numbers = frame[["Year", "Week", "Jour"]]
    return (np.isfinite(numbers).all(axis=1) & numbers.mod(1).eq(0).all(axis=1)
            & frame.Year.between(1, 9999) & frame.Week.between(1, 53)
            & frame.Jour.between(1, 7) & frame.Linea.notna())


def _calendar(source):
    calendar = _headers(source)
    _require(calendar, DAY_KEYS + ["Planned_Production"], "Calendario")
    _text(calendar, ["Linea"])
    for column in ["Year", "Week", "Jour", "Planned_Production"]:
        calendar[column] = pd.to_numeric(calendar[column], errors="coerce")
    if not _valid_day(calendar).all() or calendar.duplicated(DAY_KEYS).any():
        raise ValueError("El calendario contiene días inválidos o claves repetidas.")
    if not calendar.Planned_Production.isin([0, 1]).all():
        raise ValueError("Planned_Production debe ser 0 (cierre) o 1 (producción prevista).")
    if "Planned_Hours" not in calendar:
        calendar["Planned_Hours"] = np.nan
    calendar["Planned_Hours"] = pd.to_numeric(calendar.Planned_Hours, errors="raise")
    hours = calendar.Planned_Hours.dropna()
    if not np.isfinite(hours).all() or hours.lt(0).any():
        raise ValueError("Planned_Hours debe contener horas no negativas y finitas.")
    if "Motivo" not in calendar:
        calendar["Motivo"] = pd.NA
    _text(calendar, ["Motivo"])
    return calendar[DAY_KEYS + ["Planned_Production", "Planned_Hours", "Motivo"]]


def prepare_data(source, configuration, *, calendar=None, time_unit="hours",
                 reference_hours=22.0, tolerance_hours=0.10):
    """No elimina paradas reales ni convierte días sin actividad en festivos."""
    factors = {"hours": 1.0, "minutes": 1 / 60, "seconds": 1 / 3600}
    if time_unit not in factors:
        raise ValueError("Unidad de tiempo desconocida.")
    if (not np.isfinite(reference_hours) or reference_hours <= 0
            or not np.isfinite(tolerance_hours) or tolerance_hours < 0):
        raise ValueError("La referencia horaria debe ser positiva y la tolerancia no negativa.")
    data, config = _headers(source), _headers(configuration)
    _require(data, ROW_KEYS + VALUES, "Producción")
    _require(config, OP_KEYS + ["Orden_OP"], "Configuración")
    if "Source_Row" in data:
        raise ValueError("Source_Row está reservado para la trazabilidad del archivo original.")
    _text(data, OP_KEYS)
    _text(config, OP_KEYS)
    for column in ["Zona", "Planta"]:
        if column in config:
            _text(config, [column])
    config["Orden_OP"] = pd.to_numeric(config.Orden_OP, errors="coerce")
    if (config[OP_KEYS].isna().any().any() or config.duplicated(OP_KEYS).any()
            or not np.isfinite(config.Orden_OP).all() or config.Orden_OP.lt(0).any()):
        raise ValueError("La configuración tiene identificadores, claves u órdenes inválidos.")
    config = config[OP_KEYS + ["Orden_OP"] + [c for c in ["Zona", "Planta"] if c in config]]
    # Detectar copias antes de añadir el número de registro, que es siempre distinto.
    copied = data.duplicated()
    data["Source_Row"] = np.arange(2, len(data) + 2)
    duplicates = data.loc[copied].copy()
    data = data.loc[~copied].copy()
    for column in ["Year", "Week", "Jour"] + VALUES:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    origin_days = data.loc[_valid_day(data), DAY_KEYS].drop_duplicates()
    known = pd.MultiIndex.from_frame(config[OP_KEYS])
    numeric = data[["Year", "Week", "Jour"] + VALUES]
    issues = pd.DataFrame({
        "invalid_key": ~_valid_day(data) | data.Operacion.isna(),
        "invalid_value": (~np.isfinite(numeric).all(axis=1) | data[VALUES].lt(0).any(axis=1)
                          | data[["NAP", "NPR"]].mod(1).ne(0).any(axis=1)),
        "conflicting_key": data.duplicated(ROW_KEYS, keep=False),
        "unknown_operation": ~pd.MultiIndex.from_frame(data[OP_KEYS]).isin(known),
    }, index=data.index)
    bad = issues.any(axis=1)
    quarantine = data.loc[bad].join(issues.add_prefix("issue_"))
    clean = data.loc[~bad].copy()
    clean[TIMES] *= factors[time_unit]
    clean = clean.drop(columns=[c for c in config if c not in OP_KEYS and c in clean])
    clean = clean.merge(config, on=OP_KEYS, how="left", validate="many_to_one")
    clean["production_without_runtime"] = clean.NPR.gt(0) & clean.TBF.eq(0)
    clean["runtime_without_production"] = clean.TBF.gt(0) & clean.NPR.eq(0)
    clean["stops_without_own_time"] = clean.NAP.gt(0) & clean.TAP.eq(0)
    clean["own_time_without_stops"] = clean.TAP.gt(0) & clean.NAP.eq(0)

    calendar_data = _calendar(calendar) if calendar is not None else None
    if calendar_data is not None:
        origin_days = pd.concat([origin_days, calendar_data[DAY_KEYS]], ignore_index=True).drop_duplicates()
    observed = clean.groupby(DAY_KEYS, as_index=False).agg(
        observed_operations=("Operacion", "nunique"),
        all_zero_runtime=("TBF", lambda s: s.eq(0).all()),
        all_zero_output=("NPR", lambda s: s.eq(0).all()))
    days = origin_days.merge(observed, on=DAY_KEYS, how="left", validate="one_to_one")
    expected = config.groupby("Linea").size().rename("expected_operations").reset_index()
    days = days.merge(expected, on="Linea", how="left", validate="many_to_one")
    days["observed_operations"] = days.observed_operations.fillna(0).astype(int)
    days["complete_coverage"] = days.observed_operations.eq(days.expected_operations) & days.observed_operations.gt(0)
    if calendar_data is None:
        days["Planned_Production"] = np.nan
        days["Planned_Hours"] = np.nan
        days["Motivo"] = pd.NA
    else:
        days = days.merge(calendar_data, on=DAY_KEYS, how="left", validate="one_to_one")
    no_activity = days.complete_coverage & days.all_zero_runtime.eq(True) & days.all_zero_output.eq(True)
    activity_on_closed_day = (days.Planned_Production.eq(0) & days.observed_operations.gt(0)
                              & (~days.all_zero_runtime.eq(True) | ~days.all_zero_output.eq(True)))
    days["day_status"] = np.select(
        [activity_on_closed_day, days.Planned_Production.eq(0), days.Planned_Production.eq(1), no_activity],
        ["calendar_conflict", "closed", "planned", "unconfirmed"], default="unknown")
    days["reference_hours"] = days.Planned_Hours.fillna(reference_hours)
    for column in ["Year", "Week", "Jour"]:
        days[column] = days[column].astype(int)
    days["Periodo"] = (days.Year.astype(str) + "-S" + days.Week.astype(str).str.zfill(2)
                        + "-D" + days.Jour.astype(str))
    clean = clean.drop(columns=[column for column in days if column not in DAY_KEYS and column in clean])
    clean = clean.merge(days, on=DAY_KEYS, how="left", validate="many_to_one")
    clean["recorded_hours"] = clean[TIMES].sum(axis=1)
    difference = clean.recorded_hours.sub(clean.reference_hours).abs()
    # Margen numérico de 1e-9 h (~3,6 microsegundos), no una tolerancia operativa adicional.
    clean["time_reference_mismatch"] = difference.gt(tolerance_hours) & ~np.isclose(
        difference, tolerance_hours, atol=1e-9, rtol=0)
    audit = pd.Series({"Registros originales": len(source), "Copias idénticas retiradas": len(duplicates),
                       "Registros apartados": len(quarantine), "Registros utilizables": len(clean),
                       **{name: int(values.sum()) for name, values in issues.items()}}, name="Cantidad")
    return PreparedData(clean, config, days.sort_values(DAY_KEYS), quarantine, duplicates, audit)


def select_scenario(prepared, scenario="provisional", weeks=None):
    """Mantiene días esperados incluso cuando faltan todos sus registros."""
    days = prepared.days.copy()
    if weeks is not None:
        allowed = set(weeks)
        days = days.loc[[tuple(row) in allowed for row in days[["Year", "Week"]].to_numpy()]]
    if scenario == "confirmed":
        days = days.loc[~days.day_status.eq("closed")]
    elif scenario == "provisional":
        days = days.loc[~days.day_status.isin(["closed", "unconfirmed"])]
    elif scenario != "all":
        raise ValueError("Escenario desconocido.")
    records = prepared.records.merge(days[DAY_KEYS], on=DAY_KEYS, how="inner", validate="many_to_one")
    return records, days
