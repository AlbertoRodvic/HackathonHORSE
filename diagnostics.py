"""Diagnósticos diarios explicables, independientes de la interfaz y de los colores."""

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from analysis import TIME_COLORS, priorities, signal_conditions
from cleaning import DAY_KEYS, OP_KEYS, TIMES


def daily_metrics(records, settings):
    data = records.copy()
    data["TR"] = data[TIMES].sum(axis=1)
    data["availability_pct"] = 100 * data.TBF.div((data.TBF + data.TAP).where(lambda s: s.gt(0)))
    for kind in TIMES:
        data[f"{kind}_pct"] = 100 * data[kind].div(data.TR.where(data.TR.gt(0)))
    data["induced_pct"] = data.DES_pct + data.SAT_pct
    data["own_signal"], data["des_signal"], data["sat_signal"] = signal_conditions(data, settings)
    data["valid_day"] = (~data.day_status.isin(["closed", "unconfirmed", "calendar_conflict"])
                         & data.production_without_runtime.eq(0) & data.TR.gt(0))
    return data


def total_stops(records):
    """Lista diaria separada: no exige NPR>0 ni presume planificación por operación."""
    data = records.copy()
    data["TR"] = data[TIMES].sum(axis=1)
    data["peer_activity"] = (data.TBF.gt(0) | data.NPR.gt(0)).groupby(
        [data[k] for k in DAY_KEYS]).transform("any")
    stopped = data.loc[data.TBF.eq(0) & data.NPR.eq(0) & data.TR.gt(0)].copy()
    stopped["activity_context"] = np.select(
        [stopped.day_status.eq("calendar_conflict"), stopped.day_status.eq("closed"),
         stopped.day_status.eq("planned") & stopped.reference_hours.gt(0), stopped.peer_activity],
        ["Calendario contradictorio", "Cierre confirmado", "Producción de línea prevista",
         "Actividad observada en otras operaciones"], default="Actividad por confirmar")
    stopped["investigate_total_stop"] = stopped.activity_context.isin(
        ["Producción de línea prevista", "Actividad observada en otras operaciones"])
    stopped["stop_composition"] = np.select(
        [stopped.TAP.gt(0) & (stopped.DES + stopped.SAT).gt(0), stopped.TAP.gt(0)],
        ["Propia e inducida", "Propia"], default="Inducida")
    stopped["next_action"] = np.where(
        stopped.investigate_total_stop,
        "Prioridad alta: confirmar que esta operación debía trabajar e investigar su parada total.",
        "Confirmar calendario y actividad prevista de la operación antes de atribuir una avería.")
    columns = OP_KEYS + ["Periodo", "Source_Row"] + TIMES + ["NAP", "NPR", "TR", "activity_context",
               "investigate_total_stop", "stop_composition", "next_action"]
    return stopped.sort_values(["investigate_total_stop", "TAP", "TR"], ascending=False)[columns]


def critical_candidates(operations, records):
    """Pérdidas propias del periodo más paradas totales propias que requieren investigar."""
    normal = set(map(tuple, priorities(operations)[OP_KEYS].to_numpy()))
    stops = total_stops(records)
    extra = stops.loc[stops.investigate_total_stop & stops.TAP.gt(0)]
    keys = normal | set(map(tuple, extra[OP_KEYS].to_numpy()))
    return operations.loc[[tuple(k) in keys for k in operations[OP_KEYS].to_numpy()]].copy()


def _routes(line, subject, connections):
    if connections is None or connections.loc[connections.Linea.eq(line)].empty:
        return None
    edges = connections.loc[connections.Linea.eq(line)]
    def visit(reverse):
        distances, seen, queue = {}, {subject}, [(subject, 0)]
        for current, depth in queue:
            neighbours = edges.loc[edges.Destino.eq(current), "Origen"] if reverse else edges.loc[edges.Origen.eq(current), "Destino"]
            for other in neighbours:
                if other not in seen:
                    seen.add(other)
                    distances[other] = depth + 1
                    queue.append((other, depth + 1))
        return distances
    return visit(True), visit(False)


IMPACT_COLUMNS = ["Linea", "candidate", "operation", "signal", "relation", "distance",
                  "paired_days", "own_signal_days", "control_days", "coincident_days",
                  "coincidence_pct", "wait_with_own_pct", "wait_without_own_pct", "difference_pp",
                  "spearman", "time_mismatch_days", "comparison_available", "positive_association"]


