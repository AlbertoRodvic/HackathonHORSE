"""Versión de prueba: ejecutar con python -m streamlit run app_v2.py."""

from html import escape
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from analysis import Settings, STATUS_COLORS, TIME_COLORS, analyse, priorities
from cleaning import DAY_KEYS, DAY_LABELS, FLAGS, TIMES, VALUES, prepare_data, select_scenario

ROOT = Path(__file__).resolve().parent
REPORT_VIEWS = ["Resumen de líneas", "Operaciones", "Informe evolución y recurrencia", "Informe de microparadas"]
SCENARIOS = {"Provisional: excluir días sin actividad por confirmar": "provisional",
             "Excluir solo cierres confirmados": "confirmed", "Incluir todos los días": "all"}
METRIC_LABELS = {"Orden_OP": "Orden", "status": "Patrón", "availability_pct": "Disponibilidad propia (%)",
                 "TBF_pct": "Funcionamiento / tiempo registrado (%)", "TAP_pct": "Parada propia / tiempo registrado (%)",
                 "DES_pct": "Desabastecimiento / tiempo registrado (%)", "SAT_pct": "Saturación / tiempo registrado (%)",
                 "TBF": "Funcionamiento (h)", "TAP": "Parada propia (h)", "DES": "Desabastecimiento (h)",
                 "SAT": "Saturación (h)", "TAI": "Parada inducida (h)", "TR": "Tiempo registrado (h)",
                 "NAP": "Número de paradas propias", "NPR": "Piezas producidas", "fpm": "Paradas / 1.000 piezas",
                 "mean_stop_minutes": "Duración media por parada (min)",
                 "stop_duration_reliable": "Media consistente", "cycle_cmin": "Ciclo estimado (cmin/pieza)",
                 "coverage_pct": "Cobertura (%)", "stop_pattern": "Patrón de duración",
                 "recommendation": "Qué revisar", "tap_hours_per_1000": "Horas de parada propia / 1.000 piezas",
                 "recurrence_own": "Semanas con parada propia", "recurrence_des": "Semanas con DES",
                 "recurrence_sat": "Semanas con SAT", "evaluable_week": "Semanas evaluables"}
STATUS_ORDER = ["Parada propia", "Desabastecimiento", "Saturación", "Mixto", "Sin alertas",
                "Sin producción", "Revisar datos", "Sin datos"]
STATUS_EXPLANATIONS = {
    "Parada propia": "Señal de pérdida propia según disponibilidad o TAP.",
    "Desabastecimiento": "Predomina el tiempo registrado como DES.",
    "Saturación": "Predomina el tiempo registrado como SAT.",
    "Mixto": "Coinciden señales propias e inducidas, o DES y SAT sin predominio claro.",
    "Sin alertas": "No hay señal de parada por encima de los umbrales; se divide en buen funcionamiento y elemento lento.",
    "Sin producción": "No constan piezas ni tiempo de funcionamiento; confirmar si debía trabajar.",
    "Revisar datos": "La cobertura o coherencia de los datos no permite comparar con seguridad.",
    "Sin datos": "No hay registros utilizables para esta operación en el periodo.",
}
CARD_COLORS = {
    "Parada propia": "#d94a4a",
    "Desabastecimiento": "#f2cf52",
    "Saturación": "#f08a35",
    "Sin alertas": "#339d78",
    "Buen funcionamiento": "#428bca",
    "Elementos lentos": "#536579",
    "Sin producción": "#98a4b5",
    "Revisar datos": "#667085",
    "Sin datos": "#b8c0cc",
}
FLAG_LABELS = dict(zip(FLAGS, ["Producción sin funcionamiento", "Funcionamiento sin producción",
                              "Paradas sin tiempo propio", "Tiempo propio sin paradas contadas"]))


def number(value, suffix="", digits=1):
    return "—" if pd.isna(value) else f"{value:,.{digits}f}{suffix}"


def table(frame):
    st.dataframe(frame.rename(columns=METRIC_LABELS), hide_index=True, width="stretch")


@st.cache_data(show_spinner=False)
def read_csv(content, decimal):
    return pd.read_csv(BytesIO(content), sep=None, engine="python", decimal=decimal, encoding="utf-8-sig")


