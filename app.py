"""Ejecutar con: python -m streamlit run app.py"""

from html import escape
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Streamlit renderiza imágenes; no debe iniciar ventanas Tk.
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from analysis import (Settings, STATUS_COLORS, MIXED_BACKGROUND, TIME_COLORS, analyse, order_operations,
                      OTHER_STATUSES, map_categories, propagation_evidence)
from cleaning import TIMES, prepare_data, select_scenario
from reports import operation_report, classification_report, text_color
from diagnostics import investigation_figure, microstop_points, microstop_figure, stop_action_plan, recurrence_matrix

ROOT = Path(__file__).resolve().parent
ANALYSES = ["Microparadas", "Máquinas más problemáticas", "Tiempos todas las máquinas"]
SCENARIOS = {"Provisional: excluir días sin actividad por confirmar": "provisional",
             "Excluir solo cierres confirmados": "confirmed", "Incluir todos los días": "all"}
METRIC_LABELS = {"Orden_OP": "Orden", "status": "Patrón", "availability_pct": "Disponibilidad propia (%)",
                 "TBF_pct": "Funcionamiento / TR (%)", "TAP_pct": "TAP / TR (%)",
                 "DES_pct": "DES / TR (%)", "SAT_pct": "SAT / TR (%)", "TAP": "TAP (h)",
                 "TAI": "TAI (h)", "fpm": "FPM", "mean_stop_minutes": "Media parada (min)",
                 "stop_duration_reliable": "Media consistente", "cycle_cmin": "Ciclo (cmin/pieza)",
                 "coverage_pct": "Cobertura (%)", "stop_pattern": "Patrón de duración",
                 "recommendation": "Qué revisar", "tap_hours_per_1000": "TAP h/1.000 piezas",
                 "recurrence_own": "Semanas TAP", "recurrence_des": "Semanas DES",
                 "recurrence_sat": "Semanas SAT", "evaluable_week": "Semanas evaluables",
                 "balance_label": "Etiqueta de balance", "recorded_hours": "Horas registradas",
                 "reference_hours": "Horas de referencia", "balance_delta_minutes": "Desvío (min)",
                 "balance_ok_days": "Días en banda", "balance_deficit_days": "Días con déficit",
                 "balance_excess_days": "Días con exceso", "balance_zero_days": "Días sin tiempo",
                 "balance_review_days": "Días con balance por revisar"}


def number(value, suffix="", digits=1):
    return "—" if pd.isna(value) else f"{value:,.{digits}f}{suffix}"


def table(frame):
    st.dataframe(frame.rename(columns=METRIC_LABELS), hide_index=True, width="stretch")


@st.cache_data(show_spinner=False)
def read_csv(content, decimal):
    return pd.read_csv(BytesIO(content), sep=None, engine="python", decimal=decimal, encoding="utf-8-sig")


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
    st.session_state["section"] = "Operaciones"
    st.session_state["selected_operation"] = None


def open_summary():
    st.session_state["section"] = "Resumen de líneas"


def open_operation(operation):
    st.session_state["selected_operation"] = operation


def reset_operation():
    st.session_state["selected_operation"] = None


def toggle_map():
    st.session_state["map_expanded"] = not st.session_state.get("map_expanded", False)


def source_identity(upload, filename):
    content = upload.getvalue() if upload is not None else (ROOT / "data" / filename).read_bytes()
    name = upload.name if upload is not None else filename
    return f"{name} | SHA-256 {sha256(content).hexdigest()}"


def summary_view(result, configuration):
    st.header("Elige una línea")
    st.caption("Líneas ordenadas por máquinas con señales de parada. Cada máquina cuenta una vez si tiene señal TAP, SAT, DES o mixta. "
               "La lentitud y la revisión de datos se muestran por separado; las señales no confirman averías.")
    signals = result.operations[["own_alert", "des_alert", "sat_alert"]].any(axis=1)
    problems = result.operations.loc[signals].groupby("Linea").size()
    lines = sorted(configuration.Linea.unique(), key=lambda name: (-int(problems.get(name, 0)), str(name)))
    for line in lines:
        operations = result.operations.loc[result.operations.Linea.eq(line)]
        color = STATUS_COLORS["Parada propia" if problems.get(line, 0) else "Buen funcionamiento" if operations.eligible.any() else "Otros"]
        with st.container(border=True):
            st.markdown(f'<div style="border-left:5px solid {color};padding-left:14px">'
                        f'<h3 style="margin:0">{escape(str(line))}</h3></div>', unsafe_allow_html=True)
            st.metric("Máquinas con señales de parada", int(problems.get(line, 0)))
            if operations.empty:
                st.info("Sin jornadas incluidas para esta línea en el periodo y escenario seleccionados.")
            st.button("Ver operaciones", key=f"line_{line}", on_click=open_line, args=(line,), type="primary")


