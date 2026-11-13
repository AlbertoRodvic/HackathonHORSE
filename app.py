"""Ejecutar con: python -m streamlit run app.py"""

from html import escape
from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from analysis import Settings, STATUS_COLORS, TIME_COLORS, analyse, priorities
from cleaning import DAY_KEYS, DAY_LABELS, FLAGS, TIMES, VALUES, prepare_data, select_scenario

ROOT = Path(__file__).resolve().parent
SECTIONS = ["Resumen de líneas", "Operaciones", "Microparadas", "Evolución", "Calendario y calidad"]
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


def open_operation(operation):
    st.session_state["selected_operation"] = operation


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
            cols[3].metric("TAP / TR comparable", number(row.own_loss_pct, "%"))
            st.caption(f"{row.review_operations} operaciones requieren revisar datos o cobertura. "
                       "Una operación puede tener señales de varios tipos.")
            st.button("Ver operaciones", key=f"line_{row.Linea}", on_click=open_line, args=(row.Linea,))
    if result.lines.empty:
        st.info("No hay líneas con jornadas incluidas en el escenario seleccionado.")


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


def operations_view(operations, records, settings):
    st.header("Operaciones de la línea")
    st.caption("Orden de configuración; no representa ubicación física ni conexiones entre ramas paralelas.")
    ranking = priorities(operations).head(3)
    if not ranking.empty:
        st.subheader("Primero, investigar estas pérdidas propias")
        table(ranking[["Operacion", "TAP_pct", "TAP", "availability_pct", "recurrence_own", "recommendation"]])
    if st.session_state.get("selected_operation") not in operations.Operacion.tolist():
        st.session_state["selected_operation"] = operations.iloc[0].Operacion
    selected = st.selectbox("Selecciona una operación", operations.Operacion.tolist(), key="selected_operation")
    diagnostic(operations.loc[operations.Operacion.eq(selected)].iloc[0], settings)
    st.subheader("Mapa de patrones del periodo")
    legend = " · ".join(f'<span style="color:{color}">● {escape(status)}</span>'
                        for status, color in STATUS_COLORS.items())
    st.markdown(legend, unsafe_allow_html=True)
    show_all = st.checkbox("Mostrar también operaciones sin alertas", value=False)
    visible = operations if show_all else operations.loc[operations.status.ne("Sin alertas")]
    if "Zona" in visible and visible.Zona.notna().any():
        zones = ["Todas"] + sorted(visible.Zona.dropna().unique().tolist())
        zone = st.selectbox("Zona documentada", zones)
        if zone != "Todas":
            visible = visible.loc[visible.Zona.eq(zone)]
    st.caption(f"Mostrando {len(visible)} de {len(operations)} operaciones. "
               "El color resume el periodo, no un estado en tiempo real. Pulsa Ver para abrir el detalle.")
    for start in range(0, len(visible), 5):
        for column, (_, row) in zip(st.columns(5), visible.iloc[start:start + 5].iterrows()):
            with column:
                color = STATUS_COLORS[row['status']]
                st.markdown(f'<div style="border:1px solid #dfe4ec;border-top:5px solid {color};'
                            f'border-radius:8px;padding:12px;min-height:112px">'
                            f'<b>{escape(str(row.Operacion))}</b><br>'
                            f'<span style="font-size:13px">{escape(row["status"])}</span><br>'
                            f'<small>Orden {row.Orden_OP:g} · TAP {number(row.TAP_pct, "%")}</small></div>',
                            unsafe_allow_html=True)
                st.button(f"Ver {row.Operacion}", key=f"operation_{row.Operacion}",
                          on_click=open_operation, args=(row.Operacion,), width="stretch")
    with st.expander("Reparto de tiempos por operación"):
        st.caption("Cada barra es una operación. Las operaciones sin registros no se representan como ceros.")
        time_mix(visible.loc[visible.TR.gt(0)])
    with st.expander("Registros diarios de la operación seleccionada"):
        table(records.loc[records.Operacion.eq(selected), ["Source_Row"] + DAY_KEYS + ["Operacion"] + VALUES])


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
    st.set_page_config(page_title="LOSSIA · Análisis de producción", page_icon="🏭", layout="wide")
    st.markdown("<style>.block-container{padding-top:2rem}div[data-testid='stMetricValue']{font-size:1.7rem}</style>", unsafe_allow_html=True)
    st.title("LOSSIA")
    st.caption("Del registro de paradas a una investigación concreta · Análisis por línea y operación")
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
        section = st.radio("Sección", SECTIONS, key="section")
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
    if section == "Calendario y calidad":
        quality_view(prepared, settings, weeks)
    elif section == "Resumen de líneas":
        summary_view(result)
    elif operations.empty:
        st.info("Esta línea no tiene jornadas incluidas en el periodo y escenario seleccionados. Revisa Calendario y calidad.")
    elif section == "Operaciones":
        operations_view(operations, records.loc[records.Linea.eq(line)], settings)
    elif section == "Microparadas":
        microstop_view(operations, settings)
    else:
        evolution_view(result, line, operations)
    if not operations.empty:
        st.download_button("Descargar indicadores de esta línea", operations.to_csv(index=False).encode("utf-8-sig"),
                           file_name="indicadores_operaciones.csv", mime="text/csv")
    with st.expander("Cómo interpretar los resultados"):
        st.markdown("**Disponibilidad propia:** TBF / (TBF + TAP). **Funcionamiento sobre TR:** TBF / (TBF + TAP + DES + SAT). "
                    "**FPM:** NAP / NPR × 1.000. **Media de parada:** TAP en horas × 60 / NAP, en minutos. "
                    "**Ciclo:** TBF en horas × 6.000 / NPR, en cmin/pieza. Un denominador cero da un valor no definido.")
        st.write("Rojo: señal propia; amarillo: DES; naranja: SAT; morado: patrón mixto; azul: ciclo elevado; "
                 "verde: sin alertas con los umbrales actuales; gris: falta de producción o revisión de datos. "
                 "Mixto combina señal propia e inducida, o DES y SAT sin predominio claro (factor 1,5).")
        st.write("Los agregados diarios no permiten demostrar propagación, medir buffers ni confirmar microparadas. "
                 "No se suman piezas de operaciones distintas como producción final de línea.")


if __name__ == "__main__":
    main()