def quality_report_zip(prepared, settings, scenario_label, line, weeks, time_unit, reference_hours):
    """Package a traceable quality report without requiring an Excel writer dependency."""
    buffer = BytesIO()
    selected_weeks = set(weeks)

    def scoped(frame):
        result = frame.copy()
        if "Linea" in result.columns:
            result = result.loc[result.Linea.eq(line)]
        if selected_weeks and {"Year", "Week"}.issubset(result.columns):
            result = result.loc[[tuple(row) in selected_weeks for row in result[["Year", "Week"]].to_numpy()]]
        return result

    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        audit = prepared.audit.rename_axis("Comprobación").reset_index(name="Cantidad")
        archive.writestr("auditoria.csv", audit.to_csv(index=False).encode("utf-8-sig"))
        scoped_days = scoped(prepared.days)
        scenario = SCENARIOS[scenario_label]
        if scenario == "confirmed":
            scoped_days["included_in_scenario"] = ~scoped_days.day_status.eq("closed")
        elif scenario == "provisional":
            scoped_days["included_in_scenario"] = ~scoped_days.day_status.isin(["closed", "unconfirmed"])
        else:
            scoped_days["included_in_scenario"] = True
        coverage_columns = [column for column in DAY_KEYS + ["Periodo", "day_status", "observed_operations",
                            "expected_operations", "complete_coverage", "Planned_Production", "Planned_Hours",
                            "included_in_scenario"] if column in scoped_days.columns]
        archive.writestr("cobertura_calendario.csv",
                         scoped_days[coverage_columns].to_csv(index=False).encode("utf-8-sig"))
        archive.writestr("duplicados_exactos_retirados.csv",
                         scoped(prepared.duplicates).to_csv(index=False).encode("utf-8-sig"))
        archive.writestr("registros_apartados_revision.csv",
                         scoped(prepared.quarantine).to_csv(index=False).encode("utf-8-sig"))
        notes = f"""INFORME DE CALIDAD Y SELECCIÓN · LOSSIA

Alcance de las tablas: línea {line}; semanas {', '.join(f'{year}-S{week}' for year, week in weeks)}.
El resumen de auditoría contiene recuentos globales de los archivos cargados.
Escenario seleccionado: {scenario_label}.
Unidad declarada para los tiempos de entrada: {time_unit}. Referencia por jornada: {reference_hours:g} h.
Umbral de disponibilidad propia: {settings.availability_target:g}%.
Umbral de pérdida TAP/DES/SAT sobre tiempo registrado: {settings.loss_threshold_pct:g}%.

TRAZABILIDAD Y REGLAS APLICADAS
1. Se conservan los identificadores de fila de origen (Source_Row) para rastrear registros.
2. Se quitan espacios sobrantes de cabeceras e identificadores y se normalizan los campos numéricos.
3. Se retiran únicamente copias exactamente idénticas; su detalle está en duplicados_exactos_retirados.csv.
4. Las filas con clave diaria en conflicto, valores inválidos o negativos, contadores no enteros,
   operaciones desconocidas o claves incompletas se apartan; no se corrigen ni agregan automáticamente.
   El detalle y las causas figuran en registros_apartados_revision.csv.
5. Las horas se convierten según la unidad declarada. La cobertura compara las operaciones
   observadas con las configuradas para la línea. La ausencia de calendario se indica como
   planificación desconocida y no demuestra que una operación estuviera prevista.
6. El escenario controla cómo se tratan días de cierre confirmado y días sin actividad por confirmar.
   La tabla de cobertura contiene la clasificación diaria usada.
7. Este informe describe reglas y decisiones reproducibles; no atribuye causalidad a las señales.

Archivos: auditoria.csv (recuentos), cobertura_calendario.csv (cobertura/estado diario),
duplicados_exactos_retirados.csv (copias retiradas) y registros_apartados_revision.csv (filas en revisión).
"""
        archive.writestr("metodologia.txt", notes.encode("utf-8"))
    return buffer.getvalue()


def classification_report(settings, line, weeks, scenario_label):
    week_text = ", ".join(f"{year}-S{week}" for year, week in weeks)
    return f"""# Criterios de clasificación y colores · LOSSIA

Línea: {line}  
Semanas analizadas: {week_text}  
Tratamiento de días: {scenario_label}

## Umbrales configurados

- Disponibilidad propia: alerta si es inferior a {settings.availability_target:g}%.
- TAP, DES o SAT: señal si alcanza {settings.loss_threshold_pct:g}% del tiempo registrado (TR).
- Ciclo: `6000 × TBF (h) / NPR`; se considera elemento lento si supera {settings.cycle_target_cmin:g} cmin/pieza.
- Elegibilidad: cobertura completa del periodo, producción positiva, TBF positivo y sin piezas registradas con TBF cero.

## Prioridad y significado

Se revisan primero los casos sin datos o con datos no comparables. Después, la categoría principal se asigna en este orden:
parada propia; desabastecimiento; saturación; mixto; sin alertas.
Una parada propia se señala si la disponibilidad cae bajo el objetivo o TAP/TR alcanza el umbral.
DES/SAT se interpretan según su porcentaje de TR y su predominio relativo; cuando las señales se mezclan,
el resultado es mixto. El agregado diario no prueba qué operación causó la señal de otra.

Dentro de «Sin alertas», el ciclo divide la lectura en «Buen funcionamiento» (ciclo dentro del objetivo)
y «Elementos lentos» (ciclo por encima del objetivo). Por ello un elemento lento no equivale a una avería.

## Leyenda de colores de las fichas

| Estado | Color |
|---|---|
| Parada propia | Rojo (#d94a4a) |
| Desabastecimiento | Amarillo (#f2cf52) |
| Saturación | Naranja (#f08a35) |
| Mixto | Mitad naranja y mitad amarillo |
| Sin alertas (grupo) | Verde (#339d78) |
| Buen funcionamiento | Azul (#428bca) |
| Elementos lentos | Azul grisáceo oscuro (#536579) |
| Revisar datos / Sin producción | Gris (#667085 / #98a4b5) |
| Sin datos | Gris claro (#b8c0cc) |

Las fichas usan el color como fondo completo. Los filtros de disponibilidad son controles neutros y no representan
una clasificación de avería. Todas las señales son criterios de priorización, no un diagnóstico causal.
""".encode("utf-8")


