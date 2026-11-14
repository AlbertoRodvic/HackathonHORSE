"""Ejecutar con: python -m streamlit run app.py"""

from html import escape
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Streamlit renderiza imágenes; no debe iniciar ventanas Tk.
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from analysis import (Settings, STATUS_COLORS, MIXED_BACKGROUND, TIME_COLORS, analyse, order_operations, priorities,
                      OTHER_STATUSES, map_categories, propagation_evidence, validate_connections)
from cleaning import BALANCE_LABELS, DAY_KEYS, DAY_LABELS, FLAGS, TIMES, VALUES, prepare_data, select_scenario
from reports import operation_report, technical_report, classification_report, text_color
from diagnostics import (critical_candidates, impact_pairs, impact_summary, microstop_assessment,
                         investigation_figure, priority_figure, total_stops)

ROOT = Path(__file__).resolve().parent
ANALYSES = ["Microparadas", "Evolución", "Calendario y calidad", "Reparto de tiempos por operación", "Pérdidas propias"]
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
FLAG_LABELS = dict(zip(FLAGS, ["Producción sin funcionamiento", "Funcionamiento sin producción",
                              "Paradas sin tiempo propio", "Tiempo propio sin paradas contadas"]))


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
    st.session_state["map_data_group"] = "Con datos"


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
    st.caption("Líneas ordenadas de mayor a menor número de máquinas con problemas. "
               "Cada máquina cuenta una vez si presenta una señal operativa o requiere revisar planificación o datos.")
    problems = result.operations.loc[result.operations.status.ne("Buen funcionamiento")].groupby("Linea").size()
    lines = sorted(configuration.Linea.unique(), key=lambda name: (-int(problems.get(name, 0)), str(name)))
    for line in lines:
        operations = result.operations.loc[result.operations.Linea.eq(line)]
        color = STATUS_COLORS["Parada propia" if problems.get(line, 0) else "Buen funcionamiento" if operations.eligible.any() else "Otros"]
        with st.container(border=True):
            st.markdown(f'<div style="border-left:5px solid {color};padding-left:14px">'
                        f'<h3 style="margin:0">{escape(str(line))}</h3></div>', unsafe_allow_html=True)
            st.metric("Máquinas con problemas", int(problems.get(line, 0)))
            if operations.empty:
                st.info("Sin jornadas incluidas para esta línea en el periodo y escenario seleccionados.")
            st.button("Ver operaciones", key=f"line_{line}", on_click=open_line, args=(line,), type="primary")