def others_view(operations, settings):
    others = operations.loc[operations.status.isin(OTHER_STATUSES)]
    if others.empty:
        return
    st.header("Revisión de datos")
    st.warning(f"{len(others)} operaciones requieren revisión de planificación o datos. "
               "Confirmar estos casos antes de interpretar sus pérdidas como averías.")
    actions = {
        "Sin producción": ("Sin producción", "Confirmar si estas máquinas debían producir y su planificación. "
                           "Mantenimiento: si debían trabajar, investigar la parada total y registrar la causa."),
        "Revisar datos": ("Revisar datos", "Completar las jornadas que faltan y contrastar la producción registrada. "
                         "Mantenimiento: comprobar contadores, sensores y coherencia de los tiempos."),
        "Sin datos": ("Sin datos", "Confirmar si las máquinas estaban previstas y localizar sus registros. "
                     "Mantenimiento: revisar la captura de datos si faltan registros de máquinas que estaban activas."),
    }
    with st.expander(f"Otros · {len(others)} máquinas", expanded=False):
        st.caption("Otros agrupa Sin producción, Revisar datos y Sin datos. No son averías confirmadas.")
        for status, (label, action) in actions.items():
            group = others.loc[others.status.eq(status)]
            if not group.empty:
                with st.expander(f"{label} · {len(group)} máquinas"):
                    st.write("**Máquinas:** " + ", ".join(group.Operacion.astype(str)))
                    st.write(action)
                    table(group[["Linea", "Operacion", "TBF", "TAP", "NPR", "coverage_pct",
                                 "observed_days", "expected_days", "recommendation"]])


def total_stop_view(operations):
    stopped = operations.loc[operations.TBF.eq(0) & operations.NPR.eq(0) & operations.TAP.gt(0)]
    if stopped.empty:
        return
    with st.expander(f"Paradas totales propias · {len(stopped)} máquinas", expanded=True):
        st.warning("TBF cero con tiempo de parada propia registrado. Confirmar si estas operaciones debían trabajar e investigar la parada total.")
        st.caption("Con datos completos, estas operaciones figuran como Sin producción, dentro de Otros. "
                   "No se mezclan con las máquinas que producen y tienen paradas parciales.")
        table(stopped[["Operacion", "status", "TBF", "TAP", "DES", "SAT", "NPR"]])
        for row in stopped.itertuples():
            st.button(f"Ver diagnóstico de {row.Operacion}", key=f"total_stop_{row.Operacion}",
                      on_click=open_operation, args=(row.Operacion,))


def diagnostic(row, settings):
    st.subheader(f"Detalle · {row.Operacion}")
    st.write(f"**{row['status']}** · {row.recommendation}")
    cols = st.columns(5)
    cols[0].metric("Disponibilidad propia", number(row.availability_pct, "%"))
    cols[1].metric("Parada propia", number(row.TAP, " h"))
    cols[2].metric("Media por parada", number(row.mean_stop_minutes, " min", 2))
    cols[3].metric(f"Paradas / {settings.stop_rate_base} piezas", number(row.fpm))
    cols[4].metric("Ciclo de funcionamiento", number(row.cycle_cmin, " cmin"))
    if row.balance_review_days > 0:
        st.warning(f"Balance horario por revisar en {int(row.balance_review_days)} de {int(row.observed_days)} registros: "
                   f"{int(row.balance_deficit_days)} con déficit, {int(row.balance_excess_days)} con exceso y "
                   f"{int(row.balance_zero_days)} sin tiempo asignado. Los indicadores incluyen estos datos originales; "
                   "no se ha rellenado ni recortado tiempo para ajustar la jornada.")
    elif row.observed_days > 0:
        st.caption("Todos los registros disponibles están en la banda orientativa de balance; esto no certifica la ausencia de otros errores.")
    if not row.stop_duration_reliable and pd.notna(row.mean_stop_minutes):
        st.warning("La media TAP/NAP se puede calcular, pero hay días con tiempos y contadores "
                   "incompatibles. No se usa para señalar posibles microparadas.")
    st.caption(f"Días con datos: {int(row.observed_days)} de {int(row.expected_days)}. "
               f"Semanas evaluables: {int(row.evaluable_week)}. Señales semanales: "
               f"TAP {int(row.recurrence_own)}, DES {int(row.recurrence_des)}, SAT {int(row.recurrence_sat)}.")
    table(pd.DataFrame([row])[["Operacion", "TBF_pct", "TAP_pct", "DES_pct", "SAT_pct", "NPR", "NAP", "stop_pattern"]])