def input_csv(upload, filename, decimal):
    if upload is not None:
        return read_csv(upload.getvalue(), decimal)
    path = ROOT / "data" / filename
    if not path.exists():
        st.info(f"Carga {filename} desde la barra lateral para comenzar.")
        st.stop()
    return read_csv(path.read_bytes(), decimal)


def plot(fig):
    st.pyplot(fig, width="stretch")
    plt.close(fig)


def time_mix(frame, *, daily=False):
    if frame.empty:
        st.info("No hay tiempos para este periodo.")
        return
    columns = [f"{c}_pct" for c in TIMES]
    values = frame.set_index("Periodo" if daily else "Operacion")[columns].rename(
        columns={f"{c}_pct": c for c in TIMES})
    fig, ax = plt.subplots(figsize=(12, 4 if daily else max(4, len(frame) * 0.28)))
    values.plot(kind="bar" if daily else "barh", stacked=True, ax=ax,
                color=[TIME_COLORS[c] for c in TIMES], width=0.8)
    if daily:
        ax.set(ylabel="Horas-máquina registradas (%)", xlabel="Día registrado", ylim=(0, 100))
    else:
        ax.invert_yaxis()
        ax.set(xlabel="Tiempo registrado (%)", ylabel="Operación", xlim=(0, 100))
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, 1.12))
    fig.tight_layout()
    plot(fig)


def open_line(line):
    st.session_state["line"] = line
    st.session_state["report_view"] = "Operaciones"


def open_operation(operation):
    st.session_state["selected_operation"] = operation


def _daily_signals(records, settings):
    daily = records.copy()
    daily["TR"] = daily[TIMES].sum(axis=1)
    denominator = daily.TR.where(daily.TR.gt(0))
    for column in ["TAP", "DES", "SAT"]:
        daily[f"{column}_pct"] = 100 * daily[column].div(denominator)
    own_denominator = (daily.TBF + daily.TAP).where((daily.TBF + daily.TAP).gt(0))
    daily["availability_pct"] = 100 * daily.TBF.div(own_denominator)
    daily["own_stop_signal"] = (daily.TAP_pct.ge(settings.loss_threshold_pct)
                                | daily.availability_pct.lt(settings.availability_target))
    daily["des_signal"] = daily.DES_pct.ge(settings.loss_threshold_pct)
    daily["sat_signal"] = daily.SAT_pct.ge(settings.loss_threshold_pct)
    return daily


def _adjacent_operations(operations, selected, direction):
    selected_order = operations.loc[operations.Operacion.eq(selected), "Orden_OP"].iloc[0]
    if direction == "upstream":
        related = operations.loc[operations.Orden_OP.lt(selected_order)].sort_values("Orden_OP", ascending=False)
    else:
        related = operations.loc[operations.Orden_OP.gt(selected_order)].sort_values("Orden_OP")
    return related.Operacion.tolist()


def _coincident_days(daily, source, target, signal_column):
    source_rows = daily.loc[daily.Operacion.eq(source) & daily.own_stop_signal, DAY_KEYS]
    target_rows = daily.loc[daily.Operacion.eq(target) & daily[signal_column], DAY_KEYS]
    return len(source_rows.merge(target_rows, on=DAY_KEYS, how="inner").drop_duplicates())


def relationship_view(selected, operations, records, settings):
    """Show same-day adjacent signals as investigation leads, never causal proof."""
    daily = _daily_signals(records, settings)
    selected_status = operations.loc[operations.Operacion.eq(selected), "status"].iloc[0]
    st.subheader("Relación con otras máquinas")
    st.caption("Coincidencias en los mismos días con operaciones situadas antes o después según el orden configurado. "
               "Son candidatas para investigar, no causas confirmadas: faltan horas de evento y conexiones físicas completas.")
    reverse_rows = []
    if selected_status in ["Parada propia", "Mixto"]:
        impact_rows = []
        for direction, signal, label in [
            ("upstream", "sat_signal", "Saturación aguas arriba"),
            ("downstream", "des_signal", "Desabastecimiento aguas abajo"),
        ]:
            for neighbor in _adjacent_operations(operations, selected, direction):
                count = _coincident_days(daily, selected, neighbor, signal)
                if count:
                    impact_rows.append({"Máquina relacionada": neighbor,
                                        "Orden": operations.loc[operations.Operacion.eq(neighbor), "Orden_OP"].iloc[0],
                                        "Señal observada": label, "Días coincidentes": count})
        st.markdown("**Máquinas con señales coincidentes**")
        if impact_rows:
            table(pd.DataFrame(impact_rows))
            for index, row in enumerate(impact_rows):
                st.button(f"Abrir ficha de {row['Máquina relacionada']}",
                          key=f"relation_{selected}_{row['Máquina relacionada']}_{index}",
                          on_click=open_operation, args=(row["Máquina relacionada"],))
        else:
            st.info("No se encontraron señales DES/SAT coincidentes en las máquinas vecinas inmediatas.")

    if selected_status in ["Desabastecimiento", "Saturación", "Mixto"]:
        types = []
        if selected_status in ["Desabastecimiento", "Mixto"]:
            types.append(("des_signal", "upstream", "DES: posible máquina aguas arriba"))
        if selected_status in ["Saturación", "Mixto"]:
            types.append(("sat_signal", "downstream", "SAT: posible máquina aguas abajo"))
        for signal, direction, label in types:
            selected_signal = daily.loc[daily.Operacion.eq(selected) & daily[signal], DAY_KEYS]
            for candidate in _adjacent_operations(operations, selected, direction):
                candidate_signal = daily.loc[daily.Operacion.eq(candidate) & daily.own_stop_signal, DAY_KEYS]
                count = len(selected_signal.merge(candidate_signal, on=DAY_KEYS, how="inner").drop_duplicates())
                if count:
                    reverse_rows.append({"Posible máquina relacionada": candidate,
                                         "Orden": operations.loc[operations.Operacion.eq(candidate), "Orden_OP"].iloc[0],
                                         "Señal en esta máquina": label,
                                         "Días coincidentes": count})
        st.markdown("**Posibles máquinas con parada propia coincidente**")
        if reverse_rows:
            table(pd.DataFrame(reverse_rows))
            for index, row in enumerate(reverse_rows):
                st.button(f"Abrir posible origen {row['Posible máquina relacionada']}",
                          key=f"source_{selected}_{row['Posible máquina relacionada']}_{index}",
                          on_click=open_operation, args=(row["Posible máquina relacionada"],))
        else:
            st.info("No se encontró una parada propia coincidente en las operaciones vecinas inmediatas.")