def others_view(operations, settings):
    others = operations.loc[operations.status.isin(OTHER_STATUSES)]
    if others.empty:
        return
    st.header("Revisión prioritaria")
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
    for status, (label, action) in actions.items():
        group = others.loc[others.status.eq(status)]
        if not group.empty:
            with st.expander(f"{label} · {len(group)} máquinas", expanded=True):
                st.write("**Máquinas:** " + ", ".join(group.Operacion.astype(str)))
                st.write(action)
                if status == "Revisar datos":
                    st.caption("Valores registrados pendientes de validar. La cobertura o coherencia de estos datos "
                               "impide usarlos como diagnóstico definitivo; una disponibilidad indefinida no equivale a cero.")
                    plot(investigation_figure(group, settings))
                table(group[["Linea", "Operacion", "TBF", "TAP", "NPR", "coverage_pct",
                             "observed_days", "expected_days", "recommendation"]])
    st.divider()


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
    st.caption("Cada caja es una operación. Desliza la fila o abre la vista completa; pulsa una caja para ver su diagnóstico debajo.")
    controls = st.columns([1.1, 1.8, 1.2])
    sort_mode = controls[0].selectbox("Organizar máquinas", ["Por orden de línea", "Por disponibilidad de datos"], key="map_organization")
    available = [name for name in STATUS_COLORS if name in set(map_categories(operations))]
    visible = order_operations(operations)
    if sort_mode == "Por disponibilidad de datos":
        availability_group = controls[1].selectbox("Disponibilidad de datos", ["Con datos", "Revisar datos", "Sin datos"], key="map_data_group")
        if availability_group == "Con datos":
            visible = visible.loc[visible.eligible]
            order_mode = st.selectbox("Orden para máquinas con datos", ["Por orden de línea", "Por urgencia de reparación"], key="map_order")
            if order_mode == "Por urgencia de reparación":
                repair_group = st.selectbox("Tipo de señal", ["Todas", "Parada propia", "Desabastecimiento", "Saturación", "Mixto", "Sin alertas"], key="map_signal")
                if repair_group == "Sin alertas":
                    visible = visible.loc[visible.status.isin(["Buen funcionamiento", "Elementos lentos"])]
                    detail = st.selectbox("Dentro de Sin alertas", ["Todos", "Buen funcionamiento", "Elementos lentos"], key="map_no_alerts")
                    if detail != "Todos":
                        visible = visible.loc[visible.status.eq(detail)]
                elif repair_group != "Todas":
                    visible = visible.loc[visible.status.eq(repair_group)]
                visible = order_operations(visible, urgent=True)
        elif availability_group == "Revisar datos":
            visible = visible.loc[visible.status.isin(["Revisar datos", "Sin producción"])]
        else:
            visible = visible.loc[visible.status.eq("Sin datos")]
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
               + "Los filtros de disponibilidad no cambian los colores. "
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
    below = operations.loc[operations.eligible & operations.TBF_pct.lt(settings.availability_target)]
    if not below.empty:
        st.subheader(f"Máquinas con funcionamiento / TR < {settings.availability_target:g}% · {len(below)}")
        plot(investigation_figure(below, settings))
    others_view(operations, settings)
    if selected is None:
        st.info("Selecciona una operación en el mapa para ver su estado, evidencias y PDF de diagnóstico.")
    else:
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


def own_losses_view(operations, records, settings, connections):
    st.header("Pérdidas propias")
    ranking = priorities(operations)
    table(ranking[["Operacion", "TAP_pct", "TAP", "availability_pct", "recurrence_own", "recommendation"]])
    with st.expander("Validar el alcance sobre todas las otras operaciones"):
        candidates = critical_candidates(operations, records)
        st.caption("Segundo paso tras identificar pérdidas propias. Se comparan días con y sin señal propia; "
                   "hacen falta al menos 3 días en cada grupo. Una asociación positiva no demuestra causalidad.")
        if candidates.empty:
            st.info("No hay candidatas con los criterios y el escenario elegidos.")
        else:
            name = st.selectbox("Candidata para estudiar impacto", candidates.Operacion.tolist())
            pairs = impact_pairs(candidates.loc[candidates.Operacion.eq(name)], operations, records, settings, connections)
            table(impact_summary(pairs))
            st.caption("Se incluyen todas las demás operaciones. Sin conexiones reales no se atribuye dirección. "
                       "Cero coincidencias o falta de días de control no demuestra ausencia de impacto. "
                       "Los campos time_mismatch_days permiten revisar la sensibilidad al balance horario.")
            table(pairs)
            st.download_button("Descargar comparación completa de impacto", pairs.to_csv(index=False).encode("utf-8-sig"),
                               file_name="impacto_operacion.csv", mime="text/csv")
    with st.expander("Paradas totales: investigación separada"):
        st.caption("TBF=0, NPR=0 y tiempo registrado. Prioridad alta si la línea debía producir o hay actividad en "
                   "otras operaciones; confirmar siempre que esta operación concreta debía trabajar.")
        table(total_stops(records))