def operations_view(operations, records, days, settings, scenario, connections, sources):
    st.header("Mapa de operaciones")
    st.caption(f"Línea: {operations.Linea.iloc[0]}")
    total_stop_view(operations)
    st.caption("Cada caja es una operación. Desliza la fila o abre la vista completa; pulsa una caja para ver su diagnóstico debajo.")
    controls = st.columns([1.1, 1.8, 1.2])
    order_mode = controls[0].selectbox("Orden para máquinas con datos", ["Por orden de línea", "Por urgencia de reparación"], key="map_order")
    repair_group = controls[1].selectbox("Tipo de señal", ["Todas", "Parada propia", "Saturación", "Desabastecimiento", "Mixto", "Funcionamiento aceptable", "Otros"], key="map_signal")
    available = [name for name in STATUS_COLORS if name in set(map_categories(operations))]
    visible = order_operations(operations, urgent=order_mode == "Por urgencia de reparación")
    if repair_group == "Funcionamiento aceptable":
        visible = visible.loc[visible.status.isin(["Buen funcionamiento", "Elemento lento"])]
        detail = st.selectbox("Dentro de Funcionamiento aceptable", ["Todos", "Buen funcionamiento", "Elemento lento"], key="map_no_alerts")
        if detail != "Todos":
            visible = visible.loc[visible.status.eq(detail)]
    elif repair_group == "Otros":
        visible = visible.loc[visible.status.isin(OTHER_STATUSES)]
        review = st.selectbox("Tipo de revisión", ["Todos", *OTHER_STATUSES], key="map_review")
        if review != "Todos":
            visible = visible.loc[visible.status.eq(review)]
    elif repair_group != "Todas":
        visible = visible.loc[visible.status.eq(repair_group)]
    with controls[2]:
        st.write("")
        st.button("Volver a fila horizontal" if st.session_state.get("map_expanded", False) else "Ver todas en pantalla",
                  key="toggle_map", on_click=toggle_map, width="stretch")
    if "Zona" in visible and visible.Zona.notna().any():
        zone = st.selectbox("Zona documentada", ["Todas"] + sorted(visible.Zona.dropna().unique().tolist()))
        if zone != "Todas":
            visible = visible.loc[visible.Zona.eq(zone)]
    present = set(map_categories(visible))
    legend = " · ".join(f'<span style="display:inline-block;width:12px;height:12px;background:{MIXED_BACKGROUND if status == "Mixto" else STATUS_COLORS[status]}"></span> {escape(status)}'
                        for status in available if status in present)
    st.markdown(legend, unsafe_allow_html=True)
    st.caption(f"Mostrando {len(visible)} de {len(operations)} operaciones. "
               + "Los filtros no cambian los colores. "
               + "El orden no implica conexión física; el color resume el periodo, no el estado instantáneo.")
    expanded = st.session_state.get("map_expanded", False)
    selected = st.session_state.get("selected_operation")
    if selected not in operations.Operacion.tolist():
        selected = None
        st.session_state["selected_operation"] = None
    styles = []
    def tile(row):
        identity = sha256(f"{row.Linea}\0{row.Operacion}".encode()).hexdigest()[:16]
        key = f"map_tile_{identity}"
        background = MIXED_BACKGROUND if row["status"] == "Mixto" else STATUS_COLORS[row["status"]]
        foreground = text_color(STATUS_COLORS[row["status"]])
        outline = "3px solid #182b49" if row.Operacion == selected else "1px solid transparent"
        styles.append(f".st-key-{key} button{{background:{background}!important;color:{foreground}!important;"
                      f"border:{outline}!important;border-radius:8px;min-height:54px;font-weight:700;"
                      "box-shadow:0 2px 5px #14253f18;}"
                      f".st-key-{key} button p{{color:{foreground}!important;font-weight:700;font-size:13px;white-space:nowrap;}}"
                      f".st-key-{key} button:hover{{filter:brightness(1.08);transform:translateY(-1px);}}")
        with st.container(key=key, width="stretch" if expanded else 142):
            st.button(str(row.Operacion), key=f"operation_{identity}", width="stretch",
                      on_click=open_operation, args=(row.Operacion,),
                      help=f"{row['status']} · Orden {row.Orden_OP:g}")
    if visible.empty:
        st.info("Ninguna operación cumple estos filtros. Quita un filtro para ampliar la vista.")
    elif expanded:
        for start in range(0, len(visible), 9):
            for column, (_, row) in zip(st.columns(9, gap="small"), visible.iloc[start:start + 9].iterrows()):
                with column:
                    tile(row)
    else:
        with st.container(horizontal=True, wrap=False, key="operation_strip"):
            for _, row in visible.iterrows():
                tile(row)
    st.markdown("<style>" + "".join(styles) + "</style>", unsafe_allow_html=True)
    st.download_button("Descargar criterios de clasificación y colores",
                       classification_report(settings, operations.Linea.iloc[0],
                                             sorted(set(zip(days.Year, days.Week))), scenario),
                       file_name="criterios_clasificacion_lossia.pdf", mime="application/pdf", on_click="ignore")
    if selected is not None:
        st.divider()
        row = operations.loc[operations.Operacion.eq(selected)].iloc[0]
        diagnostic(row, settings)
        with st.expander("Posibles efectos sobre otras operaciones y fuentes de espera"):
            st.caption("Coincidencias diarias, no causalidad demostrada. Sin conexiones aportadas no se conoce la dirección del efecto.")
            evidence = propagation_evidence(row, records, settings, connections)
            effect_signals = {"Todos": None, "Desabastecimiento en otras operaciones (DES)": "DES",
                              "Saturación en otras operaciones (SAT)": "SAT", "Fuentes de espera de la seleccionada (TAP)": "TAP"}
            effect = st.selectbox("Filtrar por tipo de efecto", list(effect_signals), key="operation_effect")
            signal = effect_signals[effect]
            if signal is not None:
                evidence = evidence.loc[evidence["Señal"].eq(signal)]
            if evidence.empty:
                st.info("No hay coincidencias para este tipo de efecto en el periodo seleccionado.")
            displayed_evidence = evidence.drop(columns=["Distancia"]).copy()
            displayed_evidence["Hipótesis"] = displayed_evidence["Hipótesis"].str.replace(
                "; conexión por confirmar", "", regex=False)
            table(displayed_evidence)
        pdf = operation_report(row, records, days, settings, scenario, connections=connections, source_info=sources)
        filename = "diagnostico_" + sha256(f"{row.Linea}/{selected}".encode()).hexdigest()[:10] + ".pdf"
        st.download_button("Descargar diagnóstico PDF", pdf, file_name=filename, mime="application/pdf", on_click="ignore", type="primary")


