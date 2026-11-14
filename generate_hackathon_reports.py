"""Genera dos entregables del Hackathon a partir del notebook y del código vigente.

Ejecutar: python generate_hackathon_reports.py
No modifica ni vuelve a guardar initial_exploration.ipynb.
"""

from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, PageBreak, SimpleDocTemplate, Spacer

from analysis import Settings, analyse, order_operations
from cleaning import prepare_data, select_scenario, FLAGS, TIMES
from diagnostics import microstop_points, microstop_figure
from reports import STYLES, p, table as base_table, map_drawing

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "outputs"
ASSETS = OUTPUT / "hackathon_assets"
WIDTH = A4[0] - 84
NAVY = colors.HexColor("#14253f")
TEAL = colors.HexColor("#167d8d")
ORANGE = colors.HexColor("#c66a2b")
STYLES.add(ParagraphStyle("ReportLead", parent=STYLES["BodyLossia"], fontSize=12, leading=18, spaceAfter=16))
STYLES["BodyLossia"].fontSize, STYLES["BodyLossia"].leading = 10.5, 16
STYLES["CellLossia"].fontSize, STYLES["CellLossia"].leading = 8.7, 12.5
STYLES["HeaderLossia"].fontSize, STYLES["HeaderLossia"].leading = 8.7, 12.5
STYLES.add(ParagraphStyle("ReportCaption", parent=STYLES["SmallLossia"], fontSize=8.2, leading=11.5,
                         textColor=colors.HexColor("#546477"), spaceBefore=5, spaceAfter=11))


def num(value, digits=2):
    if pd.isna(value):
        return "No definido"
    return f"{value:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def caption(text):
    return p(text, "ReportCaption")


def table(headers, rows, widths=None):
    result = base_table(headers, rows, widths)
    result.spaceAfter = 8
    return result


def frame_table(frame, columns, labels=None, digits=2, widths=None):
    rows = []
    for _, row in frame.iterrows():
        rows.append([num(row[c], digits) if isinstance(row[c], (float, np.floating)) else str(row[c]) for c in columns])
    return table(labels or columns, rows, widths)


def picture(path, max_height=280):
    image = Image(str(path))
    scale = min(WIDTH / image.imageWidth, max_height / image.imageHeight)
    image.drawWidth, image.drawHeight = image.imageWidth * scale, image.imageHeight * scale
    return image


def figure_image(fig, name, max_height=270):
    path = ASSETS / f"{name}.png"
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return picture(path, max_height)


def section(number, title, source=None):
    content = [PageBreak(), p(f"{number:02d} / {title}", "HeadingLossia")]
    if source:
        content.append(caption(source))
    return content


def cover(title, subtitle, weight, facts):
    return [Spacer(1, 42), p("LOSSIA · HACKATHON HORSE", "HeadingLossia"),
            p(title, "TitleLossia"), p(subtitle, "ReportLead"),
            p(f"Criterio de evaluación: {weight} · 14 de noviembre de 2026"), Spacer(1, 12),
            table(["Lectura rápida", "Evidencia"], facts, [170, WIDTH - 170]), Spacer(1, 17)]


def build_pdf(story, path, title, accent):
    label = title

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(accent)
        canvas.rect(0, A4[1] - 25, A4[0], 25, fill=1, stroke=0)
        canvas.setFont("Lossia-Bold", 8)
        canvas.setFillColor(colors.white)
        canvas.drawString(42, A4[1] - 16, "LOSSIA / " + label)
        canvas.setFillColor(colors.HexColor("#546477"))
        canvas.setFont("Lossia", 7)
        canvas.drawString(42, 25, "VLL_MONTAJE_L5 · Semanas 40–43 / 2026 · Evidencia diaria agregada")
        canvas.drawRightString(A4[0] - 42, 25, str(doc.page))
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=42, leftMargin=42,
                            topMargin=47, bottomMargin=44, title=title, author="Equipo LOSSIA")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def distribution_figure(frame):
    fig, axes = plt.subplots(2, 3, figsize=(12, 6))
    for axis, kind in zip(axes.flat, TIMES + ["NAP", "NPR"]):
        axis.hist(frame[kind], bins=28, color="#167d8d", edgecolor="white")
        axis.set(title=kind + (" (h)" if kind in TIMES else " (conteo)"), ylabel="Registros")
        axis.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    return fig