def summary_view(result):
    st.header("Una vista de cada línea")
    st.caption("Las señales orientan una investigación; no atribuyen la causa de las paradas.")
    for row in result.lines.itertuples():
        alert = row.own_alerts + row.des_alerts + row.sat_alerts > 0
        color = STATUS_COLORS["Parada propia"] if alert else "#98a4b5"
        with st.container(border=True):
            st.markdown(f'<div style="border-left:5px solid {color};padding-left:14px">'
                        f'<h3 style="margin:0">{escape(str(row.Linea))}</h3></div>', unsafe_allow_html=True)
            cols = st.columns(4)
            cols[0].metric("Operaciones comparables", f"{row.comparable_operations}/{row.operations}")
            cols[1].metric("Con señales propias", row.own_alerts)
            cols[2].metric("Con señal DES / SAT", f"{row.des_alerts} / {row.sat_alerts}")
            cols[3].metric("Parada propia / tiempo registrado", number(row.own_loss_pct, "%"))
            st.caption(f"{row.review_operations} operaciones requieren revisar datos o cobertura. "
                       "Una operación puede tener señales de varios tipos.")
            st.button("Ver operaciones", key=f"line_{row.Linea}", on_click=open_line, args=(row.Linea,))
    if result.lines.empty:
        st.info("No hay líneas con jornadas incluidas en el escenario seleccionado.")


def diagnostic(row, settings):
    st.subheader(f"Ficha de máquina · {row.Operacion}")
    label = "Elementos lentos" if row["status"] == "Ciclo elevado" else row["status"]
    st.write(f"**{label}** · {row.recommendation}")
    cols = st.columns(5)
    cols[0].metric("Disponibilidad propia", number(row.availability_pct, "%"))
    cols[1].metric("Tiempo en parada propia", number(row.TAP, " h"))
    cols[2].metric("Duración media por parada", number(row.mean_stop_minutes, " min", 2))
    cols[3].metric(f"Paradas por cada {settings.stop_rate_base:,} piezas", number(row.fpm))
    cols[4].metric("Ciclo estimado", number(row.cycle_cmin, " cmin/pieza"))
    if not row.stop_duration_reliable and pd.notna(row.mean_stop_minutes):
        st.warning("La media TAP/NAP se puede calcular, pero hay días con tiempos y contadores "
                   "incompatibles. No se usa para señalar posibles microparadas.")
    st.caption(f"Días con datos: {int(row.observed_days)} de {int(row.expected_days)}. "
               f"Semanas evaluables: {int(row.evaluable_week)}. Señales semanales: "
               f"TAP {int(row.recurrence_own)}, DES {int(row.recurrence_des)}, SAT {int(row.recurrence_sat)}.")
    st.caption(f"Umbrales del periodo: disponibilidad < {settings.availability_target:g}%; "
               f"señal TAP/DES/SAT ≥ {settings.loss_threshold_pct:g}% del tiempo registrado; "
               f"elemento lento si ciclo > {settings.cycle_target_cmin:g} cmin/pieza.")
    table(pd.DataFrame([row])[["Operacion", "TBF_pct", "TAP_pct", "DES_pct", "SAT_pct", "NPR", "NAP", "stop_pattern"]])