def impact_pairs(candidates, operations, records, settings, connections=None, min_days=3):
    """Compara TODAS las otras operaciones; los acumulados no prueban causalidad.

    DES/SAT se evalúan por separado. Las medias usan sumas de horas / sumas de TR.
    Con topología se informa si la dirección es compatible; no se inventan enlaces.
    """
    data = daily_metrics(records, settings)
    data = data.loc[data.valid_day]
    rows = []
    for candidate in candidates.itertuples():
        own = data.loc[data.Linea.eq(candidate.Linea) & data.Operacion.eq(candidate.Operacion)]
        routes = _routes(candidate.Linea, candidate.Operacion, connections)
        others = operations.loc[operations.Linea.eq(candidate.Linea) & operations.Operacion.ne(candidate.Operacion)]
        for other in others.itertuples():
            target = data.loc[data.Linea.eq(candidate.Linea) & data.Operacion.eq(other.Operacion)]
            pair = own[DAY_KEYS + ["own_signal", "TAP_pct", "time_reference_mismatch"]].merge(
                target[DAY_KEYS + ["TR", "DES", "SAT", "des_signal", "sat_signal", "time_reference_mismatch"]],
                on=DAY_KEYS, validate="one_to_one", suffixes=("_own", "_other"))
            for kind in ["DES", "SAT"]:
                exposed = pair.own_signal
                n_own, n_control = int(exposed.sum()), int((~exposed).sum())
                other_signal = pair[f"{kind.lower()}_signal"]
                coincident = int((exposed & other_signal).sum())
                def share(mask):
                    denominator = pair.loc[mask, "TR"].sum()
                    return 100 * pair.loc[mask, kind].sum() / denominator if denominator > 0 else np.nan
                with_own, without = share(exposed), share(~exposed)
                y = 100 * pair[kind] / pair.TR
                rho = (pair.TAP_pct.rank().corr(y.rank()) if len(pair) >= 6
                       and pair.TAP_pct.nunique() > 1 and y.nunique() > 1 else np.nan)
                distance = np.nan
                relation = "Conexión por confirmar"
                if routes is not None:
                    compatible = routes[0] if kind == "SAT" else routes[1]
                    opposite = routes[1] if kind == "SAT" else routes[0]
                    if other.Operacion in compatible:
                        relation = "Ruta compatible: " + ("aguas arriba" if kind == "SAT" else "aguas abajo")
                        distance = compatible[other.Operacion]
                    elif other.Operacion in opposite:
                        relation = "Dirección contraria a la hipótesis"
                    else:
                        relation = "Sin ruta en conexiones aportadas"
                available = n_own >= min_days and n_control >= min_days
                rows.append([candidate.Linea, candidate.Operacion, other.Operacion, kind, relation, distance,
                             len(pair), n_own, n_control, coincident,
                             100 * coincident / n_own if n_own else np.nan, with_own, without, with_own - without,
                             rho, int((pair.time_reference_mismatch_own | pair.time_reference_mismatch_other).sum()),
                             available, bool(available and with_own > without and coincident > 0)])
    return pd.DataFrame(rows, columns=IMPACT_COLUMNS)


def impact_summary(pairs):
    columns = ["Linea", "candidate", "other_operations", "observed_operations", "coincident_operations",
               "comparable_operations", "positive_operations", "compatible_positive_operations",
               "unobserved_operations", "interpretation"]
    rows = []
    for (line, candidate), group in pairs.groupby(["Linea", "candidate"], sort=False):
        total = group.operation.nunique()
        observed = group.loc[group.paired_days.gt(0), "operation"].nunique()
        coincident = group.loc[group.coincident_days.gt(0), "operation"].nunique()
        comparable = group.loc[group.comparison_available, "operation"].nunique()
        positive = group.loc[group.positive_association, "operation"].nunique()
        compatible = group.loc[group.positive_association & group.relation.str.startswith("Ruta compatible"), "operation"].nunique()
        rows.append([line, candidate, total, observed, coincident, comparable, positive, compatible, total - observed,
                     "Asociación exploratoria; no demuestra impacto causal sobre todas las operaciones."])
    return pd.DataFrame(rows, columns=columns)