def action_plan_view(operations, settings):
    st.caption(f"Muchas/pocas se compara con el P75 de paradas por pieza de la línea; "
               f"cortas/largas se separan en {settings.short_stop_minutes:g} min de media. "
               "Estas categorías orientan la revisión; no identifican la causa de las paradas.")
    for case in stop_action_plan(operations, settings):
        if case["count"]:
            st.markdown(f"**{case['case']} · {case['count']} operaciones, {number(case['tap_hours'], ' h TAP')}.** "
                        f"Priorizar por tiempo acumulado: {case['operations']}. {case['action']}")
        else:
            st.markdown(f"**{case['case']}:** sin operaciones con media fiable en este grupo.")


def microstop_view(operations, settings, records):
    st.header("Frecuencia y duración de las paradas")
    points = microstop_points(operations)
    micro = points.loc[points.short_frequent_signal].sort_values(["mean_stop_minutes", "Operacion"])
    cards = st.columns(3)
    cards[0].metric("Operaciones representadas", len(points))
    cards[1].metric("Indicios de microparadas", len(micro))
    cards[2].metric("Media de parada prolongada", int(points.mean_stop_minutes.ge(settings.long_stop_minutes).sum()))
    st.caption(f"Un punto por operación: {len(points)} de {len(operations)} operaciones de la línea. "
               "Se excluyen las medias no fiables y los datos insuficientes; no se dibujan días ni semanas como puntos adicionales. "
               "El tamaño de la burbuja representa las horas de TAP.")
    fig = microstop_figure(operations, settings)
    if fig is None:
        st.info("No hay operaciones con frecuencia y duración consistentes para dibujar la nube.")
    else:
        plot(fig)
        st.caption("Rojo: frecuencia ≥ P75 y media inferior al umbral breve. Son indicios de microparadas, no eventos confirmados.")
    st.subheader("Lectura de la línea y acciones recomendadas")
    action_plan_view(operations, settings)
    if not micro.empty:
        first = micro.sort_values("TAP", ascending=False).iloc[0]
        st.write(f"La mayor acumulación de TAP entre las operaciones con indicios corresponde a {first.Operacion}: "
                 f"{number(first.TAP, ' h')}, {number(first.fpm)} paradas por {settings.stop_rate_base} piezas "
                 f"y {number(first.mean_stop_minutes, ' min', 3)} por parada. "
                 "Contrastar los eventos y las condiciones de operación antes de decidir la intervención.")
    if not points.empty and not points.mean_stop_minutes.ge(settings.long_stop_minutes).any():
        st.write(f"Ninguna media fiable alcanza {settings.long_stop_minutes:g} min. "
                 "Esto no excluye eventos largos aislados dentro de una media baja.")
    st.subheader("Operaciones con indicios de microparadas, de menor a mayor duración media")
    if micro.empty:
        st.info("No hay operaciones que combinen frecuencia alta y media breve en esta selección.")
    else:
        table(micro[["Operacion", "mean_stop_minutes", "fpm", "NAP", "TAP"]])
    with st.expander("Datos y cálculo de la media"):
        st.write("Media = 60 × suma de TAP / suma de NAP. Se agregan los registros de cada operación antes de dividir.")
        table(operations[["Operacion", "NAP", "TAP", "fpm", "mean_stop_minutes", "stop_duration_reliable"]])