def operations_view(operations, records, settings, line, weeks, scenario_label):
    st.header("Operaciones de la línea")
    st.caption("El orden de línea se toma de la configuración. No representa conexiones físicas ni ramas paralelas confirmadas.")
    ordered = operations.copy()
    ordered["display_status"] = ordered.status.replace({"Ciclo elevado": "Sin alertas"})
    ordered["display_detail"] = np.select(
        [ordered.status.eq("Ciclo elevado"), ordered.status.eq("Sin alertas")],
        ["Elementos lentos", "Buen funcionamiento"], default="")
    urgency_order = {status: index for index, status in enumerate(STATUS_ORDER)}
    ordered["_status_rank"] = ordered.display_status.map(urgency_order).fillna(len(STATUS_ORDER))
    ordered["_detail_rank"] = ordered.display_detail.map({"Buen funcionamiento": 0, "Elementos lentos": 1}).fillna(0)
    ordered = ordered.sort_values(["_status_rank", "_detail_rank", "Orden_OP", "Operacion"])
    if st.session_state.get("selected_operation") not in ordered.Operacion.tolist():
        st.session_state["selected_operation"] = ordered.iloc[0].Operacion
    st.subheader("Mapa de patrones del periodo")
    sort_mode = st.selectbox("Organizar máquinas", ["Por orden de línea", "Por disponibilidad de datos"])
    visible = ordered.copy()
    if sort_mode == "Por orden de línea":
        visible = visible.sort_values(["Orden_OP", "Operacion"])
    else:
        availability_group = st.selectbox("Disponibilidad de datos", ["Con datos", "Revisar datos", "Sin datos"])
        if availability_group == "Con datos":
            visible = ordered.loc[ordered.eligible].copy()
            order_mode = st.selectbox("Orden para máquinas con datos",
                                      ["Por orden de línea", "Por urgencia de reparación"])
            if order_mode == "Por urgencia de reparación":
                repair_group = st.selectbox("Tipo de señal", ["Todas", "Parada propia", "Desabastecimiento",
                                                              "Saturación", "Mixto", "Sin alertas"])
                if repair_group == "Sin alertas":
                    detail_filter = st.selectbox("Dentro de Sin alertas",
                                                 ["Todos", "Buen funcionamiento", "Elementos lentos"])
                    if detail_filter != "Todos":
                        visible = visible.loc[visible.display_detail.eq(detail_filter)]
                elif repair_group != "Todas":
                    visible = visible.loc[visible.display_status.eq(repair_group)]
                visible = visible.sort_values(["_status_rank", "_detail_rank", "Orden_OP", "Operacion"])
            else:
                visible = visible.sort_values(["Orden_OP", "Operacion"])
        elif availability_group == "Revisar datos":
            visible = ordered.loc[ordered.status.isin(["Revisar datos", "Sin producción"])].copy()
        else:
            visible = ordered.loc[ordered.status.eq("Sin datos")].copy()
    if "Zona" in visible and visible.Zona.notna().any():
        zones = ["Todas"] + sorted(visible.Zona.dropna().unique().tolist())
        zone = st.selectbox("Zona documentada", zones)
        if zone != "Todas":
            visible = visible.loc[visible.Zona.eq(zone)]
    st.caption(f"Mostrando {len(visible)} de {len(operations)} máquinas. "
               "Los desplegables de disponibilidad solo filtran y ordenan; no añaden color.")
    with st.expander("Leyenda", expanded=False):
        legend_rows = [
            ("Parada propia", CARD_COLORS["Parada propia"], STATUS_EXPLANATIONS["Parada propia"]),
            ("Desabastecimiento", CARD_COLORS["Desabastecimiento"], STATUS_EXPLANATIONS["Desabastecimiento"]),
            ("Saturación", CARD_COLORS["Saturación"], STATUS_EXPLANATIONS["Saturación"]),
            ("Mixto", "linear-gradient(90deg, #f08a35 50%, #f2cf52 50%)", STATUS_EXPLANATIONS["Mixto"]),
            ("Sin alertas · grupo", CARD_COLORS["Sin alertas"], STATUS_EXPLANATIONS["Sin alertas"]),
            ("Buen funcionamiento", CARD_COLORS["Buen funcionamiento"], "Sin alertas de parada y ciclo dentro del objetivo."),
            ("Elementos lentos", CARD_COLORS["Elementos lentos"], "Sin alertas de parada, pero ciclo por encima del objetivo."),
            ("Revisar datos", CARD_COLORS["Revisar datos"], STATUS_EXPLANATIONS["Revisar datos"]),
            ("Sin datos", CARD_COLORS["Sin datos"], STATUS_EXPLANATIONS["Sin datos"]),
        ]
        for label, color, explanation in legend_rows:
            st.markdown(f'<div style="display:flex;align-items:center;gap:10px;margin:5px 0">'
                        f'<span style="display:inline-block;width:22px;height:18px;border-radius:3px;'
                        f'background:{color};border:1px solid #657080"></span>'
                        f'<b>{escape(label)}</b><span>— {escape(explanation)}</span></div>',
                        unsafe_allow_html=True)
        st.caption("El color resume el periodo seleccionado; no es un estado en tiempo real.")
    for start in range(0, len(visible), 5):
        for column, (_, row) in zip(st.columns(5), visible.iloc[start:start + 5].iterrows()):
            with column:
                card_state = row.display_detail if row.display_detail else row.display_status
                color = CARD_COLORS.get(card_state, CARD_COLORS.get(row.display_status, CARD_COLORS["Sin datos"]))
                text_color = "#263238" if card_state in ["Desabastecimiento", "Mixto", "Sin datos"] else "#ffffff"
                background = ("linear-gradient(90deg, #f08a35 0 50%, #f2cf52 50% 100%)"
                              if row.display_status == "Mixto" else color)
                st.markdown(f'<div style="box-sizing:border-box;background:{background};color:{text_color};'
                            f'border:1px solid #dfe4ec;border-radius:8px;padding:14px;min-height:132px">'
                            f'<b>{escape(str(row.Operacion))}</b><br>'
                            f'<span style="font-size:13px">{escape(row.display_detail or row.display_status)}</span><br>'
                            f'<small>Orden {row.Orden_OP:g} · Disponibilidad {number(row.availability_pct, "%")}</small><br>'
                            f'<small>Parada propia {number(row.TAP_pct, "% TR")}</small></div>',
                            unsafe_allow_html=True)
                st.button(f"Abrir {row.Operacion}", key=f"operation_{row.Operacion}",
                          on_click=open_operation, args=(row.Operacion,), width="stretch")
    if visible.empty:
        st.info("No hay máquinas en esta selección. Cambia el filtro de disponibilidad o el periodo.")
    st.selectbox("Máquina seleccionada", ordered.Operacion.tolist(), key="selected_operation")
    selected = st.session_state["selected_operation"]
    with st.container(border=True):
        relationship_view(selected, ordered, records, settings)
        diagnostic(ordered.loc[ordered.Operacion.eq(selected)].iloc[0], settings)
        with st.expander("Registros diarios de esta máquina"):
            table(records.loc[records.Operacion.eq(selected), ["Source_Row"] + DAY_KEYS + ["Operacion"] + VALUES])
    with st.expander("Reparto de tiempos por operación"):
        st.caption("Cada barra es una operación. Las operaciones sin registros no se representan como ceros.")
        time_mix(visible.loc[visible.TR.gt(0)])
    st.download_button("Descargar criterios de clasificación y colores",
                       data=classification_report(settings, line, weeks, scenario_label),
                       file_name="criterios_clasificacion_lossia.md", mime="text/markdown")