def microstop_assessment(records, settings):
    """Localiza días compatibles y cuantifica su TAP; no suma duraciones de eventos desconocidos."""
    data = daily_metrics(records, settings)
    data["reliable_duration"] = (data.NAP.gt(0) & data.TAP.gt(0) & data.NPR.gt(0) & data.TBF.gt(0)
                                 & data.stops_without_own_time.eq(0) & data.own_time_without_stops.eq(0))
    data["mean_minutes"] = 60 * data.TAP / data.NAP.where(data.NAP.gt(0))
    data["fpm"] = settings.stop_rate_base * data.NAP / data.NPR.where(data.NPR.gt(0))
    reliable = data.loc[data.valid_day & data.reliable_duration]
    reference = reliable.groupby(OP_KEYS, as_index=False)[["NAP", "NPR"]].sum()
    reference["fpm"] = settings.stop_rate_base * reference.NAP / reference.NPR
    thresholds = reference.groupby("Linea").fpm.quantile(.75)
    data["frequency_p75"] = data.Linea.map(thresholds)
    data["brief_frequent_day"] = (data.valid_day & data.reliable_duration
                                  & data.mean_minutes.lt(settings.short_stop_minutes)
                                  & data.fpm.ge(data.frequency_p75))
    rows = []
    for (line, operation), group in data.groupby(OP_KEYS):
        valid = group.loc[group.valid_day]
        signal = group.loc[group.brief_frequent_day]
        tr = valid.TR.sum()
        hours = signal.TAP.sum()
        share = 100 * hours / tr if tr > 0 else np.nan
        significant = bool(len(signal) and share >= settings.microstop_loss_threshold_pct)
        rows.append([line, operation, len(valid), int((valid.reliable_duration).sum()), len(signal), hours,
                     share, signal.NAP.sum(), signal.time_reference_mismatch.sum(), significant,
                     "Interrupciones breves potencialmente relevantes; revisar sensores, atascos y alimentación. No son averías grandes confirmadas."
                     if significant else "Sin señal relevante según el umbral exploratorio; no demuestra ausencia de microparadas."])
    summary = pd.DataFrame(rows, columns=OP_KEYS + ["valid_days", "reliable_days", "brief_frequent_days",
        "tap_on_signal_days_h", "tap_on_signal_days_pct", "stops_on_signal_days", "signal_days_time_mismatch",
        "significant", "recommendation"])
    detail = data.loc[data.brief_frequent_day, OP_KEYS + ["Periodo", "Source_Row", "TAP", "NAP", "NPR", "TR",
        "fpm", "mean_minutes", "frequency_p75", "time_reference_mismatch"]]
    return summary.sort_values("tap_on_signal_days_h", ascending=False), detail


def investigation_figure(operations, settings, metric="availability_pct"):
    """Dos paneles del apartado 4 para las máquinas recibidas, incluso en revisión."""
    if operations.empty:
        return None
    selected = operations.sort_values([metric, "Operacion"], ascending=[True, True],
                                      na_position="last").reset_index(drop=True)
    fig = Figure(figsize=(14, max(4, len(selected) * .55)))
    axes = fig.subplots(1, 2, sharey=True, gridspec_kw={"width_ratios": [1, 1.1]})
    y = np.arange(len(selected))
    axes[0].barh(y, selected[metric], color=TIME_COLORS["TAP"])
    axes[0].axvline(settings.availability_target, color="#333333", linestyle="--", label="Objetivo")
    axes[0].set(xlim=(0, 100), xlabel="Funcionamiento / TR (%)" if metric == "TBF_pct" else "Disponibilidad propia (%)",
                title=f"{selected.Linea.iloc[0]}: dónde investigar")
    axes[0].set_yticks(y, selected.Operacion)
    axes[0].invert_yaxis()
    axes[0].legend()
    for index in selected.index[selected[metric].isna()]:
        axes[0].text(2, index, "Sin disponibilidad definida", va="center", fontsize=9)
    left = np.zeros(len(selected))
    for kind in ["TAP", "DES", "SAT"]:
        values = selected[kind].fillna(0).to_numpy()
        axes[1].barh(y, values, left=left, color=TIME_COLORS[kind], label=kind)
        left += values
    for index in selected.index[selected[["TAP", "DES", "SAT"]].isna().all(axis=1)]:
        axes[1].text(0, index, "Sin tiempos disponibles", va="center", fontsize=9)
    axes[1].set(xlabel="Horas-máquina acumuladas", title="Parada propia frente a esperas externas")
    axes[1].legend()
    fig.tight_layout()
    return fig


def microstop_points(operations):
    """Un punto por operación de la línea y del periodo, nunca por día o semana."""
    if operations.duplicated(OP_KEYS).any():
        raise ValueError("La gráfica de microparadas requiere un único agregado por línea y operación.")
    return operations.loc[operations.eligible & operations.stop_duration_reliable
                          & operations.mean_stop_minutes.gt(0) & operations.fpm.gt(0)].copy()