def problematic_view(result, line, operations, settings):
    st.header("Máquinas más problemáticas")
    others_view(operations, settings)
    below = operations.loc[operations.eligible & operations.TBF_pct.lt(settings.availability_target)]
    st.subheader(f"Máquinas con funcionamiento / TR < {settings.availability_target:g}% · {len(below)}")
    if below.empty:
        st.info("No hay operaciones comparables por debajo del objetivo.")
    else:
        st.caption("Las barras y el filtro usan el mismo indicador: TBF / (TBF + TAP + DES + SAT). "
                   "Estar por debajo del objetivo no demuestra una avería propia.")
        plot(investigation_figure(below, settings, metric="TBF_pct"))
        st.subheader("Patrón de paradas y línea de actuación")
        action_plan_view(below, settings)
    st.subheader("Qué pérdidas se repiten")
    weekly = result.weekly.loc[result.weekly.Linea.eq(line)]
    for tab, kind in zip(st.tabs(["Parada propia · TAP", "Saturación · SAT", "Desabastecimiento · DES"]), ["TAP", "SAT", "DES"]):
        with tab:
            heat = recurrence_matrix(weekly, kind, settings)
            if heat.empty:
                st.info(f"No hay operaciones con {kind}/TR ≥ {settings.loss_threshold_pct:g}% en semanas comparables bajo el objetivo.")
                continue
            fig, ax = plt.subplots(figsize=(10, max(3, len(heat) * .42)))
            chart = ax.imshow(heat.to_numpy(dtype=float), cmap="YlOrRd", vmin=0, vmax=100, aspect="auto")
            ax.set_xticks(range(len(heat.columns)), [f"{year}-S{week}" for year, week in heat.columns])
            ax.set_yticks(range(len(heat)), heat.index)
            for i in range(len(heat)):
                for j in range(len(heat.columns)):
                    value = heat.iloc[i, j]
                    ax.text(j, i, f"{value:.1f}%" if pd.notna(value) else "Sin datos", ha="center", va="center", fontsize=8)
            fig.colorbar(chart, ax=ax, label=f"{kind} / TR (%)")
            fig.tight_layout()
            plot(fig)
            st.caption(f"Solo operaciones con {kind}/TR ≥ {settings.loss_threshold_pct:g}% en al menos una semana comparable bajo el objetivo.")