def notebook_micro_figure(points, seconds):
    fig, ax = plt.subplots(figsize=(11, 4.7))
    ax.scatter(points.own_stop_rate, points.mean_stop_seconds / 60,
               s=30 + 220 * points.TAP / points.TAP.max(),
               c=np.where(points.short_frequent_signal, "#d94a4a", "#167d8d"), alpha=.72)
    ax.axhline(seconds / 60, color="#d94a4a", ls="--", label=f"Media < {seconds / 60:g} min")
    ax.axvline(points.frequency_threshold.iloc[0], color="#546477", ls=":", label="P75 de FPM")
    for row in points.nlargest(3, "own_stop_rate").itertuples():
        ax.annotate(row.Operacion, (row.own_stop_rate, row.mean_stop_seconds / 60), xytext=(4, 5), textcoords="offset points", fontsize=8)
    ax.set(xscale="log", yscale="log", xlabel="Paradas propias / 1.000 piezas (log)", ylabel="Media por parada (min, log)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig


def heat_figure(matrix, label, vmax=100, cmap="YlOrRd"):
    fig, ax = plt.subplots(figsize=(10, max(2.8, len(matrix) * .38)))
    image = ax.imshow(matrix.to_numpy(dtype=float), aspect="auto", cmap=cmap, vmin=0, vmax=vmax)
    ax.set_yticks(range(len(matrix)), matrix.index)
    ax.set_xticks(range(len(matrix.columns)), [f"S{w}" for y, w in matrix.columns])
    for i in range(len(matrix)):
        for j in range(len(matrix.columns)):
            value = matrix.iloc[i, j]
            ax.text(j, i, num(value, 1) if pd.notna(value) else "ND", ha="center", va="center", fontsize=8,
                    color="white" if cmap == "YlOrRd" and value > 60 else "black")
    fig.colorbar(image, ax=ax, label=label)
    fig.tight_layout()
    return fig


def execute_notebook():
    """Recalcula las celdas en orden y captura sus figuras y tablas sin usar salidas guardadas."""
    notebook = json.loads((ROOT / "initial_exploration.ipynb").read_text(encoding="utf-8"))
    namespace = {"__name__": "__notebook_report__"}
    images, tables, log = {}, {}, StringIO()
    current = [0]

    def display(*objects, **kwargs):
        for obj in objects:
            if isinstance(obj, (pd.DataFrame, pd.Series)):
                tables.setdefault(current[0], []).append(obj.copy())

    def show(*args, **kwargs):
        for number in plt.get_fignums():
            figure = plt.figure(number)
            path = ASSETS / f"notebook_celda_{current[0]:02d}_{len(images.get(current[0], [])) + 1}.png"
            figure.savefig(path, dpi=160, bbox_inches="tight", facecolor="white")
            images.setdefault(current[0], []).append(path)
            plt.close(figure)

    ASSETS.mkdir(parents=True, exist_ok=True)
    with patch("IPython.display.display", display), patch.object(plt, "show", show), redirect_stdout(log):
        for index, cell in enumerate(notebook["cells"]):
            if cell["cell_type"] == "code":
                current[0] = index
                exec(compile("".join(cell["source"]), f"initial_exploration.ipynb:celda_{index}", "exec"), namespace)
                show()
    (ASSETS / "ejecucion_notebook.txt").write_text(log.getvalue(), encoding="utf-8")
    return namespace, images, tables


def eda_report(s, images, tables, prepared, records, result):
    points = s["stop_candidates"]
    micro_count = int(points.short_frequent_signal.sum())
    clock = s["clock_audit"]
    story = cover("Análisis exploratorio\nde datos", "Del registro diario a una investigación defendible: calidad, exposición, pérdidas y límites de interpretación.", "EDA · 30 %", [
        ["Universo observado", f"{len(s['raw_data'])} registros · {len(s['config'])} operaciones · 20 jornadas"],
        ["La planificación cambia el diagnóstico", "4 jornadas sin actividad por confirmar; el escenario provisional conserva 16."],
        ["La calidad no es una avería", "4 registros con piezas sin TBF; 65 con TBF sin piezas. Los valores originales se conservan."],
        ["Interrupciones breves", f"{micro_count} indicios con media < 1 min en el notebook; no son eventos confirmados."],
    ])
    story += [p("Conclusión principal", "HeadingLossia"),
              p("La información permite localizar operaciones y registros que merecen revisión. No permite atribuir causalidad entre máquinas, medir buffers ni convertir horas-máquina en producción final recuperable."),
              p("Origen y enfoque", "HeadingLossia"),
              p("Este documento recalcula las celdas de initial_exploration.ipynb en orden y utiliza sus tablas y figuras. Se completa con una revisión de las 18 propuestas de «Por hacer» del README. Los resultados del notebook y los de la aplicación se identifican por separado cuando cambian la definición o el umbral."),
              caption("Recorrido: contrato y calidad → calendario → distribuciones → balance diario → hipótesis → pérdidas → microparadas → recurrencia → ciclo → revisión de propuestas y validación.")]

    story += section(1, "Contrato, cobertura y calidad", "Notebook: apartados 1 y 1.1; celdas 3, 4 y 6. README: puntos 1, 4 y 13.")
    story += [p("Unidad de observación: una fila por Linea, Operacion, Year, Week y Jour. TBF, TAP, DES y SAT se interpretan como horas; NAP y NPR son contadores. La configuración define el universo de operaciones y su orden, no sus conexiones físicas."),
              table(["Comprobación", "Resultado recalculado / decisión"], [
                  ["Estructura y catálogo", f"{len(s['clean'])} filas utilizables; {len(s['config'])} operaciones presentes en las 20 jornadas observadas."],
                  ["Ausencias, copias idénticas y apartados", f"0 valores ausentes en origen; {s['audit']['identical_copies_removed']} copias retiradas; {len(s['quarantine'])} filas apartadas."],
                  ["Identificadores", "Se aplica strip; no se fusionan ST-0050, ST_0015 o sufijos. No hay colisiones al auditar separadores."],
                  ["Fechas", "Se conserva Year/Week/Jour. Falta confirmar su convención antes de crear fechas civiles."],
              ], [145, WIDTH - 145]), Spacer(1, 9),
              table(["Señal de revisión", "Registros", "Tratamiento"], [
                  ["NPR > 0 y TBF = 0", int(s['clean'].production_without_runtime.sum()), "No interpretar ciclo ni comparar el periodo como dato fiable."],
                  ["TBF > 0 y NPR = 0", int(s['clean'].runtime_without_production.sum()), "Confirmar contadores, actividad opcional o significado de funcionamiento."],
                  ["NAP > 0 y TAP = 0", int(s['clean'].stops_without_own_time.sum()), "No usar TAP/NAP como duración fiable."],
                  ["TAP > 0 y NAP = 0", int(s['clean'].own_time_without_stops.sum()), "Conservar: puede ser cierre o parada previa; no inventar incidencias."],
              ], [150, 60, WIDTH - 210]),
              p("Las señales pueden solaparse y no justifican eliminar filas automáticamente. El contraste manual con Excel solicitado en el README sigue pendiente; no se presenta como validación realizada."),
              p("Trazabilidad: cada fila preparada conserva Source_Row. Los detalles completos se guardan en los CSV de soporte del informe.")]

    story += section(2, "Calendario: sensibilidad de los resultados", "Notebook: apartados 2 y 3; celdas 8 y 10. README: puntos 2, 3 y 9.")
    scenarios = []
    for label, key in [("Todos", "all"), ("Solo cierres confirmados", "confirmed"), ("Provisional", "provisional")]:
        r, d = select_scenario(prepared, key)
        out = analyse(r, d, prepared.configuration)
        eligible = out.operations.loc[out.operations.eligible]
        scenarios.append([label, len(d), len(r), len(eligible), num(eligible.availability_pct.median()),
                          int(eligible.availability_pct.lt(90).sum())])
    story += [table(["Escenario", "Días", "Filas", "Comparables", "Mediana Dp %", "Dp < 90 %"], scenarios,
                    [125, 40, 45, 80, 110, WIDTH - 400]),
              caption("Dp = disponibilidad propia = TBF/(TBF + TAP). Es una mediana entre operaciones, no disponibilidad global de línea ni TBF/TR."),
              p("Las jornadas 2026-S40-D1, 2026-S41-D5, 2026-S42-D1 y 2026-S42-D5 tienen 91 operaciones registradas sin funcionamiento ni piezas, con TAP=22 h y NAP=0. Sus 364 registros explican toda la señal de tiempo propio sin paradas contadas."),
              p("Sin calendario de fábrica no podemos afirmar que sean festivos. El escenario provisional los excluye para explorar, pero los conserva en la preparación. Si se aporta planificación de producción, la parada total no se elimina por el mero hecho de no haber actividad."),
              table(["Dato que falta", "Por qué importa"], [
                  ["Calendario por planta y jornada", "Distingue cierres previstos de paradas cuando debía producirse."],
                  ["Actividad prevista por operación", "Que otras máquinas produzcan no demuestra que todas debieran trabajar."],
                  ["Convención de Year/Week/Jour", "Impide asignar festivos o días civiles sin una correspondencia confirmada."],
              ], [180, WIDTH - 180]),
              p("Decisión: mantener explícitos los tres escenarios y acompañar los resultados con su exposición. No borrar todas las filas con TBF=0, como proponía el borrador inicial del README.")]

    story += section(3, "Distribuciones y concentración de los datos", "Ampliación descriptiva de las variables examinadas en initial_exploration; población: 1.456 registros del escenario provisional.")
    story += [figure_image(distribution_figure(s['working']), "eda_distribuciones", 280),
              caption("Tiempos en horas y contadores en unidades originales. Se incluyen ceros; no se mezclan estas distribuciones con las cuatro jornadas excluidas provisionalmente.")]
    stats = []
    for kind in TIMES + ["NAP", "NPR"]:
        x = s['working'][kind]
        stats.append([kind, int(x.eq(0).sum()), num(x.median()), num(x.quantile(.95)), num(x.max())])
    story += [table(["Variable", "Ceros", "Mediana", "P95", "Máximo"], stats),
              p("Las distribuciones son asimétricas y contienen muchos ceros. Por eso se usan ratios de sumas, percentiles por línea y escalas logarítmicas en la nube frecuencia-duración. Un valor extremo se investiga; no se recorta por ser extremo."),
              p("NPR no se suma entre operaciones como producción final: una misma pieza puede contarse en varias estaciones. Tampoco se comparan NAP absolutos sin tener en cuenta producción y exposición.")]

    story += section(4, "Auditoría de las 22 horas: registro a registro", "Notebook: apartado 6; celdas 17–19. Cálculo con Decimal a partir del texto original del CSV.")
    story += [table(["Comprobación exacta", "Registros"], [
                  ["Total exactamente igual a 22 h", int(clock.exact_reference.sum())],
                  ["Total inferior a 22 h", int(clock.under_reference.sum())],
                  ["Total superior a 22 h", int(clock.over_reference.sum())],
                  ["Cuatro tiempos iguales a cero (subconjunto de inferiores)", int(clock.zero_total.sum())],
              ], [WIDTH - 95, 95]), Spacer(1, 10),
              frame_table(tables[17][-1], ['Supuesto', 'Banda_minutos', 'Dentro', 'Fuera'],
                          ['Criterio', 'Banda ± min', 'Dentro', 'Fuera'], widths=[WIDTH - 225, 85, 70, 70]),
              p("Las bandas representan hipótesis distintas. ±1,2 min es el límite conjunto condicional si cuatro campos se redondean a 0,01 h; ±2,4 min explora truncado; seis minutos es una tolerancia exploratoria, no una consecuencia del redondeo."),
              p("El notebook usa suma decimal exacta para evitar clasificar mal los valores frontera por coma flotante. La auditoría no rellena déficits ni recorta excesos: una discrepancia puede deberse a captura, ventanas de acumulación, solapes o una jornada realmente distinta."),
              p("No basta una media de línea próxima a 22 h: los excesos y déficits se pueden compensar. Las 16 jornadas sin ningún tiempo asignado corresponden a ST_0030; requieren confirmar actividad prevista o ausencia de captura."),
              caption("La referencia de 22 h no convierte automáticamente TR en tiempo requerido ni transforma las diferencias en pérdidas recuperables.")]

    story += section(5, "¿Los déficits se explican por microparadas?", "Notebook: apartados 6.1 y 6.2; celdas 21 y 23. Esta es una hipótesis contrastada, no una corrección aplicada.")
    story += [picture(images[23][0], 255),
              caption("Figura recalculada del notebook: asociaciones entre balance, frecuencia y duración. Las correlaciones mezclan operaciones y cargas; no identifican una causa."),
              table(["Asociación de rangos de Spearman", "Valor"], [
                  ["FPM frente al desvío absoluto de horas", num(s['clock_correlations'].loc['fpm_clock', 'abs_gap_hours'], 3)],
                  ["NAP frente al desvío absoluto de horas", num(s['clock_correlations'].loc['NAP', 'abs_gap_hours'], 3)],
                  ["Media por parada frente al desvío absoluto", num(s['clock_correlations'].loc['mean_stop_minutes_clock', 'abs_gap_hours'], 3)],
              ], [WIDTH - 100, 100]),
              p("Hay déficits incluso en registros con NAP=0 y también hay excesos, que no se explican por tiempo omitido. La asociación entre frecuencia y déficit no basta para imputar todas las horas que faltan a microparadas."),
              p("Prueba necesaria: contrastar el contrato de los contadores, sus ventanas y eventos con inicio/fin. La simulación del notebook de «minutos adicionales por parada si todo el déficit fueran paradas» es un contrafactual, no un tiempo corregido ni un hallazgo causal.")]

    story += section(6, "Dónde se acumulan pérdidas propias", "Notebook: apartado 4; celdas 12 y 13. Selección exploratoria por disponibilidad propia inferior al 90 %.")
    focus = s['priorities'].sort_values('TAP', ascending=False)
    story += [frame_table(focus, ['Operacion', 'availability_pct', 'TAP', 'TAI', 'NPR', 'weeks_below_target'],
                          ['Operación', 'Dp %', 'TAP h', 'DES+SAT h', 'Piezas', 'Semanas Dp<90'], widths=[100, 70, 75, 95, 80, WIDTH - 420]),
              caption("Cinco operaciones comparables incumplen disponibilidad propia. La gráfica de Máquinas más problemáticas usa esta misma selección; el mapa conserva su clasificación por TBF/TR."),
              picture(images[13][1], 260),
              p("PM2250 permite ilustrar la diferencia: el tiempo propio y las esperas se separan antes de decidir una actuación. ST2235 acumula TAP elevado con una frecuencia muy alta y media muy breve. No se declara que sea el origen de las esperas del resto de la línea."),
              p("Las paradas totales se revisan aparte: PM2130 presenta TBF=0, NPR=0 y 351,87 h de TAP en el escenario provisional. No desaparece por exigir producción positiva en los ratios; hay que confirmar si debía trabajar.")]
    story.append(p("En el mapa actual, «Por urgencia de reparación» agrupa por color en orden TAP, SAT, DES, mixto y funcionamiento aceptable, con los casos de datos aparte. Dentro de cada grupo ordena por TBF/TR de menor a mayor; los empates se resuelven por orden configurado y nombre. La gráfica de tiempos conserva la ordenación global por TBF/TR, sin agrupar por color."))

    story += section(7, "Microparadas: frecuencia y duración conjuntamente", "Notebook: apartado 5; celda 15. Se conserva su hipótesis exploratoria de media < 60 segundos.")
    story += [figure_image(notebook_micro_figure(points, s['MICROSTOP_MEAN_SECONDS']), "eda_microparadas", 260),
              p(f"La nube contiene {len(points)} operaciones con media consistente. Combina FPM en el cuartil superior de la línea y media < {s['MICROSTOP_MEAN_SECONDS'] / 60:g} min: {micro_count} indicios. El área representa TAP, de modo que se distingue frecuencia de tiempo acumulado."),
              table(["Definición", "Notebook / EDA", "Streamlit actual"], [
                  ["Media breve", "< 1 min", "< 2 min"], ["Frecuencia alta", "FPM ≥ P75 por línea", "FPM ≥ P75 por línea"],
                  ["Operaciones en la nube", len(points), len(microstop_points(result.operations))],
                  ["Indicios agregados", micro_count, int(result.operations.short_frequent_signal.sum())],
              ]),
              p("La diferencia de 19 frente a 20 responde al umbral, no a duplicar operaciones. Ninguna media fiable de la aplicación llega a 15 min, pero una media baja puede ocultar eventos prolongados aislados."),
              p("Línea de actuación: para alta frecuencia y media breve, revisar eventos repetidos, sensores, alimentación y atascos como hipótesis. Para media mayor, contrastar incidencias y recuperación. Las medias diarias o del periodo no diagnostican por sí solas averías mecánicas.")]

    story += section(8, "Recurrencia: qué señales reaparecen", "Notebook: apartado 5; celda 15. El segundo PDF desarrolla la implementación actual por pérdida predominante.")
    chosen = s['priorities'].Operacion.tolist()
    heat = s['weekly'].pivot(index='Operacion', columns=['Year', 'Week'], values='availability_pct').reindex(chosen)
    story += [figure_image(heat_figure(heat, "Disponibilidad propia (%)", cmap="RdYlGn"), "eda_recurrencia", 245),
              caption("Mismas operaciones comparables del apartado 6. La unidad es una semana de registros, no un evento de avería."),
              frame_table(s['priorities'], ['Operacion', 'weeks_below_target', 'observed_weeks'],
                          ['Operación', 'Semanas Dp<90 %', 'Semanas observadas']),
              p("Se comparan ratios calculados después de sumar los tiempos de cada semana. Los días incluidos por semana son distintos tras excluir las jornadas sin actividad; usar solo TAP absoluto introduciría un sesgo de exposición."),
              p("El incumplimiento en varias semanas señala persistencia o recurrencia de una señal. No demuestra que sea la misma avería ni distingue una incidencia continua de episodios independientes. La solución actual amplía esta lectura a TAP, DES y SAT con elegibilidad semanal explícita."),
              p("Uso posterior a una intervención: comparar periodos con planificación, carga y producto equivalentes y comprobar si caen TAP/TR, FPM y semanas afectadas. No se entrena un predictor con estas cuatro semanas.")]

    story += section(9, "Ciclo elevado, paralelismo y esperas", "Notebook: apartado 7 y 7.1; celdas 25–29. README: puntos 6, 9, 10, 11 y 14.")
    slow = s['slow_profile']
    story += [frame_table(slow, ['Operacion', 'cycle_cmin', 'NPR', 'days_cycle_over_target', 'productive_days'],
                          ['Operación', 'Ciclo cmin', 'Piezas', 'Días ciclo>80', 'Días con piezas']),
              p("Siete operaciones comparables tienen ciclo agregado >80 cmin/pieza en el EDA; seis de ellas están además en Funcionamiento aceptable en la aplicación. Un NPR muy bajo puede disparar el cociente: ST-0295 requiere comprobar si el contador representa la misma actividad o producto."),
              frame_table(s['parallel_hypotheses'], ['Operacion_A', 'Operacion_B', 'Ratio_combinado', 'Ciclo_equivalente_hipotetico'],
                          ['Operación A', 'Operación B', 'Piezas / mediana', 'Ciclo hipotético cmin']),
              p("La suma de piezas de ST2376 y ST-2375 se aproxima a la mediana de otras operaciones. Esto sugiere una comprobación de posible reparto de producción, no confirma que ejecuten el mismo paso en paralelo ni autoriza a sumarlas como producción final."),
              p(f"El notebook genera {len(s['slow_pairs'])} comparaciones exploratorias con esperas de operaciones próximas en el orden. Sin topología solo son listas de inspección; no se asignan roles causales ni se miden buffers."),
              p("Picking, kitting y tareas manuales requieren diccionario de activos, incidencias y flujos de material. Ningún prefijo o correlación permite atribuir una pérdida a una persona o a una causa logística concreta.")]

    backlog = [
        (1, "Validación de registros", "Reglas y trazabilidad implementadas; contraste manual con Excel pendiente."),
        (2, "Fecha civil", "Se conserva periodo codificado; conversión pendiente de confirmar la convención."),
        (3, "Cierres y festivos", "4 jornadas identificadas; escenarios y calendario opcional. Causas sin confirmar."),
        (4, "Operaciones ausentes", "Catálogo contrastado: ninguna ausente en estas 20 jornadas. No prueba planificación."),
        (5, "Media y tipología", "Ratio de sumas y filtros de coherencia. Umbrales exploratorios de 1/2/15 min."),
        (6, "Zonas", "Solo si se documentan en configuración; no se inventan a partir de códigos."),
        (7, "Frecuencia de microparadas", "FPM + P75 + duración fiable; no basta con NAP o FPM aislado."),
        (8, "Mapa de línea", "Mapa por orden con pérdidas y verde; sin inferir enlaces físicos."),
        (9, "Método generalizable", "Contrato, calendario, unidades y objetivos configurables. Propagación causal pendiente."),
        (10, "Operaciones lentas", "Ciclo y producción auditados; hipótesis de paralelismo sin confirmar."),
        (11, "Picking y kitting", "Hipótesis pendiente: no hay tipología de activos ni eventos de material."),
        (12, "Mes, semanas y días", "Agregados y recurrencia implementados. No se presume un mes civil completo."),
        (13, "Limpieza", "Strip, tipos, rangos, claves, duplicados exactos y cuarentena reproducibles."),
        (14, "Funcionamiento y ciclo", "TBF/TR se distingue de Dp; ciclo en cmin/pieza, con denominador válido."),
        (15, "Integrar Jupyter", "Notebook disponible y recalculado; se integran nube y conclusiones de balance."),
        (16, "Variables propuestas", "TAP/1.000 piezas y tipología implementados; piezas perdidas, carga e índice VV no validados."),
        (17, "Pantalla de decisión", "Ficha, PDF, priorización y recurrencia. Sin Top 3 por impacto causal inventado."),
        (18, "Navegación por planta", "Resumen → línea → operación; zonas solo documentadas. No hay plano físico validado."),
    ]
    for part in range(2):
        story += section(10 + part, f"Revisión de «Por hacer» · {part * 9 + 1}–{part * 9 + 9}", "Cada propuesta se contrasta con el notebook y el código vigente; una propuesta no se convierte en resultado por figurar en el README.")
        story += [table(["N.º", "Propuesta", "Resultado y límite"], [[a, b, c] for a, b, c in backlog[part * 9:(part + 1) * 9]], [35, 155, WIDTH - 190]),
                  Spacer(1, 12), p("Los puntos pendientes requieren datos o validación de planta. No se han consultado calendarios públicos ni se ha convertido Jour a fecha para atribuir festivos, porque la convención y la planificación industrial no están confirmadas.")]

    story += section(12, "Conclusiones, validación y reproducibilidad", "Síntesis del apartado 8 del notebook y de las comprobaciones adicionales del README.")
    story += [table(["Hallazgo defendible", "Siguiente comprobación"], [
                  ["La planificación altera fuertemente la disponibilidad", "Confirmar las cuatro jornadas sin actividad y las operaciones previstas."],
                  ["Hay discrepancias entre tiempos, piezas y contadores", "Contrastar los registros concretos; conservar origen y motivo de revisión."],
                  ["Frecuencia y duración aportan señales distintas", "Validar eventos y umbrales antes de elegir mantenimiento o automatización."],
                  ["Hay déficit/exceso de horas y ciclos extremos", "Revisar captura, ventanas, unidades, opcionalidad y paralelismo."],
                  ["Las coincidencias no acreditan causalidad", "Aportar conexiones y eventos temporales antes de medir propagación o buffers."],
              ], [220, WIDTH - 220]),
              p("Este EDA no estima un «índice de culpa», piezas finales perdidas ni probabilidad de fallo. Las variables propuestas en el README siguen siendo hipótesis cuando faltan referencias de ciclo ideal, rutas o eventos."),
              p("Reproducción", "HeadingLossia"),
              p("Ejecutar generate_hackathon_reports.py desde la raíz con las dependencias del proyecto e IPython. El generador ejecuta las celdas del notebook sin modificarlo; prepara por separado los resultados del código actual y produce ambos PDF, tablas de soporte y un manifiesto de fuentes."),
              p("Soporte: outputs/hackathon_assets contiene figuras, tablas completas de señales, auditoría decimal, catálogo, indicadores y semanas. Las huellas SHA-256 del manifiesto identifican exactamente las entradas y el código utilizados."),
              caption("Las 1.820 filas estructuralmente utilizables no implican 1.820 registros operativamente validados. No se ha realizado confirmación de causas por parte de planta.")]
    return story


def architecture_figure():
    from matplotlib.patches import FancyBboxPatch
    fig, ax = plt.subplots(figsize=(11, 4.3))
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    labels = ["CSV + configuración\n+ calendario opcional", "cleaning.py\nvalidación y trazabilidad",
              "select_scenario\nexposición y semanas", "analysis.py\nratios + reglas + recurrencia",
              "diagnostics.py\nmicroparadas y coincidencias", "app.py / reports.py\nmapa, gráficos y PDF"]
    locations = [(.02, .61), (.36, .61), (.70, .61), (.70, .11), (.36, .11), (.02, .11)]
    for index, (label, (x, y)) in enumerate(zip(labels, locations)):
        ax.add_patch(FancyBboxPatch((x, y), .28, .27, boxstyle="round,pad=0.012", facecolor="#eef3f9", edgecolor="#167d8d"))
        ax.text(x + .14, y + .135, label, ha="center", va="center", fontsize=9, color="#14253f")
        if index < len(labels) - 1:
            nx, ny = locations[index + 1]
            start = (x + .29, y + .135) if ny == y and nx > x else ((x - .01, y + .135) if ny == y else (x + .14, y - .02))
            end = (nx - .015, ny + .135) if ny == y and nx > x else ((nx + .295, ny + .135) if ny == y else (nx + .14, ny + .29))
            ax.annotate("", xy=end, xytext=start, arrowprops={"arrowstyle": "->", "color": "#c66a2b", "lw": 1.8})
    fig.tight_layout()
    return fig


def solution_report(s, prepared, records, days, result, manifest):
    settings = Settings()
    ops = result.operations
    alerts = ops[["own_alert", "des_alert", "sat_alert"]].any(axis=1)
    below = ops.loc[ops.eligible & ops.TBF_pct.lt(settings.availability_target)]
    story = cover("Solución presentada", "Un sistema de reglas explicable que transforma datos diarios en prioridades, evidencias y seguimiento semanal.", "Solución · 40 %", [
        ["Modelo utilizado", "Agregación, reglas deterministas, percentiles y análisis semanal. No se ha entrenado un modelo de machine learning."],
        ["Resultado operativo actual", f"{len(ops)} operaciones · {int(alerts.sum())} bajo el objetivo con señal predominante · {int(ops.status.isin(['Revisar datos', 'Sin producción', 'Sin datos']).sum())} casos de revisión."],
        ["Interfaz", "Mapa → operación → diagnóstico PDF; microparadas, máquinas problemáticas y tiempos de todas las máquinas."],
        ["Recurrencia", "Clasificación por semana comparable y conteo de semanas afectadas por TAP, DES y SAT."],
    ])
    story += [p("Qué resuelve", "HeadingLossia"),
              p("Separa funcionamiento, parada propia y esperas inducidas; distingue la calidad del dato de las señales operativas; conserva paradas totales y permite explicar cada color y recomendación con los registros originales."),
              p("Qué no se afirma", "HeadingLossia"),
              p("No se confirma la causa de una avería, no se estima producción final recuperable y no se predice un fallo. Las coincidencias entre operaciones son hipótesis para investigar."),
              caption("El criterio de solución se documenta con fórmulas, arquitectura, algoritmos y límites. La evidencia exploratoria completa se entrega en el PDF de EDA.")]

    story += section(1, "Arquitectura y contrato de datos", "Implementación vigente: cleaning.py → analysis.py / diagnostics.py → app.py / reports.py.")
    story += [figure_image(architecture_figure(), "solucion_arquitectura", 220),
              table(["Capa", "Responsabilidad"], [
                  ["Preparación", "Valida el esquema y las claves, convierte unidades, retira copias exactas y aparta conflictos sin sumarlos. Conserva Source_Row."],
                  ["Contexto", "Clasifica jornadas con calendario opcional; conserva cierres contradictorios y diferencia planificación desconocida de parada confirmada."],
                  ["Modelo analítico", "Agrega por línea/operación/periodo, calcula indicadores y aplica la misma regla a periodos, semanas y días."],
                  ["Diagnóstico", "Evalúa frecuencia-duración, coincidencias diarias y, fuera de la interfaz, comparaciones con días de control."],
                  ["Presentación", "Streamlit gestiona el alcance y la navegación. ReportLab produce PDF locales con evidencia y fuentes."],
              ], [105, WIDTH - 105]),
              p("La configuración es el universo de operaciones: permite mostrar máquinas sin registros. No equivale a una lista de máquinas que debían producir. Sin calendario no puede demostrarse que falten jornadas enteras que nunca aparecen en los archivos."),
              p("No hay servidor de base de datos, API de planta ni almacenamiento distribuido en la solución actual. Se procesa con pandas en memoria y se usa caché de lectura de CSV en Streamlit.")]

    story += section(2, "Fórmulas: unidades, denominadores y agregación", "Los ratios se calculan después de sumar los registros de la misma línea, operación y alcance.")
    formulas = [
        ["Tiempo registrado", "TR = TBF + TAP + DES + SAT", "Horas registradas; no se impone como jornada requerida."],
        ["Espera inducida", "TAI = DES + SAT", "Horas de espera por suministro o evacuación."],
        ["Funcionamiento / TR", "F = 100 × TBF / TR", "Porcentaje que decide si se alcanza el objetivo."],
        ["Disponibilidad propia", "Dp = 100 × TBF / (TBF + TAP)", "Excluye DES y SAT; se conserva como indicador, no decide el color."],
        ["Reparto de tiempos", "P_X = 100 × X / TR", "X: TBF, TAP, DES o SAT; porcentajes comparables."],
        ["Frecuencia de parada", "FPM = 1.000 × NAP / NPR", "Paradas por 1.000 piezas; no es tiempo perdido."],
        ["Media por parada", "M = 60 × TAP / NAP", "Minutos por parada; fiable solo con contadores compatibles."],
        ["Ciclo de funcionamiento", "C = 6.000 × TBF / NPR", "cmin/pieza: 60 min/h × 100 centésimas/min."],
        ["TAP por producción", "H_1000 = 1.000 × TAP / NPR", "Horas de parada propia por 1.000 piezas."],
        ["Peso propio de las pérdidas", "100 × TAP / (TAP + DES + SAT)", "Porcentaje propio del tiempo sin funcionamiento; no asigna causalidad."],
        ["Balance de tiempos", "Desvío = 60 × (TR − referencia h)", "Minutos de déficit/exceso respecto a la referencia de cada jornada."],
        ["Cobertura", "100 × días observados / días esperados", "Universo de días de línea incluidos y operaciones configuradas."],
    ]
    story += [table(["Indicador", "Fórmula", "Interpretación"], formulas, [110, 185, WIDTH - 295]),
              p("Denominador cero: el ratio queda no definido. TBF=0 no se elimina como regla de limpieza. Un ciclo con piezas registradas sin funcionamiento no se interpreta como ciclo cero."),
              p("Ejemplo de agregación: dos días con TAP=1 h y NAP=120 y 1 dan M=120/121=0,992 min. Promediar las medias diarias daría 30,25 min y respondería a una pregunta distinta.")]

    story += section(3, "Algoritmo de clasificación del periodo", "Clasificador determinista: umbral de funcionamiento, pérdida mayor y excepciones de calidad.")
    story += [table(["Paso", "Regla implementada"], [
                  ["1. Calidad antes de color operativo", "Sin registros: Sin datos. Cobertura incompleta o piezas sin TBF: Revisar datos. TBF=0 y NPR=0: Sin producción. TBF>0 sin piezas agregadas: Revisar datos."],
                  ["2. Funcionamiento aceptable", "Si TBF/TR ≥ objetivo, color verde. El objetivo inicial es 90 %. Buen funcionamiento y Elemento lento comparten verde; el ciclo los distingue en el desplegable."],
                  ["3. Pérdida predominante", "Si TBF/TR < objetivo, comparar TAP, DES y SAT. Si TAP es el mayor, también en empate, rojo. En otro caso, predomina DES amarillo o SAT naranja."],
                  ["4. DES/SAT próximos", "Si TAP no es el mayor y max(DES,SAT) < 1,5 × min(DES,SAT), ambos positivos, mostrar mitad naranja y mitad amarillo. El estado interno es Mixto."],
              ], [125, WIDTH - 125]),
              p("El corte global es estricto: exactamente al 90 % no se activa una señal de parada. El color usa el mayor componente del tiempo sin funcionamiento; comparar sus horas o sus proporciones sobre el mismo total de pérdida da el mismo orden."),
              p("En la aplicación actual, la disponibilidad propia y un umbral individual del 10 % ya no deciden el color. El 10 % derivado de 100−objetivo se usa para seleccionar porcentajes significativos en los mapas semanales."),
              table(["Categoría actual", "Operaciones"], [[name, int(count)] for name, count in ops.status.value_counts().items()], [WIDTH - 90, 90]),
              caption("Los colores son señales del periodo. Una máquina que espera en DES o SAT no queda diagnosticada como averiada.")]

    story += section(4, "Mapa, prioridades y diagnóstico explicable", "Código: order_operations, operations_view, operation_report y state_explanation.")
    story += [map_drawing(order_operations(ops)), Spacer(1, 8),
              caption("91 operaciones en el orden configurado. Se conserva únicamente el nombre dentro de cada caja; el orden no se interpreta como una conexión física."),
              p("Dos ordenaciones: orden de configuración o «Por urgencia de reparación». La segunda agrupa por color: TAP, SAT, DES, mixto y funcionamiento aceptable; los casos de datos se muestran aparte. Dentro de cada grupo ordena TBF/TR de menor a mayor, con desempate por Orden_OP y nombre y porcentajes no definidos al final de su grupo. Usa el porcentaje de funcionamiento, no horas absolutas. Es una prioridad de investigación, no un ranking de impacto causal."),
              p("La ficha aparece tras descargar los criterios y conserva métricas, evidencias y posibles efectos filtrables. El PDF incluye fórmulas aplicadas, razones del color, registros diarios, balance, fuente y parámetros. Revisión de datos se muestra al final del mapa."),
              p("PM2130 se destaca al principio: TBF=0, NPR=0 y 351,87 h de TAP. Permanece como Sin producción dentro de Otros; se confirma planificación antes de concluir una avería continua. ST_0030 tiene cero horas en todas las categorías y requiere revisar actividad o captura."),
              p("La gráfica de tiempos ordena por TBF/TR, el mismo porcentaje que dibuja, y no por horas TBF absolutas. En Máquinas más problemáticas, la gráfica del apartado 4 del EDA filtra y dibuja disponibilidad propia: TBF/(TBF + TAP) <90 %, cinco operaciones comparables en estos datos. Conserva los colores TAP rojo, DES amarillo y SAT naranja. El mapa continúa usando funcionamiento/TR para su clasificación y ordenación.")]

    story += section(5, "Algoritmo de microparadas y recomendaciones", "Código: classify, microstop_points y stop_action_plan. Separado de la asignación del color operativo.")
    story += [figure_image(microstop_figure(ops, settings), "solucion_microparadas", 245),
              p("Población de referencia: operaciones elegibles y con duración fiable dentro de cada línea y periodo. FPM_P75 = cuantil 0,75 de sus FPM. Indicio = FPM ≥ FPM_P75 y M < umbral breve, inicialmente 2 min. No basta con NAP alto ni con TAP alto."),
              p(f"Un punto por operación, con comprobación de unicidad: {len(microstop_points(ops))} puntos y {int(ops.short_frequent_signal.sum())} indicios en la selección actual. El notebook usa 1 min y obtiene 19; ambos parámetros se explicitan, sin mezclar sus recuentos."),
              p("El módulo de diagnóstico también analiza días fiables por separado y calcula el TAP de días con indicios / TR de días válidos; considera relevancia exploratoria desde el 1 %. Ese TAP diario puede incluir eventos largos y no equivale a una duración confirmada de microparadas. El patrón de pocas y prolongadas combina FPM ≤ P25 y media ≥15 min."),
              table(["Grupo de la plantilla", "Acción orientativa"], [
                  ["Muchas y cortas", "Contrastar eventos repetidos, sensores, alimentación y atascos; priorizar TAP acumulado."],
                  ["Muchas y largas", "Investigar incidencias repetidas y recuperación."],
                  ["Pocas y cortas", "Seguimiento y estandarización de ajustes."],
                  ["Pocas y largas", "Revisar incidencias de mayor duración y procedimiento de recuperación."],
              ], [170, WIDTH - 170]),
              caption("Muchas/pocas: respecto a P75. Cortas/largas: respecto al umbral breve; no equivale a parada prolongada ≥15 min. Las recomendaciones proceden de plantillas calculadas, no de un modelo generativo ni de un diagnóstico causal.")]

    story += section(6, "Recurrencia: algoritmo, fórmula y resultado", "Código: analyse calcula agregados y clasificación semanal, elegibilidad y conteos por operación.")
    own = ops.loc[ops.own_alert].sort_values(['recurrence_own', 'TAP'], ascending=False)
    story += [p("Se repite el cálculo sobre cada combinación Linea, Operacion, Year y Week. La elegibilidad semanal exige cobertura completa de sus jornadas incluidas, producción y funcionamiento positivos y ausencia de piezas sin TBF. Una semana no comparable no se interpreta como una semana sin fallos."),
              table(["Magnitud", "Definición"], [
                  ["E(o,w)", "1 si la operación o es elegible en la semana w; 0 en otro caso."],
                  ["I_k(o,w)", "1 si E=1 y la regla de pérdida predominante activa TAP, DES o SAT; 0 si no."],
                  ["Semanas afectadas", "R_k(o) = suma sobre semanas de I_k(o,w). Es el conteo implementado."],
                  ["Semanas evaluables", "N_eval(o) = suma sobre semanas de E(o,w). Se muestra junto al conteo."],
                  ["Lectura normalizada", "100 × R_k / N_eval. Cociente descriptivo del informe; no es probabilidad de fallo."],
              ], [145, WIDTH - 145]), Spacer(1, 8),
              frame_table(own, ['Operacion', 'recurrence_own', 'recurrence_des', 'recurrence_sat', 'evaluable_week'],
                          ['Operación con TAP predominante', 'Semanas TAP', 'Semanas DES', 'Semanas SAT', 'Evaluables']),
              p("La categoría del periodo puede diferir de la semanal: el agregado pondera horas y una pérdida puede predominar en semanas distintas. No se promedian categorías ni se suman porcentajes semanales."),
              p("Señales repetidas pueden corresponder a una incidencia persistente, a eventos independientes o a condiciones de proceso repetidas. El sistema no implementa identificación de una misma avería ni conteo de episodios consecutivos a partir de eventos."),
              caption("El conteo actual es de semanas afectadas. Para comparar meses con distinto número de semanas debe usarse también la exposición evaluable y una planificación comparable.")]

    story += section(7, "Recurrencia: lectura visual y seguimiento", "Los mapas muestran porcentajes significativos; los contadores anteriores muestran clasificación semanal predominante.")
    chosen = own.Operacion.tolist()
    weekly = result.weekly
    matrix = weekly.pivot(index='Operacion', columns=['Year', 'Week'], values='TAP_pct').reindex(chosen)
    story += [figure_image(heat_figure(matrix, "TAP / TR (%)"), "solucion_recurrencia", 245),
              caption("Operaciones con TAP predominante en el periodo. Se muestran todas las semanas observadas; los números son porcentajes y no conteos de eventos."),
              p("En Streamlit, cada mapa TAP/DES/SAT filtra filas que alcancen 100−objetivo de funcionamiento en al menos una semana elegible bajo el objetivo. Este filtro de significación controla el tamaño de la gráfica; no modifica las reglas de color ni los tiempos originales."),
              p("Un porcentaje de DES significativo puede aparecer en el mapa aunque otra pérdida predomine esa semana. Por eso el porcentaje mostrado no debe confundirse con el contador de semanas clasificadas como DES."),
              p("Plan de seguimiento", "HeadingLossia"),
              p("1. Confirmar calendario y comparabilidad. 2. Identificar las semanas y registros que explican una pérdida. 3. Registrar la intervención y su fecha. 4. Comparar después TAP/TR, FPM, media y recurrencia con carga y producto equivalentes. 5. Validar con planta que el cambio no sea solo de captura o planificación."),
              p("No se utiliza una predicción, una tendencia ajustada ni una inferencia de causalidad para recomendar actuaciones. Cuatro semanas permiten una descripción inicial, no una validación longitudinal.")]

    story += section(8, "Relaciones entre operaciones: algoritmos y límites", "Código: propagation_evidence, validate_connections, impact_pairs e impact_summary.")
    story += [table(["Procedimiento", "Implementación y alcance"], [
                  ["Coincidencias diarias", "Une por Linea/Year/Week/Jour los días con TAP predominante de una operación y DES/SAT de otra; cuenta días y suma las horas de la señal de la otra máquina."],
                  ["Recorrido de conexiones", "Si se proporciona un grafo fuera de la interfaz actual, se recorren rutas aguas arriba y abajo con búsqueda en anchura, evitando nodos ya visitados. Los saltos no son distancia física ni tiempo de propagación."],
                  ["Comparación con control", "Para cada candidata y las otras operaciones compara porcentaje de espera en días con y sin señal propia. Exige al menos 3 días en cada grupo para marcar comparación disponible."],
                  ["Asociación exploratoria", "Spearman se calcula como correlación de rangos cuando hay al menos 6 días pareados y variación en ambas variables; no es una prueba causal ni un modelo entrenado."],
              ], [140, WIDTH - 140]),
              p("Diferencia de espera = 100 × suma(espera con señal) / suma(TR con señal) − 100 × suma(espera sin señal) / suma(TR sin señal). Compara ratios de sumas, no medias de porcentajes con exposiciones distintas."),
              p("Las horas coincidentes son el acumulado completo del día de la otra operación, no el solapamiento temporal. Sin eventos no se conoce qué ocurrió primero. Sin conexiones no se asignan direcciones a partir de Orden_OP."),
              p("Estado actual: no hay archivo de conexiones aportado y su carga ya no figura en Streamlit. La interfaz muestra coincidencias para investigar. Los análisis con control y rutas siguen en los módulos e informes, no en una pestaña independiente de pérdidas propias."),
              p("No se ha aplicado el índice TAP + SAT_previo + DES_siguiente del borrador del README: sumaría horas de varias operaciones sin validar conexiones, exposición ni doble conteo. Tampoco se estiman buffers ni piezas perdidas como resultado validado.")]

    story += section(9, "Validación, alcance y escalabilidad", "Los criterios de evaluación se separan: EDA 30 %, solución 40 %, visualización/funcionalidad 15 % y pitch 15 %.")
    story += [table(["Dimensión", "Evidencia / siguiente paso"], [
                  ["Validación implementada", "56 pruebas del proyecto: unidades, claves, cierres, medias de sumas, colores, elegibilidad, recurrencia, orden de barras, filtros y PDF. No miden exactitud de causas industriales."],
                  ["Usabilidad", "Tres apartados, cajas con nombre, filtros, detalle de operación y PDF reproducible. Se separan calidad, funcionamiento y pérdidas."],
                  ["Generalización", "Otras líneas y periodos con el mismo contrato diario y universo configurado; objetivos, unidades y calendario ajustables."],
                  ["Límites actuales", "CSV y pandas en memoria. Sin autenticación por roles, base de datos, despliegue distribuido ni benchmark de grandes volúmenes."],
                  ["Escalado de datos", "Particionar por planta/línea/periodo, almacenar tablas preparadas y preagregar semanas. Añadir producto, turno y actividad prevista por operación antes de comparar."],
                  ["Escalado de relaciones", "Las comparaciones entre candidatas y otras operaciones crecen con sus pares. Indexar conexiones y fechas; usar adyacencias y deque para recorridos grandes en lugar de filtros repetidos de DataFrame."],
              ], [145, WIDTH - 145]),
              p("No hay entrenamiento supervisado, clustering, red neuronal, optimización de mantenimiento ni predictor de fallos. La contribución es un pipeline auditable y un clasificador explicable con evidencia por operación y seguimiento semanal."),
              p("Evolución propuesta, no implementada", "HeadingLossia"),
              p("Conectar eventos y topología validados; definir objetivos por producto/operación; medir desempeño después de intervenciones; estimar impacto solo con una referencia de producción final y evitando doble conteo. Los ratios víctima/villano, carga diaria y piezas perdidas del README requieren validación antes de dirigir decisiones.")]

    story += section(10, "Fuentes y reproducción de la entrega", "Instantánea del código de trabajo actual; las huellas identifican los archivos exactos, incluidos cambios aún no publicados.")
    sources = [[Path(name).name, entry['sha256'][:20] + "…"] for name, entry in manifest['sources'].items()]
    story += [table(["Archivo", "SHA-256 (prefijo; completo en manifiesto)"], sources, [230, WIDTH - 230]),
              p("Entradas: datos_hackaton.csv y config_hackaton.csv. Sin calendario ni conexiones aportados. Tiempos de entrada en horas; escenario provisional; objetivo TBF/TR 90 %; ciclo 80 cmin/pieza; breve 2 min; prolongada 15 min; FPM por 1.000 piezas."),
              p("Reproducción: ejecutar generate_hackathon_reports.py. El generador recalcula el notebook y prepara por separado la solución actual. Guarda indicadores por operación, clasificación semanal y datos de soporte en outputs/hackathon_assets, junto con el manifiesto de parámetros y fuentes."),
              p("Comprobaciones de consistencia de esta entrega", "HeadingLossia"),
              p(f"{len(ops)} operaciones únicas; {len(below)} con funcionamiento/TR bajo el objetivo y señal predominante; "
                f"{int((ops.eligible & ops.availability_pct.lt(90)).sum())} con disponibilidad propia bajo el 90 %, representadas en la gráfica de Máquinas más problemáticas; "
                f"{len(microstop_points(ops))} puntos únicos de microparadas. Los registros originales y el notebook no se sobrescriben."),
              p("Mensaje para la presentación", "HeadingLossia"),
              p("La solución no confunde una operación que espera con una avería confirmada. Explica qué se observa, permite localizar el registro y propone cómo comprobar si una intervención mejora el resultado. El EDA justifica las decisiones; la arquitectura hace que sean repetibles.")]
    return story


def main():
    OUTPUT.mkdir(exist_ok=True)
    source_paths = ["initial_exploration.ipynb", "README.md", "data/datos_hackaton.csv", "data/config_hackaton.csv",
                    "cleaning.py", "analysis.py", "diagnostics.py", "app.py", "reports.py", "generate_hackathon_reports.py"]
    sources = {name: {"sha256": sha256((ROOT / name).read_bytes()).hexdigest(),
                       "bytes": (ROOT / name).stat().st_size} for name in source_paths}
    state, figures, notebook_tables = execute_notebook()
    prepared = prepare_data(state['raw_data'], state['raw_config'])
    records, days = select_scenario(prepared, 'provisional')
    settings = Settings()
    result = analyse(records, days, prepared.configuration, settings)
    ops = result.operations
    alerts = ops[['own_alert', 'des_alert', 'sat_alert']].any(axis=1)
    assert not ops.duplicated(['Linea', 'Operacion']).any()
    assert int(alerts.sum()) == int((ops.eligible & ops.TBF_pct.lt(90)).sum())
    assert len(state['working']) == len(records)
    assert len(state['stop_candidates']) == len(microstop_points(ops))
    manifest = {
        "generated_for_date": "2026-11-14", "sources": sources,
        "evaluation_weights_pct": {"eda": 30, "solution": 40, "visualization_functionality": 15, "pitch": 15},
        "scenario": "provisional", "calendar_provided": False, "connections_provided": False,
        "time_unit": "hours", "reference_hours": 22, "runtime_target_pct": 90, "cycle_target_cmin": 80,
        "notebook_brief_seconds": float(state['MICROSTOP_MEAN_SECONDS']), "application_brief_minutes": 2,
        "notebook_micro_signals": int(state['stop_candidates'].short_frequent_signal.sum()),
        "application_micro_signals": int(ops.short_frequent_signal.sum()), "scatter_operations": len(microstop_points(ops)),
        "operations": len(ops), "period_rows": len(records), "period_days": len(days),
        "runtime_below_target": int(alerts.sum()), "status_counts": {str(k): int(v) for k, v in ops.status.value_counts().items()},
    }
    for cell, frames in notebook_tables.items():
        for index, frame in enumerate(frames, start=1):
            frame.to_csv(ASSETS / f"notebook_celda_{cell:02d}_tabla_{index:02d}.csv", index=True, encoding='utf-8-sig')
    for key in ['clock_audit', 'identifier_catalog', 'clock_by_operation', 'clock_matrix', 'slow_profile', 'slow_pairs']:
        state[key].to_csv(ASSETS / f"eda_{key}.csv", index=True, encoding='utf-8-sig')
    for flag in FLAGS:
        prepared.records.loc[prepared.records[flag]].to_csv(ASSETS / f"calidad_{flag}.csv", index=False, encoding='utf-8-sig')
    ops.to_csv(ASSETS / "solucion_indicadores.csv", index=False, encoding='utf-8-sig')
    result.weekly.to_csv(ASSETS / "solucion_recurrencia_semanal.csv", index=False, encoding='utf-8-sig')
    eda_path = OUTPUT / "LOSSIA_Analisis_exploratorio.pdf"
    solution_path = OUTPUT / "LOSSIA_Solucion_presentada.pdf"
    build_pdf(eda_report(state, figures, notebook_tables, prepared, records, result), eda_path, "Análisis exploratorio de datos", TEAL)
    build_pdf(solution_report(state, prepared, records, days, result, manifest), solution_path, "Solución presentada", ORANGE)
    for name, metadata in sources.items():
        assert sha256((ROOT / name).read_bytes()).hexdigest() == metadata['sha256'], f"La fuente cambió durante la generación: {name}"
    import re
    manifest['pdfs'] = {}
    for path in [eda_path, solution_path]:
        content = path.read_bytes()
        assert content.startswith(b'%PDF-') and content.rstrip().endswith(b'%%EOF')
        pages = len(re.findall(rb'/Type\s*/Page\b', content))
        manifest['pdfs'][path.name] = {"pages": pages, "bytes": len(content), "sha256": sha256(content).hexdigest()}
        print(f"{path.name}: {pages} páginas; {len(content):,} bytes")
    (ASSETS / "manifiesto_entrega.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Soporte y huellas: {ASSETS}")


if __name__ == "__main__":
    main()