def stop_action_plan(operations, settings):
    """Plantilla de cuatro casuísticas calculada con los mismos puntos de la nube."""
    points = microstop_points(operations)
    frequent = points.fpm.ge(points.frequency_p75)
    brief = points.mean_stop_minutes.lt(settings.short_stop_minutes)
    cases = [
        ("Muchas paradas cortas", frequent & brief,
         "Revisar registros de eventos, sensores, alimentación y atascos repetidos; priorizar las operaciones con más TAP."),
        ("Muchas paradas largas", frequent & ~brief,
         "Investigar incidencias repetidas y tiempos de recuperación; contrastar mantenimiento y condiciones de operación."),
        ("Pocas paradas cortas", ~frequent & brief,
         "Mantener seguimiento y estandarizar los ajustes; intervenir si aumenta la frecuencia o el tiempo acumulado."),
        ("Pocas paradas largas", ~frequent & ~brief,
         "Revisar las incidencias de mayor duración, su causa registrada y el procedimiento de recuperación."),
    ]
    rows = []
    for name, mask, action in cases:
        group = points.loc[mask].sort_values(["TAP", "Operacion"], ascending=[False, True])
        rows.append({"case": name, "count": len(group), "operations": ", ".join(group.head(3).Operacion.astype(str)),
                     "tap_hours": float(group.TAP.sum()), "action": action})
    return rows


def microstop_figure(operations, settings):
    points = microstop_points(operations)
    if points.empty:
        return None
    fig = Figure(figsize=(11, 5))
    ax = fig.subplots()
    sizes = 30 + 220 * points.TAP / points.TAP.max()
    ax.scatter(points.fpm, points.mean_stop_minutes, s=sizes,
               c=np.where(points.short_frequent_signal, "#dc4848", "#4b87bb"), alpha=.75)
    ax.axhline(settings.short_stop_minutes, color="#dc4848", linestyle="--", label="Umbral breve")
    ax.axhline(settings.long_stop_minutes, color="#667085", linestyle="--", label="Umbral prolongado")
    ax.axvline(points.frequency_p75.iloc[0], color="#667085", linestyle=":", label="P75 de frecuencia")
    for row in points.nlargest(3, "fpm").itertuples():
        ax.annotate(row.Operacion, (row.fpm, row.mean_stop_minutes), xytext=(4, 5), textcoords="offset points")
    ax.set(xscale="log", yscale="log", xlabel=f"Paradas propias / {settings.stop_rate_base} piezas (escala log)",
           ylabel="Duración media (minutos, escala log)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig


def recurrence_matrix(weekly, kind, settings):
    significant = weekly.loc[weekly.eligible & weekly.TBF_pct.lt(settings.availability_target)
                             & weekly[f"{kind}_pct"].ge(settings.loss_threshold_pct)]
    selected = significant.groupby("Operacion")[f"{kind}_pct"].max().sort_values(ascending=False).index.tolist()
    return weekly.pivot(index="Operacion", columns=["Year", "Week"], values=f"{kind}_pct").reindex(selected)


def priority_figure(operations, settings, limit=10):
    """Extiende el último gráfico del apartado 4: mismas operaciones en cinco paneles."""
    selected = priorities(operations).head(limit).iloc[::-1]
    if selected.empty:
        return None
    fig = Figure(figsize=(16, max(3.5, len(selected) * .42)))
    axes = fig.subplots(1, 5, sharey=True, gridspec_kw={"width_ratios": [1.2, 1.7, 1, 1, 1]})
    y = np.arange(len(selected))
    axes[0].barh(y, selected.availability_pct, color="#4b87bb")
    axes[0].axvline(settings.availability_target, color="#dc4848", linestyle="--")
    axes[0].set(xlim=(0, 100), xlabel="Disponibilidad (%)", title="Objetivo de disponibilidad")
    axes[0].set_yticks(y, selected.Operacion)
    left = np.zeros(len(selected))
    for kind in ["TAP", "DES", "SAT"]:
        axes[1].barh(y, selected[kind], left=left, color=TIME_COLORS[kind], label=kind)
        left += selected[kind].fillna(0).to_numpy()
    axes[1].set(xlabel="Horas-máquina", title="Propia y esperas externas")
    axes[1].legend(fontsize=8)
    for ax, column, label in zip(axes[2:], ["fpm", "cycle_cmin", "mean_stop_minutes"],
                                [f"Paradas / {settings.stop_rate_base} piezas", "Ciclo (cmin/pieza)", "Media parada (min)"]):
        ax.barh(y, selected[column], color="#4b87bb")
        ax.set(xlabel=label, xscale="symlog", title="Escala simétrica log")
    axes[3].axvline(settings.cycle_target_cmin, color="#dc4848", linestyle="--")
    fig.suptitle("Dónde investigar: pérdidas propias, esperas y otros indicadores", fontsize=12)
    fig.tight_layout()
    return fig