def main():
    st.set_page_config(page_title="LOSSIA · Análisis de producción", page_icon="🏭", layout="wide")
    st.markdown("<style>.block-container{padding-top:2rem}div[data-testid='stMetricValue']{font-size:1.7rem}</style>", unsafe_allow_html=True)
    if st.session_state.get("section", "Resumen de líneas") == "Resumen de líneas":
        st.title("LOSSIA")
    with st.sidebar:
        st.header("Datos y alcance")
        with st.expander("Archivos de entrada"):
            st.caption("Por defecto se leen los CSV de data/. También puedes cargar otros archivos con el mismo esquema.")
            source = st.file_uploader("Producción", type="csv")
            config = st.file_uploader("Configuración", type="csv")
            calendar_file = st.file_uploader("Calendario de fábrica (opcional)", type="csv")
            st.caption("Calendario: Linea, Year, Week, Jour, Planned_Production (0/1); Planned_Hours y Motivo opcionales.")
            decimal = st.selectbox("Separador decimal", [".", ","])
            unit = st.selectbox("Unidad de los tiempos de entrada", ["hours", "minutes", "seconds"],
                                format_func=lambda value: {"hours": "Horas", "minutes": "Minutos", "seconds": "Segundos"}[value])
        with st.expander("Objetivos y umbrales"):
            availability = st.number_input("Objetivo de funcionamiento / TR (%)", 1.0, 99.9, 90.0)
            st.caption("Funcionamiento = TBF / (TBF + TAP + DES + SAT). Solo se activan señales de parada por debajo de este objetivo.")
            cycle = st.number_input("Objetivo de ciclo (cmin/pieza)", 0.1, value=80.0)
            loss = round(100 - availability, 10)
            st.caption(f"El umbral para distinguir pérdidas se deriva del objetivo: 100 − {availability:g} = {loss:g}% de TR.")
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
        connections = None
        sources = {"Producción": source_identity(source, "datos_hackaton.csv"),
                   "Configuración": source_identity(config, "config_hackaton.csv"),
                   "Calendario": f"{calendar_file.name} | SHA-256 {sha256(calendar_file.getvalue()).hexdigest()}" if calendar_file else "No aportado",
                   "Conexiones": "No aportadas"}
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
            st.session_state["section"] = "Resumen de líneas"
        line = st.session_state.get("line")
        available_weeks = sorted({(int(row.Year), int(row.Week)) for row in prepared.days.itertuples()})
        weeks = st.multiselect("Semanas", available_weeks, default=available_weeks,
                               format_func=lambda value: f"{value[0]} · semana {value[1]}")
        scenario_label = st.selectbox("Tratamiento de días", list(SCENARIOS))
        section = st.session_state.get("section", "Resumen de líneas")
        if section != "Resumen de líneas":
            st.button("Volver a líneas", key="back_to_lines", on_click=open_summary)
    if not weeks:
        st.info("Selecciona al menos una semana.")
        st.stop()
    scenario = SCENARIOS[scenario_label]
    records, days = select_scenario(prepared, scenario, weeks)
    result = analyse(records, days, prepared.configuration, settings)
    unconfirmed = prepared.days.loc[[tuple(row) in set(weeks) for row in prepared.days[["Year", "Week"]].to_numpy()]].day_status.eq("unconfirmed").sum()
    if unconfirmed:
        st.sidebar.warning(f"Hay {unconfirmed} días-línea sin actividad cuya causa no está confirmada. "
                   + ("Este escenario los excluye provisionalmente. " if scenario == "provisional" else "Este escenario los incluye. ")
                   + "Para consultar las razones de no actividad de un día, sube un calendario de fábrica en Archivos de entrada e incluye la columna Motivo.")
    operations = result.operations.loc[result.operations.Linea.eq(line)]
    if section == "Resumen de líneas":
        summary_view(result, prepared.configuration)
    elif operations.empty:
        st.header("Mapa de operaciones")
        st.info("Esta línea no tiene jornadas incluidas en el periodo y escenario seleccionados.")
    else:
        line_records = records.loc[records.Linea.eq(line)]
        operations_view(operations, records.loc[records.Linea.eq(line)], days.loc[days.Linea.eq(line)], settings,
                        scenario_label, connections, sources)
        st.divider()
        st.header("Análisis de la línea")
        analysis = st.radio("Análisis de la línea", ANALYSES, horizontal=True, key="line_analysis", label_visibility="collapsed")
        if analysis == "Microparadas":
            microstop_view(operations, settings, line_records)
        elif analysis == "Máquinas más problemáticas":
            problematic_view(result, line, operations, settings)
        else:
            st.header(analysis)
            ordering = st.selectbox("Orden de las máquinas", ["Orden de línea", "De menor TBF a mayor TBF"], key="times_order")
            timed = operations.loc[operations.TR.gt(0)]
            timed = timed.sort_values(["TBF", "Orden_OP", "Operacion"]) if ordering == "De menor TBF a mayor TBF" else order_operations(timed)
            time_mix(timed)


if __name__ == "__main__":
    main()