def microstop_view(operations, settings):
    st.header("Frecuencia y duración de las paradas")
    st.write("La media por parada es **TAP × 60 / NAP**, en minutos. Se calcula después de sumar "
             "el periodo; no se promedian las medias de cada día.")
    points = operations.loc[operations.eligible & operations.stop_duration_reliable
                            & operations.mean_stop_minutes.gt(0) & operations.fpm.gt(0)]
    if points.empty:
        st.info("No hay operaciones con frecuencia y duración consistentes para dibujar la nube.")
    else:
        fig, ax = plt.subplots(figsize=(11, 5))
        max_tap = points.TAP.max()
        sizes = 30 + 220 * points.TAP / max_tap
        ax.scatter(points.fpm, points.mean_stop_minutes, s=sizes,
                   c=np.where(points.short_frequent_signal, "#dc4848", "#4b87bb"), alpha=0.75)
        ax.axhline(settings.short_stop_minutes, color="#dc4848", linestyle="--", label="Umbral breve")
        ax.axhline(settings.long_stop_minutes, color="#667085", linestyle="--", label="Umbral prolongado")
        ax.axvline(points.frequency_p75.iloc[0], color="#667085", linestyle=":", label="P75 de frecuencia")
        for row in points.nlargest(3, "fpm").itertuples():
            ax.annotate(row.Operacion, (row.fpm, row.mean_stop_minutes), xytext=(4, 5), textcoords="offset points")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set(xlabel=f"Paradas propias / {settings.stop_rate_base} piezas (escala log)",
               ylabel="Duración media (minutos, escala log)")
        ax.legend(fontsize=8)
        fig.tight_layout()
        plot(fig)
        st.caption("Rojo: frecuencia ≥ P75 de la línea y media inferior al umbral breve. "
                   "Tamaño del punto: horas de TAP. Son indicios, no microparadas confirmadas.")
    table(operations[["Operacion", "NAP", "TAP", "fpm", "mean_stop_minutes", "stop_duration_reliable", "stop_pattern"]])


def evolution_view(result, line, operations):
    st.header("Evolución y recurrencia")
    st.subheader("Reparto diario de horas-máquina")
    st.caption("Cada barra suma las operaciones registradas de un día; no mide el tiempo parada de la línea.")
    time_mix(result.daily.loc[result.daily.Linea.eq(line)], daily=True)
    st.subheader("Qué pérdidas se repiten")
    count = st.slider("Operaciones en los mapas", 1, len(operations), min(12, len(operations))) if len(operations) > 1 else 1
    selected = operations.sort_values("TAP_pct", ascending=False).head(count).Operacion.tolist()
    weekly = result.weekly.loc[result.weekly.Linea.eq(line)]
    for tab, kind in zip(st.tabs(["Parada propia · TAP", "Desabastecimiento · DES", "Saturación · SAT"]), ["TAP", "DES", "SAT"]):
        with tab:
            heat = weekly.pivot(index="Operacion", columns=["Year", "Week"], values=f"{kind}_pct").reindex(selected)
            fig, ax = plt.subplots(figsize=(10, max(3, len(heat) * 0.42)))
            image = ax.imshow(heat.to_numpy(dtype=float), cmap="YlOrRd", vmin=0, vmax=100, aspect="auto")
            ax.set_xticks(range(len(heat.columns)), [f"{year}-S{week}" for year, week in heat.columns])
            ax.set_yticks(range(len(heat)), heat.index)
            for i, operation in enumerate(heat.index):
                for j, (year, week) in enumerate(heat.columns):
                    row = weekly.loc[weekly.Operacion.eq(operation) & weekly.Year.eq(year) & weekly.Week.eq(week)].iloc[0]
                    text = f"{heat.iloc[i, j]:.1f}%" if pd.notna(heat.iloc[i, j]) else "Sin datos"
                    text += f" ({int(row.observed_days)}/{int(row.expected_days)} d)"
                    ax.text(j, i, text, ha="center", va="center", fontsize=8)
            fig.colorbar(image, ax=ax, label=f"{kind} / TR (%)")
            fig.tight_layout()
            plot(fig)
    st.caption("Los mapas muestran porcentajes y cobertura. Los recuentos semanales usan solo semanas comparables; "
               "no identifican si la misma avería se prolongó o si fueron eventos diferentes.")
    table(operations[["Operacion", "recurrence_own", "recurrence_des", "recurrence_sat", "evaluable_week"]])