def microstop_view(operations, settings, records):
    st.header("Frecuencia y duración de las paradas")
    cards = st.columns(3)
    cards[0].metric("Operaciones con media consistente", int((operations.eligible & operations.stop_duration_reliable).sum()))
    cards[1].metric("Señal de frecuentes y breves", int(operations.short_frequent_signal.sum()))
    cards[2].metric("Media de parada prolongada", int((operations.eligible & operations.stop_duration_reliable & operations.mean_stop_minutes.ge(settings.long_stop_minutes)).sum()))
    st.caption("A la derecha: más paradas por pieza. Abajo: paradas más breves. El tamaño muestra horas de TAP.")
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
    with st.expander("Datos y cálculo de la media"):
        st.write("Media por parada = TAP × 60 / NAP, en minutos. Se suman tiempos y contadores antes de dividir.")
        table(operations[["Operacion", "NAP", "TAP", "fpm", "mean_stop_minutes", "stop_duration_reliable", "stop_pattern"]])
    st.subheader("Dónde son potencialmente relevantes")
    st.caption(f"Análisis diario separado del color: media < {settings.short_stop_minutes:g} min y FPM >= P75 de la línea "
               f"con días fiables. Relevante si el TAP de los días compatibles alcanza {settings.microstop_loss_threshold_pct:g}% "
               "del TR de días válidos. No son averías grandes confirmadas: el TAP mostrado puede incluir eventos largos.")
    summary, detail = microstop_assessment(records, settings)
    table(summary.loc[summary.brief_frequent_days.gt(0)])
    with st.expander("Días y registros con indicios de microparadas"):
        table(detail)


def evolution_view(result, line, operations, settings):
    st.header("Evolución y recurrencia")
    st.subheader("Disponibilidad, pérdidas y otros indicadores de las prioritarias")
    comparison = priority_figure(operations, settings)
    if comparison is not None:
        plot(comparison)
    st.subheader("Reparto diario de horas-máquina")
    st.caption("Cada barra suma las operaciones registradas de un día; no mide el tiempo parada de la línea.")
    time_mix(result.daily.loc[result.daily.Linea.eq(line)], daily=True)
    st.subheader("Qué pérdidas se repiten")
    count = st.slider("Operaciones en los mapas", 1, len(operations), min(12, len(operations))) if len(operations) > 1 else 1
    weekly = result.weekly.loc[result.weekly.Linea.eq(line)]
    for tab, kind in zip(st.tabs(["Parada propia · TAP", "Desabastecimiento · DES", "Saturación · SAT"]), ["TAP", "DES", "SAT"]):
        with tab:
            selected = operations.sort_values(f"{kind}_pct", ascending=False).head(count).Operacion.tolist()
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


def hour_balance_view(records, *, key):
    """Etiquetas visibles y descargables; filtrar esta tabla no cambia el análisis."""
    if records.empty:
        st.info("No hay registros utilizables para comprobar el balance en este alcance.")
        return
    counts = records.balance_label.value_counts().reindex(BALANCE_LABELS, fill_value=0)
    for column, label in zip(st.columns(4), BALANCE_LABELS):
        column.metric(label, int(counts[label]))
    bands = records.balance_band_minutes.unique()
    st.caption(f"Balance = TBF + TAP + DES + SAT frente a la referencia de cada jornada. "
               f"Banda orientativa: ±{number(float(bands[0]), ' min', 2)}. "
               "Estar en banda no demuestra que el registro sea correcto. Sin tiempo asignado significa que las cuatro categorías suman cero.")
    labels = st.multiselect("Etiquetas de balance visibles", list(BALANCE_LABELS), default=list(BALANCE_LABELS), key=f"{key}_labels")
    detail = records.loc[records.balance_label.isin(labels)].sort_values(DAY_KEYS + ["Operacion"])
    columns = ["Source_Row"] + DAY_KEYS + ["Operacion"] + VALUES + ["recorded_hours", "reference_hours", "balance_delta_minutes", "balance_label"]
    table(detail[columns])
    st.caption("Déficit: revisar categorías, jornada y captura. Exceso: revisar solapes, ventanas y unidades. "
               "Tiempo cero: confirmar planificación o ausencia de captura. Ninguna etiqueta diagnostica por sí sola una avería.")
    st.download_button("Descargar registros con etiqueta de balance", detail[columns].to_csv(index=False).encode("utf-8-sig"),
                       file_name="balance_horario.csv", mime="text/csv", key=f"{key}_download")


