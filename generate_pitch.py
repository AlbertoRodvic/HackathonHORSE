"""Seis slides editables y PDF, con demo integrada y guion de 8 minutos.

Preparar datos con el entorno del proyecto:
    HORSE/Scripts/python.exe generate_pitch.py --prepare
Generar presentación con python-pptx y PyMuPDF:
    python generate_pitch.py
"""

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
ASSETS = OUT / "pitch_assets"
W, H = 960, 540
BG, NAVY, TEAL, GRAY = "F5F7FA", "14253F", "167D8D", "59677A"
GREEN, RED, YELLOW, ORANGE = "339D78", "D94A4A", "F2CF52", "F08A35"


def prepare():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from analysis import analyse, Settings
    from cleaning import prepare_data, select_scenario
    from diagnostics import microstop_points, investigation_figure

    ASSETS.mkdir(parents=True, exist_ok=True)
    prepared = prepare_data(pd.read_csv(ROOT / "data/datos_hackaton.csv"), pd.read_csv(ROOT / "data/config_hackaton.csv"))
    records, days = select_scenario(prepared)
    result = analyse(records, days, prepared.configuration)
    ops = result.operations
    points = microstop_points(ops)
    own_priorities = ops.loc[ops.eligible & ops.availability_pct.lt(90)]
    medians = {}
    for scenario in ["all", "provisional"]:
        r, d = select_scenario(prepared, scenario)
        o = analyse(r, d, prepared.configuration).operations
        medians[scenario] = float(o.loc[o.eligible, "availability_pct"].median())
    facts = {
        "rows": len(prepared.records), "operations": len(ops), "included_days": len(days),
        "pending_days": int(prepared.days.day_status.eq("unconfirmed").sum()),
        "medians": medians, "scatter": len(points), "micro": int(points.short_frequent_signal.sum()),
        "signals": int(ops[["own_alert", "des_alert", "sat_alert"]].any(axis=1).sum()),
        "own_priority_count": len(own_priorities),
        "quality": {flag: int(prepared.records[flag].sum()) for flag in [
            "production_without_runtime", "runtime_without_production", "stops_without_own_time", "own_time_without_stops"]},
        "duplicates": len(prepared.duplicates),
        "weekly_example": result.weekly.loc[result.weekly.Operacion.eq("ST2235")].sort_values(["Year", "Week"])[["Week", "TAP_pct"]].to_dict("records"),
        "examples": {name: ops.loc[ops.Operacion.eq(name), ["TBF", "TAP", "fpm", "mean_stop_minutes", "recurrence_own", "evaluable_week"]].iloc[0].to_dict()
                     for name in ["ST2235", "PM2130", "PM2250"]},
    }
    (ASSETS / "datos_presentacion.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.labelsize": 11})
    fig, ax = plt.subplots(figsize=(8, 4.2), facecolor="#" + BG)
    ax.set_facecolor("#" + BG)
    ax.scatter(points.fpm, points.mean_stop_minutes, s=25 + 155 * points.TAP / points.TAP.max(),
               color=np.where(points.short_frequent_signal, "#" + RED, "#6C9BAF"), alpha=.85, linewidth=0)
    ax.axhline(2, color="#" + RED, lw=1.3, ls="--")
    ax.axvline(points.frequency_p75.iloc[0], color="#7B8797", lw=1.2, ls=":")
    ax.text(.02, 2.2, "2 min", transform=ax.get_yaxis_transform(), color="#" + RED, fontsize=10)
    ax.set(xscale="log", yscale="log", xlabel="Paradas por 1.000 piezas · escala log", ylabel="Media por parada (min) · escala log")
    ax.set_ylim(.025, 12)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color("#CCD5DE")
    ax.tick_params(colors="#" + GRAY)
    ax.grid(alpha=.12, which="major")
    for name, offset in [("ST2235", (-78, 7)), ("MANOP749", (5, 12)), ("ST-2390", (8, -15))]:
        row = points.loc[points.Operacion.eq(name)].iloc[0]
        ax.annotate(name, (row.fpm, row.mean_stop_minutes), xytext=offset, textcoords="offset points",
                    fontsize=10, fontweight="bold", color="#" + NAVY)
    fig.tight_layout(pad=1)
    fig.savefig(ASSETS / "microparadas_pitch.png", dpi=200, facecolor=fig.get_facecolor())
    plt.close(fig)
    fig = investigation_figure(own_priorities, Settings(), metric="availability_pct")
    fig.set_size_inches(12, 3.6)
    fig.set_facecolor("#" + BG)
    for axis in fig.axes:
        axis.set_facecolor("#" + BG)
        axis.title.set_fontsize(12)
        axis.xaxis.label.set_fontsize(11)
        axis.tick_params(labelsize=11)
        if axis.get_legend():
            for text in axis.get_legend().get_texts():
                text.set_fontsize(10)
    fig.tight_layout(pad=1)
    fig.savefig(ASSETS / "prioridades_propias_pitch.png", dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    print("Datos y gráfica de pitch preparados.")


class Slide:
    def __init__(self, background=BG):
        self.background = background
        self.elements = []
        self.notes = ""

    def rect(self, x, y, width, height, fill, stroke=None, radius=False):
        self.elements.append(("rect", x, y, width, height, fill, stroke, radius))

    def text(self, x, y, width, height, text, size=18, color=NAVY, bold=False, align="left"):
        self.elements.append(("text", x, y, width, height, text, size, color, bold, align))

    def image(self, x, y, width, height, path):
        self.elements.append(("image", x, y, width, height, str(path)))


def base(section, number, dark=False):
    slide = Slide(NAVY if dark else BG)
    color = "FFFFFF" if dark else NAVY
    muted = "B6C4D6" if dark else GRAY
    slide.rect(48, 31, 4, 20, "65CBC4" if dark else TEAL)
    slide.text(64, 31, 160, 24, "LOSSIA", 16, color, True)
    slide.text(610, 33, 302, 21, section.upper(), 12, muted, align="right")
    slide.text(48, 513, 650, 15, "HACKATHON HORSE  /  VLL_MONTAJE_L5", 9, muted)
    slide.text(849, 511, 63, 18, f"0{number} / 06", 10, muted, align="right")
    return slide


def es(value, digits=2):
    return f"{value:.{digits}f}".replace(".", ",")


def create_slides(facts):
    slides = []

    s = base("Proyecto · Hackathon HORSE", 1, True)
    s.text(48, 94, 864, 97, "LOSSIA", 70, "FFFFFF", True)
    s.text(48, 211, 864, 75, "Diagnóstico explicable de pérdidas\ny seguimiento de líneas de producción.", 26, "FFFFFF")
    for x, title, desc in [
        (48, "Recurrencia", "Ver qué señales se repiten\ny cómo evolucionan."),
        (344, "Relaciones", "Contrastar señales\nentre operaciones."),
        (640, "Escalabilidad", "Reutilizar el análisis\nen otras líneas y periodos."),
    ]:
        s.rect(x, 326, 272, 119, "223650", radius=True)
        s.text(x + 18, 344, 238, 30, title, 20, "65CBC4", True)
        s.text(x + 18, 388, 238, 47, desc, 15, "FFFFFF")
    s.text(48, 475, 864, 26, "Datos diarios → prioridades de revisión → evidencia para actuar", 17, "D8E3EF")
    s.notes = """00:00–00:30 · 30 segundos

Presentamos LOSSIA: una herramienta que convierte registros diarios de producción en prioridades de revisión y seguimiento. Nos centramos en tres aspectos: recurrencia, para ver qué señales se repiten; relación entre operaciones, para contrastar posibles efectos sobre el flujo; y un método configurable para otras líneas y periodos. Cada prioridad puede explicarse con los datos que la sustentan.

No presentar las coincidencias como efectos causales confirmados ni la escalabilidad como un despliegue distribuido ya realizado.
"""
    slides.append(s)

    s = base("Índice", 2)
    s.text(48, 86, 864, 62, "¿De qué vamos a hablar?", 36, bold=True)
    items = [
        ("Herramienta final", "Primero, una demostración de Streamlit."),
        ("EDA", "Los problemas de los CSV y las decisiones de limpieza."),
        ("Solución planteada", "Herramientas técnicas, reglas y variables creadas."),
        ("Aspectos clave de la interfaz", "Recurrencia, relaciones y escalabilidad."),
    ]
    for index, (title, desc) in enumerate(items):
        y = 179 + index * 75
        s.rect(48, y, 864, 66, "FFFFFF", radius=True)
        s.text(67, y + 17, 45, 37, f"0{index + 1}", 24, TEAL, True)
        s.text(130, y + 9, 756, 33, title, 23, NAVY, True)
        s.text(130, y + 41, 756, 22, desc, 14, GRAY)
    s.notes = """00:30–00:50 · 20 segundos

Empezaremos por la herramienta final para mostrar cómo se identifican las operaciones que conviene investigar. Después explicaremos el EDA, las decisiones técnicas que lo convierten en una solución y los tres aspectos clave de la interfaz: evolución semanal, relación entre operaciones y reutilización en otras líneas.
"""
    slides.append(s)

    s = base("Herramienta final · Demo de Streamlit", 3)
    s.text(48, 87, 864, 58, f"De 91 operaciones a {facts['own_priority_count']} prioridades claras.", 34, bold=True)
    s.text(48, 153, 864, 37, "Disponibilidad propia < 90 % · TBF / (TBF + TAP)", 20, GRAY)
    s.image(33, 204, 894, 268, ASSETS / "prioridades_propias_pitch.png")
    s.text(48, 482, 864, 25, "EN DIRECTO  ·  Elegir línea → Máquinas más problemáticas → Ficha y diagnóstico", 14, TEAL, True)
    s.notes = """00:50–03:00 · 2 minutos 10 segundos, incluidos 15 segundos de introducción y 1 minuto 55 de demo

Introducción de la slide: «La herramienta reduce la búsqueda a cinco operaciones comparables con disponibilidad propia inferior al 90 %. El primer panel muestra TBF/(TBF+TAP); el segundo separa TAP, DES y SAT. Veámoslo en Streamlit».

00:50–01:05 · Introducir la gráfica de respaldo de esta slide.
01:05–01:25 · Cambiar a Streamlit, abrir VLL_MONTAJE_L5 y señalar PM2130 destacada al principio: no registra TBF, tiene 351,87 h de TAP y requiere confirmar si debía trabajar.
01:25–02:10 · Entrar en «Máquinas más problemáticas». Mostrar las cinco operaciones y distinguir disponibilidad propia de TBF/TR. Elegir ST2235 como ejemplo por sus pérdidas registradas, sin afirmar que causa las de toda la línea.
02:10–02:45 · Volver al mapa, seleccionar «Por urgencia de reparación» y filtrar «Parada propia». Abrir ST2235, señalar métricas, posibles efectos sobre otras operaciones y botón de diagnóstico PDF.
02:45–03:00 · Volver a la presentación: «Para llegar a este resultado tuvimos que entender primero los problemas del dato».

La imagen es la gráfica del apartado 4 del EDA con la paleta actual, no una simulación de la interfaz. Es el respaldo si la demo no carga. No descargar y abrir documentos durante la demo si eso retrasa el recorrido.
"""
    slides.append(s)

    s = base("EDA · Del CSV a una base fiable", 4)
    s.text(48, 87, 864, 57, "Entender el CSV antes de decidir.", 34, bold=True)
    s.text(48, 151, 864, 33, "1.820 registros · 91 operaciones · calidad, cobertura y exposición", 19, GRAY)
    s.text(62, 191, 400, 21, "QUÉ ENCONTRAMOS", 12, TEAL, True)
    s.text(499, 191, 400, 21, "CÓMO LO TRATAMOS", 12, TEAL, True)
    q = facts['quality']
    rows = [
        ("4 jornadas sin actividad\nTBF y producción = 0", "Calendario opcional y escenarios.\nExclusión provisional, no festivos confirmados."),
        (f"{q['production_without_runtime']} registros: piezas sin TBF\n{q['runtime_without_production']}: TBF sin piezas", "Validación y trazabilidad por registro.\nSeñalar antes de corregir o atribuir averías."),
        (f"{q['stops_without_own_time']}: NAP sin TAP\n{q['own_time_without_stops']}: TAP sin NAP", "Calcular medias solo si son fiables.\nNo inventar incidencias ni duraciones."),
        ("Totales diarios distintos de 22 h", "Auditar déficit, exceso y tiempo cero.\nConservar los tiempos originales."),
        (f"{facts['duplicates']} duplicados · catálogo 91/91\nNombres con formatos distintos", "Normalizar espacios, claves y tipos.\nConservar códigos y sufijos originales."),
    ]
    for index, (left, right) in enumerate(rows):
        y = 218 + index * 53
        s.rect(48, y, 864, 48, "FFFFFF" if index % 2 == 0 else "EAF0F5", radius=True)
        s.text(62, y + 3, 399, 44, left, 15, NAVY, True)
        s.text(499, y + 4, 398, 43, right, 14, GRAY)
    s.text(48, 490, 864, 17, "Pendiente de validar: fechas civiles, zonas, topología y causas logísticas. No se inventan conexiones.", 11, GRAY)
    s.notes = """03:00–04:35 · 1 minuto 35 segundos

El EDA parte del notebook y de la lista «Por hacer» del README. Comprobamos estructura, duplicados y correspondencia con el catálogo: aparecen las 91 operaciones y no hay copias idénticas. Eso no garantiza coherencia operativa. Hay cuatro registros con piezas sin funcionamiento, 65 con funcionamiento sin piezas y casos donde NAP y TAP no son compatibles. Los conservamos con señales de revisión; no inventamos tiempos ni incidencias.

La exposición fue decisiva: cuatro jornadas tienen TBF y producción cero, pero sí 22 horas de TAP. Las excluimos provisionalmente, con opción de aportar calendario de fábrica. La mediana de disponibilidad propia cambia del 76,19 al 98,37 %, sin que eso represente una mejora física de la línea. También auditamos déficits y excesos diarios: no forzamos que todo sume 22 horas. Mantenemos los identificadores tal como están, porque un guion o un sufijo no prueba un error ni un paralelo. Fechas civiles, zonas, picking/kitting y conexiones reales requieren contexto de planta.

Respaldo: PDF de EDA, con revisión de los 18 puntos del README. No afirmar que se han contrastado las incidencias manualmente con Excel o confirmado festivos.
"""
    slides.append(s)

    s = base("Solución planteada · técnica", 5, True)
    s.text(48, 86, 864, 88, "Reglas trazables, variables comparables\ny un pipeline reproducible.", 32, "FFFFFF", True)
    tools = [
        ("pandas", "Limpieza, joins\ny escenarios"),
        ("NumPy", "Ratios y reglas\ndeterministas"),
        ("Matplotlib", "Gráficas y\nrecurrencia"),
        ("Streamlit + PDF", "Interfaz y diagnóstico\ncon ReportLab"),
    ]
    for index, (name, desc) in enumerate(tools):
        x = 48 + index * 220
        s.rect(x, 191, 204, 102, "223650", radius=True)
        s.text(x + 15, 205, 176, 28, name, 18, "65CBC4", True)
        s.text(x + 15, 246, 176, 42, desc, 14, "FFFFFF")
    s.text(48, 315, 864, 20, "VARIABLES CREADAS · RATIOS DE SUMAS, NO MEDIAS DE RATIOS", 12, "65CBC4", True)
    left = ["TR = TBF + TAP + DES + SAT", "Funcionamiento (%) = 100 × TBF / TR", "Dp (%) = 100 × TBF / (TBF + TAP)"]
    right = ["FPM = 1.000 × NAP / NPR", "Media (min) = 60 × TAP / NAP", "Recurrencia = semanas con señal / evaluables"]
    for index in range(3):
        y = 346 + index * 31
        s.text(48, y, 421, 27, left[index], 15, "FFFFFF")
        s.text(488, y, 424, 27, right[index], 15, "FFFFFF")
    chips = [(48, 252, GREEN, "≥ 90 %  ACEPTABLE", "FFFFFF"),
             (312, 110, RED, "TAP", "FFFFFF"), (434, 110, YELLOW, "DES", NAVY), (556, 110, ORANGE, "SAT", NAVY)]
    for x, width, color, label, text_color in chips:
        s.rect(x, 451, width, 35, color, radius=True)
        s.text(x + 8, 458, width - 16, 24, label, 13, text_color, True, "center")
    s.text(690, 452, 222, 38, "Bajo el objetivo:\npérdida predominante.", 13, "D8E3EF")
    s.text(48, 490, 864, 17, "Además: TAI, ciclo en cmin/pieza, cobertura, TAP/1.000 piezas y señales de calidad.", 11, "B6C4D6")
    s.notes = """04:35–06:15 · 1 minuto 40 segundos

La solución se desarrolla en Python. pandas valida, normaliza y une producción y configuración; NumPy permite aplicar ratios y reglas; Matplotlib genera las gráficas; Streamlit gestiona la navegación y ReportLab el diagnóstico PDF. Son reglas deterministas y percentiles, no un modelo de machine learning entrenado.

Primero sumamos tiempos y contadores por operación y periodo. Después creamos TR y TAI, el funcionamiento sobre TR, la disponibilidad propia, la frecuencia por mil piezas, la duración media, el ciclo, la cobertura y las señales de calidad. Esta separación evita confundir el porcentaje de funcionamiento global con las pérdidas propias. Los denominadores cero quedan no definidos, nunca como un cero ficticio.

El color del mapa utiliza TBF/TR: a partir del objetivo del 90 %, verde; por debajo, la pérdida mayor entre TAP, DES y SAT. TAP gana empates; DES/SAT próximos combinan colores. Los elementos lentos también son verdes y se distinguen por el ciclo dentro de Funcionamiento aceptable. En paralelo, la gráfica que hemos mostrado filtra disponibilidad propia inferior al 90 %. Repetimos la regla por semana y contamos señales entre semanas evaluables para seguir la recurrencia.

Si preguntan por el ciclo: 6.000 × TBF / NPR, en centésimas de minuto por pieza. Otras variables propuestas en el README, como piezas perdidas, carga diaria o un índice de culpa, no se presentan como resultados validados.
"""
    slides.append(s)

    s = base("Aspectos clave de la interfaz", 6)
    s.text(48, 86, 864, 88, "Identificar, relacionar\ny comprobar la evolución.", 34, bold=True)
    for x in [48, 344, 640]:
        s.rect(x, 191, 272, 241, "FFFFFF", radius=True)
    s.text(66, 210, 238, 31, "Recurrencia", 21, NAVY, True)
    ex = facts['examples']['ST2235']
    s.text(66, 251, 238, 65, f"{int(ex['recurrence_own'])} / {int(ex['evaluable_week'])}", 47, TEAL, True)
    s.text(66, 319, 238, 44, "semanas con TAP predominante\nen ST2235", 14, GRAY)
    for index, row in enumerate(facts['weekly_example']):
        height = max(2, row['TAP_pct'] / 100 * 31)
        x = 72 + index * 56
        s.rect(x, 400 - height, 36, height, RED)
        s.text(x, 405, 39, 17, f"S{int(row['Week'])}", 10, GRAY, align="center")
    s.text(362, 210, 238, 31, "Relaciones", 21, NAVY, True)
    s.rect(362, 257, 236, 36, RED, radius=True)
    s.text(371, 265, 218, 23, "TAP de la seleccionada", 14, "FFFFFF", True, "center")
    for x, label, color in [(362, "DES", YELLOW), (486, "SAT", ORANGE)]:
        s.rect(x, 308, 112, 34, color, radius=True)
        s.text(x + 8, 315, 96, 23, label, 14, NAVY, True, "center")
    s.text(362, 359, 238, 48, "Contrastar señales en\nlos mismos días.", 16, GRAY)
    s.text(362, 410, 238, 17, "Causalidad pendiente de validar.", 11, GRAY)
    s.text(658, 210, 238, 31, "Escalabilidad", 21, NAVY, True)
    s.text(658, 254, 238, 68, "CSV +\nconfiguración", 25, TEAL, True)
    s.text(658, 334, 238, 57, "Otras líneas y periodos\ncon el mismo contrato diario.", 16, GRAY)
    s.text(658, 395, 238, 32, "Unidades, objetivos y calendario\nconfigurables.", 12, GRAY)
    s.rect(48, 452, 864, 41, NAVY, radius=True)
    s.text(64, 462, 832, 28, "Una prioridad que se puede explicar y seguir después de intervenir.", 18, "FFFFFF", True, "center")
    s.notes = """06:15–07:40 · 1 minuto 25 segundos

Estos son los tres aspectos que queremos destacar en la interfaz. La recurrencia permite ver si una señal reaparece en semanas comparables: en ST2235, TAP predomina en las cuatro semanas evaluables. No son cuatro averías contadas ni una predicción; es evolución de una señal que permite orientar el seguimiento.

Las relaciones permiten contrastar TAP de una operación con DES o SAT de otras en los mismos días. Así exploramos posibles efectos sobre el flujo y posibles fuentes de espera, sin afirmar que una máquina haya causado la parada de otra. Para demostrarlo harían falta topología y eventos con hora de inicio y fin.

La escalabilidad se basa en un contrato de datos configurable. La entrada permite elegir línea; las líneas se ordenan por máquinas con señales, y el mismo procedimiento admite otros periodos, unidades y objetivos. Estos CSV tienen una única línea; no presentamos un despliegue industrial a gran escala ni una prueba de rendimiento que no hayamos realizado. El diagnóstico y sus registros permiten revisar las decisiones después de una actuación.

07:40–08:00 · Cierre · 20 segundos
«LOSSIA transforma registros diarios en prioridades explicables: valida el dato, distingue pérdidas propias de esperas y permite comprobar cómo evolucionan las operaciones. El siguiente paso es contrastar las causas con planificación y eventos de planta».
"""
    slides.append(s)
    return slides


def rgb(value):
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def export(slides):
    import fitz
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

    presentation = Presentation()
    presentation.slide_width, presentation.slide_height = Inches(W / 72), Inches(H / 72)
    presentation.core_properties.title = "LOSSIA · Pitch del Hackathon HORSE"
    presentation.core_properties.subject = "6 slides: herramienta final, EDA, solución e interfaz · 8 minutos"
    presentation.core_properties.author = "Equipo LOSSIA"
    pdf = fitz.open()
    alignments = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}
    for data in slides:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string(data.background)
        page = pdf.new_page(width=W, height=H)
        page.draw_rect(page.rect, color=None, fill=rgb(data.background))
        page.insert_font(fontname="ArialPitch", fontfile="C:/Windows/Fonts/arial.ttf")
        page.insert_font(fontname="ArialPitchBold", fontfile="C:/Windows/Fonts/arialbd.ttf")
        for element in data.elements:
            kind, x, y, width, height, *attrs = element
            rect = fitz.Rect(x, y, x + width, y + height)
            if kind == "rect":
                fill, stroke, rounded = attrs
                shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
                                               Inches(x / 72), Inches(y / 72), Inches(width / 72), Inches(height / 72))
                if rounded:
                    shape.adjustments[0] = .1
                shape.fill.solid(); shape.fill.fore_color.rgb = RGBColor.from_string(fill)
                if stroke:
                    shape.line.color.rgb = RGBColor.from_string(stroke)
                else:
                    shape.line.fill.background()
                page.draw_rect(rect, color=rgb(stroke) if stroke else None, fill=rgb(fill), radius=.08 if rounded else None)
            elif kind == "text":
                text, size, color, bold, align = attrs
                box = slide.shapes.add_textbox(Inches(x / 72), Inches(y / 72), Inches(width / 72), Inches(height / 72))
                tf = box.text_frame
                tf.clear(); tf.word_wrap = True
                tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
                tf.vertical_anchor = MSO_ANCHOR.TOP
                for i, line in enumerate(text.split("\n")):
                    paragraph = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    paragraph.text = line
                    paragraph.alignment = alignments[align]
                    paragraph.line_spacing = 1.08
                    paragraph.space_after = Pt(0)
                    for run in paragraph.runs:
                        run.font.name, run.font.size, run.font.bold = "Arial", Pt(size), bold
                        run.font.color.rgb = RGBColor.from_string(color)
                remaining = page.insert_textbox(rect, text, fontsize=size, fontname="ArialPitchBold" if bold else "ArialPitch",
                                               color=rgb(color), align={"left": 0, "center": 1, "right": 2}[align], lineheight=1.08)
                if remaining < -.01:
                    raise ValueError(f"Texto no cabe: {text!r}: {remaining}")
            elif kind == "image":
                path = attrs[0]
                slide.shapes.add_picture(path, Inches(x / 72), Inches(y / 72), Inches(width / 72), Inches(height / 72))
                page.insert_image(rect, filename=path)
        slide.notes_slide.notes_text_frame.text = data.notes
    presentation.save(OUT / "LOSSIA_Pitch_8_minutos.pptx")
    pdf.set_metadata({"title": "LOSSIA · Pitch 8 minutos", "author": "Equipo LOSSIA"})
    pdf.save(OUT / "LOSSIA_Pitch_8_minutos.pdf", garbage=4, deflate=True)
    for i, page in enumerate(pdf):
        page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False).save(ASSETS / f"slide_{i + 1}.png")
    pdf.close()