def quality_view(prepared, settings, weeks):
    st.header("Calendario y calidad de los datos")
    st.info("Un festivo público no explica automáticamente un cierre de fábrica. "
            "Los días sin actividad se mantienen como causa pendiente hasta confirmar la planificación. "
            "Si un cierre indicado por el calendario tiene producción o funcionamiento registrado, "
            "se conserva y se señala la contradicción para revisión.")
    st.subheader("Cómo influye el tratamiento de los días")
    comparisons = []
    for label, scenario in SCENARIOS.items():
        records, days = select_scenario(prepared, scenario, weeks)
        result = analyse(records, days, prepared.configuration, settings)
        for line in days.Linea.unique():
            ops = result.operations.loc[result.operations.Linea.eq(line)]
            comparisons.append({"Escenario": label, "Linea": line, "Días": len(days.loc[days.Linea.eq(line)]),
                                "Operaciones comparables": int(ops.eligible.sum()),
                                "Bajo objetivo de disponibilidad": int((ops.eligible & ops.availability_pct.lt(settings.availability_target)).sum())})
    table(pd.DataFrame(comparisons))
    st.subheader("Calendario y cobertura registrados")
    st.caption("Estas tablas de calidad abarcan todos los datos cargados; la comparación anterior usa las semanas elegidas.")
    days = prepared.days.copy()
    days["Estado"] = days.day_status.map(DAY_LABELS)
    table(days[DAY_KEYS + ["Estado", "observed_operations", "expected_operations", "complete_coverage"]])
    table(prepared.audit.to_frame().reset_index(names="Comprobación"))
    st.subheader("Registros con señales de revisión")
    for flag, label in FLAG_LABELS.items():
        detail = prepared.records.loc[prepared.records[flag]]
        with st.expander(f"{label} · {len(detail)} registros"):
            table(detail[["Source_Row"] + DAY_KEYS + ["Operacion"] + VALUES + ["day_status"]])
    with st.expander(f"Registros apartados · {len(prepared.quarantine)}"):
        st.caption("Sus valores conservan las unidades originales. Los motivos figuran en columnas issue_.")
        table(prepared.quarantine)
    with st.expander(f"Copias idénticas retiradas · {len(prepared.duplicates)}"):
        table(prepared.duplicates)