def quality_view(prepared, settings, weeks):
    st.header("Calendario y calidad de los datos")
    st.subheader("Balance horario por registro")
    balance_records, _ = select_scenario(prepared, "all", weeks)
    balance_lines = ["Todas"] + sorted(prepared.configuration.Linea.unique().tolist())
    scope_line = st.selectbox("Línea del balance horario", balance_lines, key="quality_balance_line")
    if scope_line != "Todas":
        balance_records = balance_records.loc[balance_records.Linea.eq(scope_line)]
    st.caption("Semanas seleccionadas, incluyendo días sin actividad y cierres. Este bloque conserva todas las etiquetas para auditar el registro original.")
    hour_balance_view(balance_records, key="quality_balance")
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
    table(days[DAY_KEYS + ["Estado", "Motivo", "observed_operations", "expected_operations", "complete_coverage"]])
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


def report_view(prepared, records, days, result, settings, scenario, sources, connections, context, weeks):
    st.header("El criterio unificado, explicado")
    st.write("La misma regla decide el color, los filtros, la recurrencia y la explicación del PDF. "
             "El informe incluye EDA, limpieza, matemáticas, gráficas, escalabilidad y límites del diagnóstico.")
    st.caption("El informe general abarca todas las líneas cargadas y las semanas y escenario seleccionados.")
    if st.button("Preparar informe técnico PDF", type="primary"):
        with st.spinner("Preparando el informe con las gráficas y la evidencia seleccionada…"):
            data = technical_report(prepared, records, days, result, settings, scenario, connections=connections, source_info=sources, selected_weeks=weeks)
        st.session_state["technical_report"] = (context, data)
    saved = st.session_state.get("technical_report")
    if saved and saved[0] == context:
        st.download_button("Descargar informe técnico PDF", saved[1], file_name="informe_tecnico_LOSSIA.pdf",
                           mime="application/pdf", on_click="ignore", type="primary")
    st.subheader("Cómo se asigna el estado")
    table(pd.DataFrame([
        {"Color": name, "Regla": rule} for name, rule in [
            ("Gris · Sin datos", "Sin registros; no significa producción cero."),
            ("Gris · Revisar datos", "Cobertura incompleta o tiempos y producción contradictorios."),
            ("Gris · Sin producción", "NPR=0 y TBF=0: confirmar actividad prevista o parada total."),
            ("Rojo · Parada propia", f"Disponibilidad < {settings.availability_target:g}%, sin señales inducidas."),
            ("Amarillo · DES", "Señal de falta de suministro sin otra señal de parada."),
            ("Naranja · SAT", "Señal de bloqueo de salida sin otra señal de parada."),
            ("Naranja y amarillo · Mixto", "Señales propias e inducidas, o DES y SAT a la vez."),
            ("Azul · Buen funcionamiento", f"Sin alertas de parada y ciclo ≤ {settings.cycle_target_cmin:g} cmin/pieza."),
            ("Azul grisáceo · Elementos lentos", f"Sin alertas de parada y ciclo > {settings.cycle_target_cmin:g} cmin/pieza."),
        ]]))
    st.write(f"DES o SAT se activan al alcanzar {settings.loss_threshold_pct:g}% de TR. "
             "Si solo la suma supera el umbral, se usa predominio 1,5; si no hay predominio, se activan ambas señales.")
    st.write(f"Antes de distinguir TAP, DES y SAT se exige TBF/TR < {settings.availability_target:g}%. "
             "Si el funcionamiento alcanza el objetivo, no se activa ninguna señal de parada.")
    st.write("La urgencia ordena primero pérdidas propias comparables, después flujo, revisión de datos y seguimiento. "
             "Dentro de cada grupo prioriza porcentaje de pérdida, recurrencia y horas TAP. No estima responsabilidad causal.")


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
            connections_file = st.file_uploader("Conexiones reales entre operaciones (opcional)", type="csv")
            st.caption("Conexiones: Linea, Origen, Destino. Sirven para estudiar coincidencias aguas arriba y abajo, no para demostrar causalidad.")
            decimal = st.selectbox("Separador decimal", [".", ","])
            unit = st.selectbox("Unidad de los tiempos de entrada", ["hours", "minutes", "seconds"],
                                format_func=lambda value: {"hours": "Horas", "minutes": "Minutos", "seconds": "Segundos"}[value])
        with st.expander("Objetivos y umbrales"):
            availability = st.number_input("Objetivo de disponibilidad propia (%)", 1.0, 100.0, 90.0)
            st.caption("Este objetivo también exige TBF/TR inferior al umbral para activar señales TAP, DES o SAT.")
            cycle = st.number_input("Objetivo de ciclo (cmin/pieza)", 0.1, value=80.0)
            loss = st.number_input("Señal de pérdida sobre TR (%)", 0.1, 100.0, 10.0)
            short = st.number_input("Parada breve: media inferior a (min)", 0.1, 10.0, 2.0)
            long = st.number_input("Parada prolongada: media desde (min)", 10.1, value=15.0)
            reference = st.number_input("Referencia de horas por jornada", 0.1, value=22.0)
            balance_band = st.number_input("Banda orientativa de balance (min)", min_value=0.0, value=1.2, step=0.1, key="balance_band_minutes")
            st.caption("1,2 min corresponde al límite conjunto si cuatro campos se redondean a 0,01 h. "
                       "Si la precisión o las unidades de origen son distintas, ajusta la banda. "
                       "Es una hipótesis, no una regla para descartar registros.")
            st.caption("Umbrales exploratorios ajustables; los percentiles se calculan dentro de cada línea y periodo.")
    settings = Settings(availability_target=availability, cycle_target_cmin=cycle,
                        loss_threshold_pct=loss, short_stop_minutes=short, long_stop_minutes=long)
    try:
        raw = input_csv(source, "datos_hackaton.csv", decimal)
        configuration = input_csv(config, "config_hackaton.csv", decimal)
        calendar = read_csv(calendar_file.getvalue(), decimal) if calendar_file else None
        prepared = prepare_data(raw, configuration, calendar=calendar, time_unit=unit, reference_hours=reference,
                                balance_tolerance_hours=balance_band / 60)
        connections = validate_connections(read_csv(connections_file.getvalue(), decimal), prepared.configuration) if connections_file else None
        sources = {"Producción": source_identity(source, "datos_hackaton.csv"),
                   "Configuración": source_identity(config, "config_hackaton.csv"),
                   "Calendario": f"{calendar_file.name} | SHA-256 {sha256(calendar_file.getvalue()).hexdigest()}" if calendar_file else "No aportado",
                   "Conexiones": f"{connections_file.name} | SHA-256 {sha256(connections_file.getvalue()).hexdigest()}" if connections_file else "No aportadas"}
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
        quality_view(prepared, settings, weeks)
    else:
        line_records = records.loc[records.Linea.eq(line)]
        operations_view(operations, records.loc[records.Linea.eq(line)], days.loc[days.Linea.eq(line)], settings,
                        scenario_label, connections, sources)
        st.download_button("Descargar indicadores de esta línea", operations.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"indicadores_{line}.csv", mime="text/csv", key=f"download_line_{line}")
        st.divider()
        st.header("Análisis de la línea")
        analysis = st.radio("Análisis de la línea", ANALYSES, horizontal=True, key="line_analysis", label_visibility="collapsed")
        if analysis == "Microparadas":
            microstop_view(operations, settings, line_records)
        elif analysis == "Evolución":
            evolution_view(result, line, operations, settings)
        elif analysis == "Calendario y calidad":
            quality_view(prepared, settings, weeks)
        elif analysis == "Reparto de tiempos por operación":
            st.header(analysis)
            time_mix(operations.loc[operations.TR.gt(0)])
        else:
            own_losses_view(operations, line_records, settings, connections)


if __name__ == "__main__":
    main()
