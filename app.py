"""Ejecutar con: python -m streamlit run app.py"""

from html import escape
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from analysis import (Settings, STATUS_COLORS, TIME_COLORS, analyse, order_operations, priorities,
                      OTHER_STATUSES, map_categories, propagation_evidence, state_explanation, validate_connections)
from cleaning import DAY_KEYS, DAY_LABELS, FLAGS, TIMES, VALUES, prepare_data, select_scenario
from reports import operation_report, technical_report, text_color
from diagnostics import (critical_candidates, impact_pairs, impact_summary, microstop_assessment,
                         priority_figure, total_stops)

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
                 "recurrence_sat": "Semanas SAT", "evaluable_week": "Semanas evaluables"}
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
    st.session_state["map_filters"] = []


def open_summary():
    st.session_state["section"] = "Resumen de líneas"


def open_operation(operation):
    st.session_state["selected_operation"] = operation


def reset_operation():
    st.session_state["selected_operation"] = None
    st.session_state["map_filters"] = []


def toggle_map():
    st.session_state["map_expanded"] = not st.session_state.get("map_expanded", False)


def source_identity(upload, filename):
    content = upload.getvalue() if upload is not None else (ROOT / "data" / filename).read_bytes()
    name = upload.name if upload is not None else filename
    return f"{name} | SHA-256 {sha256(content).hexdigest()}"


def summary_view(result, configuration):
    st.header("Una vista de cada línea")
    for line in sorted(configuration.Linea.unique()):
        operations = result.operations.loc[result.operations.Linea.eq(line)]
        below = operations.loc[operations.eligible & operations.availability_pct.lt(90)]
        color = STATUS_COLORS["Parada propia" if not below.empty else "Buen funcionamiento" if operations.eligible.any() else "Otros"]
        with st.container(border=True):
            st.markdown(f'<div style="border-left:5px solid {color};padding-left:14px">'
                        f'<h3 style="margin:0">{escape(str(line))}</h3></div>', unsafe_allow_html=True)
            st.metric("Máquinas con disponibilidad propia < 90%", len(below))
            if not below.empty:
                table(below[["Operacion", "availability_pct"]])
            elif operations.empty:
                st.info("Sin jornadas incluidas para esta línea en el periodo y escenario seleccionados.")
            else:
                st.caption("Ninguna máquina evaluable tiene disponibilidad propia inferior al 90%.")
            st.button("Ver operaciones", key=f"line_{line}", on_click=open_line, args=(line,), type="primary")
            st.download_button("Descargar indicadores de esta línea", operations.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"indicadores_{line}.csv", mime="text/csv", key=f"download_line_{line}",
                               disabled=operations.empty)


def others_view(operations):
    others = operations.loc[operations.status.isin(OTHER_STATUSES)]
    if others.empty:
        return
    st.subheader("Otros")
    actions = {
        "Sin producción": ("Sin producción", "Jefe de Unidad: confirmar si estas máquinas debían producir y su planificación. "
                           "Mantenimiento: si debían trabajar, investigar la parada total y registrar la causa."),
        "Revisar datos": ("Revisa datos", "Jefe de Unidad: completar las jornadas que faltan y contrastar la producción registrada. "
                         "Mantenimiento: comprobar contadores, sensores y coherencia de los tiempos."),
        "Sin datos": ("Sin datos", "Jefe de Unidad: confirmar si las máquinas estaban previstas y localizar sus registros. "
                     "Mantenimiento: revisar la captura de datos si faltan registros de máquinas que estaban activas."),
    }
    for status, (label, action) in actions.items():
        group = others.loc[others.status.eq(status)]
        if not group.empty:
            with st.expander(f"{label} · {len(group)} máquinas"):
                st.write("**Máquinas:** " + ", ".join(group.Operacion.astype(str)))
                st.write(action)
                table(group[["Operacion", "observed_days", "expected_days", "recommendation"]])