def write_script(slides):
    content = """# LOSSIA · Guion de 6 diapositivas · 8 minutos

## Orden y tiempos

| Slide | Contenido | Tiempo | Duración |
| --- | --- | --- | --- |
| 1 | LOSSIA y propuesta de valor | 00:00–00:30 | 30 s |
| 2 | Índice | 00:30–00:50 | 20 s |
| 3 | Herramienta final + demo de Streamlit | 00:50–03:00 | 2 min 10 s |
| 4 | EDA: problemas del CSV y decisiones | 03:00–04:35 | 1 min 35 s |
| 5 | Solución técnica y variables creadas | 04:35–06:15 | 1 min 40 s |
| 6 | Recurrencia, relaciones y escalabilidad | 06:15–07:40 | 1 min 25 s |
| — | Cierre sobre la slide 6 | 07:40–08:00 | 20 s |

Total: 8 minutos. La demo forma parte de la slide 3; no hay una demo adicional de cuatro minutos después de las slides. El EDA (30 % de evaluación) se apoya en hallazgos auditables; la solución (40 %) se explica con implementación y variables; la interfaz (15 %) se demuestra en directo y el pitch (15 %) se cuida con transiciones y cierre.

## Texto y notas del presentador

"""
    for index, slide in enumerate(slides, start=1):
        content += f"### Slide {index}\n\n{slide.notes}\n\n"
    content += """## Demo: recorrido exacto de la slide 3

Antes de empezar: abrir Streamlit, dejar semanas 40–43, escenario provisional y objetivo 90 %. Preparar la ventana para cambiar con Alt+Tab. Los números de las slides corresponden a ese alcance.

| Tiempo | Acción | Qué señalar |
| --- | --- | --- |
| 00:50–01:05 | Mantener la slide 3. | Cinco operaciones comparables con TBF/(TBF + TAP) <90 %. La imagen es la gráfica real de respaldo. |
| 01:05–01:25 | Abrir Streamlit, entrar en VLL_MONTAJE_L5. | Selección por línea y PM2130 destacada: TBF cero, TAP 351,87 h; confirmar si debía trabajar. |
| 01:25–02:10 | Entrar en Máquinas más problemáticas. | Cinco barras filtradas por disponibilidad propia, con TAP rojo, DES amarillo y SAT naranja. No confundir Dp con TBF/TR. |
| 02:10–02:45 | Volver al mapa, elegir Por urgencia de reparación y Parada propia; abrir ST2235. | Colores agrupados, TBF/TR creciente dentro de cada grupo, ficha explicable, posibles efectos y diagnóstico PDF. |
| 02:45–03:00 | Volver a la slide 4. | Transición: «Para llegar a este resultado, primero entendimos los problemas del dato». |

No abrir un PDF durante el recorrido si eso retrasa la demo. Si Streamlit no carga, usar la imagen de la slide 3 y continuar: no consumir la exposición arreglando el entorno.

## Cobertura de la lista Por hacer del README

| Puntos | Dónde y cómo se incorporan |
| --- | --- |
| 1 y 13: validación y limpieza | Slide 4: claves, tipos, duplicados, señales de incoherencia y trazabilidad. Contraste manual con Excel pendiente. |
| 2 y 3: fechas, cierres y festivos | Slide 4: calendario opcional, escenario provisional y convención de fecha pendiente; no se confirman festivos. |
| 4 y 6: operaciones y zonas | Slide 4 y 6: catálogo completo en estos datos; zonas solo si se documentan. No se deducen de nombres. |
| 5 y 7: duración y frecuencia | Slide 5: media y FPM creadas; microparadas combinan frecuencia alta y media breve fiable. |
| 8 y 18: mapa y navegación | Demo y slide 6: línea → operación, colores y diagnóstico. El orden no es una conexión física. |
| 9: método generalizable | Slide 5 y 6: pipeline, contrato diario, unidades, objetivos y calendario configurables. |
| 10 y 14: ciclo y funcionamiento | Slide 5: Dp, TBF/TR y ciclo distintos; elementos lentos dentro de Funcionamiento aceptable. |
| 11: picking/kitting y logística | Slide 4 y 6: hipótesis pendientes de contexto, material y eventos; no atribuir causas humanas. |
| 12: análisis por periodo y semana | Slide 6: recurrencia y semanas evaluables; no se confunden semanas con eventos de avería. |
| 15: notebook | Slide 4: EDA recalculado; documentos completos en el PDF de análisis exploratorio. |
| 16: nuevas variables | Slide 5: TR, TAI, reparto, FPM, media, ciclo, cobertura, TAP/1.000 piezas y recurrencia. Índice de culpa, carga y piezas perdidas no se presentan como resultados validados. |
| 17: decisión | Demo y slide 6: identificar candidatas, explicar el dato y comprobar evolución; no se promete impacto causal o producción recuperable. |

## Consideraciones de presentacion.md

1. Calendario: las cuatro jornadas sin actividad tienen TBF y producción cero, pero sí TAP=22 h. La exclusión es provisional, no una confirmación de festivos. La mediana Dp pasa del 76,19 al 98,37 %, sin que ello signifique una mejora física del proceso.
2. Selector de línea: se muestra al comenzar la demo. Las líneas se ordenan por operaciones con señales de parada; estos CSV contienen una única línea.
3. Elementos lentos: la nota antigua del azul ya no corresponde a la interfaz. Ahora son verdes y se distinguen al desplegar Funcionamiento aceptable y por su ciclo.
4. TBF cero: PM2130 se muestra separada al principio, conserva TAP y requiere validar planificación. ST_0030 tiene todos sus tiempos a cero y no debe confundirse con esa parada propia registrada.

## Fórmulas de respaldo para preguntas

- TR = TBF + TAP + DES + SAT; TAI = DES + SAT.
- Funcionamiento (%) = 100 × TBF / TR: decide si el mapa alcanza el objetivo.
- Disponibilidad propia (%) = 100 × TBF / (TBF + TAP): filtra la gráfica de cinco prioridades.
- FPM = 1.000 × NAP / NPR; media por parada (min) = 60 × TAP / NAP.
- Ciclo (cmin/pieza) = 6.000 × TBF / NPR; TAP/1.000 piezas = 1.000 × TAP / NPR.
- Recurrencia = semanas con señal entre semanas evaluables. Se conserva el denominador; no es un conteo de averías ni una predicción.
- Los indicadores usan sumas del mismo alcance antes de dividir. Denominador cero significa valor no definido.
- Las relaciones son coincidencias diarias. No se mide solapamiento de eventos, propagación causal ni buffers sin topología y marcas temporales.

## Fuentes y comprobaciones

Datos recalculados sobre los CSV actuales con cleaning.py, analysis.py y diagnostics.py. Las diapositivas reflejan el funcionamiento vigente de Streamlit. Respaldo documental: LOSSIA_Analisis_exploratorio.pdf y LOSSIA_Solucion_presentada.pdf.

La presentación conserva seis slides editables y notas del presentador, además de un PDF. El cierre está en la slide 6; no requiere una séptima diapositiva.
"""
    (OUT / "LOSSIA_Guion_8_minutos.md").write_text(content, encoding="utf-8")


def main():
    OUT.mkdir(exist_ok=True); ASSETS.mkdir(exist_ok=True)
    if "--prepare" in sys.argv:
        prepare()
        return
    facts = json.loads((ASSETS / "datos_presentacion.json").read_text(encoding="utf-8"))
    slides = create_slides(facts)
    assert len(slides) == 6
    export(slides)
    write_script(slides)
    print("Presentación PPTX, PDF y guion de 8 minutos generados.")


if __name__ == "__main__":
    main()