def main():
    st.set_page_config(page_title="LOSSIA · Prueba de mejoras", page_icon="🏭", layout="wide")
    st.markdown("<style>.block-container{padding-top:2rem}div[data-testid='stMetricValue']{font-size:1.7rem}</style>", unsafe_allow_html=True)
    st.title("LOSSIA · Prueba de mejoras")
    st.caption("Versión independiente para probar navegación, relaciones, etiquetas y leyenda. "
               "Las señales de relación son coincidencias, no causas confirmadas.")
    with st.sidebar:
        st.header("Datos y alcance")
        with st.expander("Archivos de entrada"):
            st.caption("Por defecto se leen los CSV de data/. También puedes cargar otros archivos con el mismo esquema.")
            source = st.file_uploader("Producción", type="csv")
            config = st.file_uploader("Configuración", type="csv")
            calendar_file = st.file_uploader("Calendario de fábrica (opcional)", type="csv")
            st.caption("Calendario: Linea, Year, Week, Jour, Planned_Production (0/1); Planned_Hours opcional.")
            decimal = st.selectbox("Separador decimal", [".", ","])
            unit = st.selectbox("Unidad de los tiempos de entrada", ["hours", "minutes", "seconds"],
                                format_func=lambda value: {"hours": "Horas", "minutes": "Minutos", "seconds": "Segundos"}[value])
        with st.expander("Objetivos y umbrales"):
            availability = st.number_input("Objetivo de disponibilidad propia (%)", 1.0, 100.0, 90.0)
            cycle = st.number_input("Objetivo de ciclo (cmin/pieza)", 0.1, value=80.0)
            loss = st.number_input("Señal de pérdida sobre TR (%)", 0.1, 100.0, 10.0)
            short = st.number_input("Parada breve: media inferior a (min)", 0.1, 10.0, 2.0)
            long = st.number_input("Parada prolongada: media desde (min)", 10.1, value=15.0)
            reference = st.number_input("Referencia de horas por jornada", 0.1, value=22.0)
            st.caption("Umbrales exploratorios ajustables; los percentiles se calculan dentro de cada línea y periodo.")
    settings = Settings(availability_target=availability, cycle_target_cmin=cycle,
                        loss_threshold_pct=loss, short_stop_minutes=short, long_stop_minutes=long)
    try:
        raw = input_csv(source, "datos_hackaton.csv", decimal)
        configuration = input_csv(config, "config_hackaton.csv", decimal)
        calendar = read_csv(calendar_file.getvalue(), decimal) if calendar_file else None
        prepared = prepare_data(raw, configuration, calendar=calendar, time_unit=unit, reference_hours=reference)
    except (ValueError, OSError, UnicodeError) as error:
        st.error(f"No se pueden preparar los datos: {error}")
        st.stop()
    if prepared.days.empty:
        st.error("No hay jornadas identificables. Revisa las columnas de línea, año, semana y día.")
        table(prepared.audit.to_frame())
        table(prepared.quarantine)
        st.stop()
    with st.sidebar:
        lines = sorted(prepared.configuration.Linea.dropna().unique().tolist())
        if not lines:
            st.error("La configuración no contiene líneas.")
            st.stop()
        if st.session_state.get("line") not in lines:
            st.session_state["line"] = lines[0]
        line = st.selectbox("Línea", lines, key="line")
        available_weeks = sorted({(int(row.Year), int(row.Week)) for row in prepared.days.itertuples()})
        weeks = st.multiselect("Semanas", available_weeks, default=available_weeks,
                               format_func=lambda value: f"{value[0]} · semana {value[1]}")
        scenario_label = st.selectbox("Tratamiento de días", list(SCENARIOS))
        with st.expander("Resumen de líneas", expanded=True):
            report_view = st.selectbox("Apartado", REPORT_VIEWS, key="report_view")
        with st.expander("Informe de calendario y calidad"):
            st.caption("Incluye auditoría, cobertura diaria, copias idénticas retiradas y filas apartadas para revisión.")
            st.download_button(
                "Descargar informe de calidad y selección",
                data=quality_report_zip(prepared, settings, scenario_label, line, weeks, unit, reference),
                file_name="informe_calidad_y_seleccion_lossia.zip",
                mime="application/zip")
    if not weeks:
        st.info("Selecciona al menos una semana.")
        st.stop()
    scenario = SCENARIOS[scenario_label]
    records, days = select_scenario(prepared, scenario, weeks)
    result = analyse(records, days, prepared.configuration, settings)
    unconfirmed = prepared.days.loc[[tuple(row) in set(weeks) for row in prepared.days[["Year", "Week"]].to_numpy()]].day_status.eq("unconfirmed").sum()
    if unconfirmed:
        st.warning(f"Hay {unconfirmed} días-línea sin actividad cuya causa no está confirmada. "
                   + ("Este escenario los excluye provisionalmente." if scenario == "provisional" else "Este escenario los incluye."))
    st.caption(f"Escenario: {scenario_label}. Tiempos normalizados a horas. "
               "Year/Week/Jour se conservan: no se presupone una correspondencia con fechas civiles.")
    operations = result.operations.loc[result.operations.Linea.eq(line)]
    if report_view == "Resumen de líneas":
        summary_view(result)
    elif operations.empty:
        st.info("Esta línea no tiene jornadas incluidas en el periodo y escenario seleccionados. Descarga el informe de calidad para revisar la cobertura.")
    elif report_view == "Operaciones":
        operations_view(operations, records.loc[records.Linea.eq(line)], settings, line, weeks, scenario_label)
    elif report_view == "Informe de microparadas":
        microstop_view(operations, settings)
    else:
        evolution_view(result, line, operations)
    if not operations.empty:
        st.download_button("Descargar indicadores de esta línea", operations.to_csv(index=False).encode("utf-8-sig"),
                           file_name="indicadores_operaciones.csv", mime="text/csv")
    with st.expander("Glosario y cómo interpretar los resultados"):
        st.markdown("**TBF:** tiempo de buen funcionamiento. **TAP:** tiempo de parada propia. "
                    "**DES:** tiempo en desabastecimiento. **SAT:** tiempo en saturación. "
                    "**TR:** tiempo registrado, suma de TBF + TAP + DES + SAT. "
                    "**TAI:** parada inducida, suma de DES + SAT. **NAP:** número de paradas propias. "
                    "**NPR:** número de piezas producidas. **FPM:** paradas por cada 1.000 piezas.")
        st.markdown("**Disponibilidad propia:** TBF / (TBF + TAP). **Funcionamiento sobre el tiempo registrado:** TBF / TR. "
                    "**FPM:** NAP / NPR × 1.000. **Duración media por parada:** TAP en horas × 60 / NAP, en minutos. "
                    "**Ciclo estimado:** TBF en horas × 6.000 / NPR, en centésimas de minuto por pieza. "
                    "Si un denominador es cero, el valor no se define.")
        st.write("Rojo: parada propia; amarillo: desabastecimiento; naranja: saturación; "
                 "mitad naranja y mitad amarilla: señales mixtas; azul: buen funcionamiento sin alertas de parada; "
                 "azul grisáceo oscuro: elementos lentos; gris: datos por revisar o ausentes. "
                 "Mixto combina señal propia e inducida, o DES y SAT sin predominio claro (factor 1,5).")
        st.write("Los agregados diarios no permiten demostrar propagación, medir buffers ni confirmar microparadas. "
                 "No se suman piezas de operaciones distintas como producción final de línea.")


if __name__ == "__main__":
    main()