def diagnostic(row, settings):
    st.subheader(f"Detalle · {row.Operacion}")
    st.write(f"**{row['status']}** · {row.recommendation}")
    cols = st.columns(5)
    cols[0].metric("Disponibilidad propia", number(row.availability_pct, "%"))
    cols[1].metric("Parada propia", number(row.TAP, " h"))
    cols[2].metric("Media por parada", number(row.mean_stop_minutes, " min", 2))
    cols[3].metric(f"Paradas / {settings.stop_rate_base} piezas", number(row.fpm))
    cols[4].metric("Ciclo de funcionamiento", number(row.cycle_cmin, " cmin"))
    if not row.stop_duration_reliable and pd.notna(row.mean_stop_minutes):
        st.warning("La media TAP/NAP se puede calcular, pero hay días con tiempos y contadores "
                   "incompatibles. No se usa para señalar posibles microparadas.")
    st.caption(f"Días con datos: {int(row.observed_days)} de {int(row.expected_days)}. "
               f"Semanas evaluables: {int(row.evaluable_week)}. Señales semanales: "
               f"TAP {int(row.recurrence_own)}, DES {int(row.recurrence_des)}, SAT {int(row.recurrence_sat)}.")
    table(pd.DataFrame([row])[["Operacion", "TBF_pct", "TAP_pct", "DES_pct", "SAT_pct", "NPR", "NAP", "stop_pattern"]])


def operations_view(operations, records, days, settings, scenario, connections, sources):
    st.header("Mapa de operaciones")
    st.caption("Cada caja es una operación. Desliza la fila o abre la vista completa; pulsa una caja para ver su diagnóstico debajo.")
    controls = st.columns([1.1, 1.8, 1.2])
    ordering = controls[0].selectbox("Ordenar por", ["Orden de línea", "Urgencia"], key="map_order")
    categories = map_categories(operations)
    available = [name for name in STATUS_COLORS if name in set(categories)]
    filters = controls[1].multiselect("Filtrar por categoría", available, key="map_filters")
    with controls[2]:
        st.write("")
        st.button("Volver a fila horizontal" if st.session_state.get("map_expanded", False) else "Ver todas en pantalla",
                  key="toggle_map", on_click=toggle_map, width="stretch")
    visible = order_operations(operations, urgent=ordering == "Urgencia")
    if filters:
        visible = visible.loc[map_categories(visible).isin(filters)]
    if "Zona" in visible and visible.Zona.notna().any():
        zone = st.selectbox("Zona documentada", ["Todas"] + sorted(visible.Zona.dropna().unique().tolist()))
        if zone != "Todas":
            visible = visible.loc[visible.Zona.eq(zone)]
    present = set(map_categories(visible))
    legend = " · ".join(f'<span style="color:{STATUS_COLORS[status]}">● {escape(status)}</span>'
                        for status in available if status in present)
    st.markdown(legend, unsafe_allow_html=True)
    st.caption(f"Mostrando {len(visible)} de {len(operations)} operaciones. "
               + ("Se muestran las categorías seleccionadas. " if filters else "Sin filtros: se muestran todas. ")
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
        background = STATUS_COLORS[row['status']]
        foreground = text_color(background)
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
    others_view(visible)
    if selected is None:
        st.info("Selecciona una operación en el mapa para ver su estado, evidencias y PDF de diagnóstico.")
    else:
        st.divider()
        row = operations.loc[operations.Operacion.eq(selected)].iloc[0]
        diagnostic(row, settings)
        with st.expander("Por qué tiene este color"):
            for reason in state_explanation(row, settings):
                st.write(reason)
        pdf = operation_report(row, records, days, settings, scenario, connections=connections, source_info=sources)
        filename = "diagnostico_" + sha256(f"{row.Linea}/{selected}".encode()).hexdigest()[:10] + ".pdf"
        st.download_button("Descargar diagnóstico PDF", pdf, file_name=filename, mime="application/pdf", on_click="ignore", type="primary")
        with st.expander("Posibles efectos sobre otras operaciones y fuentes de espera"):
            st.caption("Coincidencias diarias, no causalidad demostrada. Sin conexiones aportadas no se conoce la dirección del efecto.")
            evidence = propagation_evidence(row, records, settings, connections)
            table(evidence)
        st.subheader("Registros diarios de la operación seleccionada")
        table(records.loc[records.Operacion.eq(selected), ["Source_Row"] + DAY_KEYS + ["Operacion"] + VALUES])


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
            ("Cian · DES", "Señal de falta de suministro sin otra señal de parada."),
            ("Violeta · SAT", "Señal de bloqueo de salida sin otra señal de parada."),
            ("Azul · Mixto", "Señales propias e inducidas, o DES y SAT a la vez."),
            ("Verde · Buen funcionamiento", f"Disponibilidad ≥ {settings.availability_target:g}% sin señales DES/SAT."),
        ]]))
    st.write(f"DES o SAT se activan al alcanzar {settings.loss_threshold_pct:g}% de TR. "
             "Si solo la suma supera el umbral, se usa predominio 1,5; si no hay predominio, se activan ambas señales.")
    st.write("La urgencia ordena primero pérdidas propias comparables, después flujo, revisión de datos y seguimiento. "
             "Dentro de cada grupo prioriza porcentaje de pérdida, recurrencia y horas TAP. No estima responsabilidad causal.")


def interpretation_view(operations, settings, analysis):
    with st.expander("Cómo interpretar los resultados"):
        explanations = {
            "Parada propia": "Rojo: disponibilidad propia inferior al 90%.",
            "Buen funcionamiento": "Verde: disponibilidad propia ≥ 90% sin señales de desabastecimiento o saturación.",
            "Desabastecimiento": "Cian: señal de falta de suministro (DES).",
            "Saturación": "Violeta: señal de bloqueo de salida (SAT).",
            "Mixto": "Azul, mezcla de cian y violeta: dos o más señales propias o inducidas coinciden.",
            "Otros": "Gris: sin producción, revisión de datos o sin datos. Consulta las acciones debajo del mapa.",
        }
        for status in STATUS_COLORS:
            if status in set(map_categories(operations)):
                st.write(explanations[status])
        st.write("Disponibilidad propia = TBF / (TBF + TAP) × 100. "
                 "El color resume el periodo seleccionado; no representa el estado instantáneo.")
        st.write(f"DES y SAT se activan desde {settings.loss_threshold_pct:g}% del tiempo registrado. "
                 "Si solo su suma alcanza el umbral, se usa predominio 1,5; sin predominio se señalan ambas.")
        if st.session_state.get("selected_operation") is not None:
            st.write(f"Media de parada = TAP (h) × 60 / NAP; FPM = NAP / NPR × {settings.stop_rate_base}; "
                     "ciclo = TBF (h) × 6.000 / NPR. Un denominador cero deja el indicador sin definir.")
        if analysis == "Microparadas":
            st.write(f"FPM = NAP / NPR × {settings.stop_rate_base}. Media de parada = TAP (h) × 60 / NAP. "
                     f"Los indicios combinan frecuencia ≥ P75 de la línea y media < {settings.short_stop_minutes:g} min "
                     "con datos consistentes. Los agregados diarios no confirman microparadas individuales.")
        elif analysis == "Evolución":
            st.write("Las barras muestran el reparto diario de horas-máquina. La recurrencia cuenta semanas evaluables "
                     "con señal; no permite saber si fue la misma avería o varios eventos.")
        elif analysis == "Calendario y calidad":
            st.write("El escenario determina qué días se incluyen. Sin datos no significa producción cero. "
                     "Confirma los cierres con la planificación de fábrica; Year/Week/Jour identifican días registrados.")
        elif analysis == "Reparto de tiempos por operación":
            st.write("Cada barra reparte TR = TBF + TAP + DES + SAT: funcionamiento, parada propia, "
                     "desabastecimiento y saturación. Cada porcentaje divide su tiempo por TR.")
        else:
            st.write("La tabla ordena las pérdidas propias comparables por TAP/TR, recurrencia y horas TAP. "
                     "Las coincidencias con otras operaciones orientan la investigación y no demuestran causalidad.")


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
            availability = 90.0
            st.caption("Objetivo de disponibilidad propia: 90%.")
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
            st.session_state["line"] = lines[0]
        line = st.selectbox("Línea", lines, key="line", on_change=reset_operation)
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
        st.divider()
        analysis = st.radio("Análisis de la línea", ANALYSES, horizontal=True, key="line_analysis")
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
        interpretation_view(operations, settings, analysis)


if __name__ == "__main__":
    main()
