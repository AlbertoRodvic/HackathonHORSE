"""PDF locales y reproducibles del criterio y del diagnóstico por operación."""

import argparse
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import reportlab
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from analysis import (STATUS_COLORS, TIME_COLORS, Settings, analyse, order_operations,
                      propagation_evidence, state_explanation, validate_connections)
from cleaning import DAY_KEYS, DAY_LABELS, FLAGS, TIMES, prepare_data, select_scenario
from diagnostics import (critical_candidates, impact_pairs, impact_summary, microstop_assessment,
                         priority_figure, total_stops)

WIDTH = A4[0] - 84
NAVY = colors.HexColor("#14253f")
LIGHT = colors.HexColor("#eef3f9")
FONT_DIR = Path(reportlab.__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("Lossia", str(FONT_DIR / "Vera.ttf")))
pdfmetrics.registerFont(TTFont("Lossia-Bold", str(FONT_DIR / "VeraBd.ttf")))
STYLES = getSampleStyleSheet()
for style in STYLES.byName.values():
    style.fontName = "Lossia"
STYLES.add(ParagraphStyle("BodyLossia", fontName="Lossia", fontSize=9, leading=14, spaceAfter=8, textColor=NAVY))
STYLES.add(ParagraphStyle("TitleLossia", fontName="Lossia-Bold", fontSize=29, leading=36, spaceAfter=20, textColor=NAVY))
STYLES.add(ParagraphStyle("HeadingLossia", fontName="Lossia-Bold", fontSize=16, leading=21, spaceBefore=10, spaceAfter=12, textColor=NAVY))
STYLES.add(ParagraphStyle("SmallLossia", fontName="Lossia", fontSize=7.1, leading=10, spaceAfter=4, textColor=NAVY))
STYLES.add(ParagraphStyle("CellLossia", fontName="Lossia", fontSize=7.6, leading=11, textColor=NAVY))
STYLES.add(ParagraphStyle("HeaderLossia", fontName="Lossia-Bold", fontSize=7.6, leading=11, textColor=colors.white))


def text_color(hex_color):
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    luminance = sum(v * w for v, w in zip(linear, [0.2126, 0.7152, 0.0722]))
    return "#ffffff" if (1.05 / (luminance + 0.05)) >= ((luminance + 0.05) / 0.05) else "#000000"


def fmt(value, digits=2):
    return "No definido" if pd.isna(value) else f"{value:,.{digits}f}"


def p(text, style="BodyLossia"):
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), STYLES[style])


def heading(text):
    return p(text, "HeadingLossia")


def table(headers, rows, widths=None):
    content = [[p(x, "HeaderLossia") for x in headers]]
    content += [[x if isinstance(x, (Paragraph, Drawing)) else p(x, "CellLossia") for x in row] for row in rows]
    result = Table(content, colWidths=widths or [WIDTH / len(headers)] * len(headers), repeatRows=1, hAlign="LEFT")
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, colors.HexColor("#dbe3ed")),
    ]))
    return result


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, A4[1] - 24, A4[0], 24, fill=1, stroke=0)
    canvas.setFont("Lossia-Bold", 8)
    canvas.setFillColor(colors.white)
    canvas.drawString(42, A4[1] - 16, "LOSSIA  /  CRITERIO UNIFICADO DE PARADAS")
    canvas.setFillColor(colors.HexColor("#627188"))
    canvas.setFont("Lossia", 7)
    canvas.drawString(42, 25, "Uso interno · Evidencia diaria agregada · No acredita causalidad")
    canvas.drawRightString(A4[0] - 42, 25, f"Página {doc.page}")
    canvas.restoreState()


def _build(story, title):
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=42, leftMargin=42,
                            topMargin=46, bottomMargin=43, title=title, author="Equipo LOSSIA")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return output.getvalue()


def _image(fig, max_height=260):
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buffer.seek(0)
    image = Image(buffer)
    scale = min(WIDTH / image.imageWidth, max_height / image.imageHeight)
    image.drawWidth, image.drawHeight = image.imageWidth * scale, image.imageHeight * scale
    return image


def map_drawing(operations):
    columns, cell_width, row_height = 9, WIDTH / 9, 32
    height = max(1, int(np.ceil(len(operations) / columns))) * row_height
    drawing = Drawing(WIDTH, height)
    for index, row in enumerate(operations.itertuples()):
        x = (index % columns) * cell_width
        y = height - (index // columns + 1) * row_height
        color = STATUS_COLORS[row.status]
        drawing.add(Rect(x + 2, y + 3, cell_width - 4, row_height - 6, rx=4, ry=4,
                         fillColor=colors.HexColor(color), strokeColor=None))
        if row.status == "Mixto":
            drawing.add(Rect(x + cell_width / 2, y + 3, cell_width / 2 - 2, row_height - 6,
                             fillColor=colors.HexColor(STATUS_COLORS["Desabastecimiento"]), strokeColor=None))
        drawing.add(String(x + cell_width / 2, y + 13, str(row.Operacion), fontName="Lossia-Bold",
                           fontSize=6.2, textAnchor="middle", fillColor=colors.HexColor(text_color(color))))
    return drawing


def _source_table(source_info):
    rows = [(name, str(value)) for name, value in (source_info or {}).items()]
    return table(["Fuente", "Identificación / huella SHA-256"], rows or [["Entrada", "Datos proporcionados al generador"]], [110, WIDTH - 110])


def _scope(records, days, scenario):
    periods = days.Periodo.sort_values().unique() if not days.empty else []
    return (f"Escenario: {scenario}. Jornadas-línea incluidas: {len(days)}. Registros incluidos: {len(records)}. "
            + (f"Rango registrado: {periods[0]} a {periods[-1]}. " if len(periods) else "No hay jornadas incluidas. ")
            + "Year/Week/Jour no se convierten a fechas civiles sin confirmar la convención del sistema.")


def _legend(settings):
    rows = [
        ("Sin datos", "Ningún registro utilizable en el periodo; no se sustituye por ceros."),
        ("Revisar datos", "Cobertura inferior al 100%, producción sin TBF o funcionamiento sin piezas en el agregado."),
        ("Sin producción", "NPR=0 y TBF=0. Confirmar si debía trabajar o sufrió una parada total."),
        ("Parada propia", f"TBF/TR < {settings.availability_target:g}% y TAP es la pérdida mayor. TAP tiene prioridad en empates. Rojo."),
        ("Desabastecimiento", f"TBF/TR < {settings.availability_target:g}% y DES predomina entre las pérdidas. Amarillo."),
        ("Saturación", f"TBF/TR < {settings.availability_target:g}% y SAT predomina entre las pérdidas. Naranja."),
        ("Funcionamiento aceptable", f"TBF/TR >= {settings.availability_target:g}%. Verde."),
    ]
    return [(name, description) for name, description in rows if name in STATUS_COLORS]


def legend_table(settings):
    rows = _legend(settings)
    content = []
    for index, (name, _) in enumerate(rows, start=1):
        background = STATUS_COLORS[name]
        style = ParagraphStyle(f"Legend{index}", parent=STYLES["CellLossia"],
                               textColor=colors.HexColor(text_color(background)))
        label = Paragraph(escape(f"{index}. {name}"), style)
        if name == "Mixto":
            label = mixed_label(f"{index}. Mixto", 151)
        content.append([label, rows[index - 1][1]])
    result = table(["Precedencia / color", "Condición y significado"], content, [165, WIDTH - 165])
    for index, (name, _) in enumerate(rows, start=1):
        background = STATUS_COLORS[name]
        result.setStyle(TableStyle([("BACKGROUND", (0, index), (0, index), colors.HexColor(background))]))
    return result


def mixed_label(label, width):
    drawing = Drawing(width, 22)
    for x, color in [(0, STATUS_COLORS["Saturación"]), (width / 2, STATUS_COLORS["Desabastecimiento"])]:
        drawing.add(Rect(x, 0, width / 2, 22, fillColor=colors.HexColor(color), strokeColor=None))
    drawing.add(String(5, 7, label, fontName="Lossia-Bold", fontSize=8,
                       fillColor=colors.HexColor(text_color(STATUS_COLORS["Mixto"]))))
    return drawing


def classification_report(settings, line, weeks, scenario):
    """PDF breve que comparte las reglas y la leyenda del diagnóstico."""
    return _build([
        p("Criterios de clasificación y colores", "TitleLossia"),
        p(f"Línea: {line}. Semanas: {', '.join(f'{year}-S{week}' for year, week in weeks)}. Escenario: {scenario}."),
        heading("Umbrales y precedencia"),
        p(f"Condición previa para TAP, DES y SAT: TBF/TR < {settings.availability_target:g}%. "
          "Si el funcionamiento alcanza el objetivo no se activan señales de parada. Después se aplica la división por tipo de pérdida."),
        p("Por debajo del objetivo, el color corresponde al mayor tiempo entre TAP, DES y SAT. "
          "TAP gana los empates. Si TAP no es el mayor y DES/SAT difieren por un factor inferior a 1,5, "
          "se muestran naranja y amarillo a la vez; en otro caso, el mayor de DES y SAT. "
          "La disponibilidad propia, 100 × TBF / (TBF + TAP), se conserva como indicador y no decide el color."),
        p(f"TR = TBF + TAP + DES + SAT. Ciclo = 6000 × TBF (h) / NPR. Dentro de Funcionamiento aceptable, "
          f"el ciclo divide buen funcionamiento y elementos lentos con objetivo {settings.cycle_target_cmin:g} cmin/pieza. "
          "Los problemas de cobertura y coherencia tienen prioridad sobre la clasificación operativa."),
        legend_table(settings),
        heading("Lectura de los resultados"),
        p("Mixto se representa mitad naranja y mitad amarillo. Los filtros por categoría "
          "solo cambian las máquinas visibles. Las cajas muestran únicamente el nombre de la máquina. "
          "Los colores resumen el periodo; las coincidencias diarias no prueban causalidad y un elemento lento no confirma una avería."),
        p("Por urgencia de reparación agrupa por color: TAP, SAT, DES, mixto y funcionamiento aceptable; los casos de datos se muestran aparte. "
          "Dentro de cada grupo ordena de menor a mayor TBF/TR. Los empates se resuelven por orden configurado y nombre; los porcentajes no definidos se sitúan al final de su grupo."),
    ], "LOSSIA · Criterios de clasificación y colores")


def technical_report(prepared, records, days, result, settings, scenario, *, connections=None, source_info=None, selected_weeks=None):
    """Informe metodológico con datos y gráficas del escenario elegido."""
    story = [Spacer(1, 55), p("Entender la parada.\nElegir dónde actuar.", "TitleLossia"),
             p("Informe técnico de EDA, limpieza, análisis y mapa de operaciones"),
             p("Criterio operativo unificado · Versión 1.1 · Reglas explicables y configurables"), Spacer(1, 20)]
    story.append(table(["Objetivo del reto", "Respuesta de la solución"], [
        ["1. Analizar las paradas", "Tiempos propios e inducidos, disponibilidad, ciclo, frecuencia, duración y recurrencia."],
        ["2. Crear una solución tecnológica", "Una misma preparación y un mismo clasificador alimentan mapa, tablas, filtros y PDF."],
        ["3. Versión simplificada", "Mapa primero: nombre + color. El detalle y la evidencia aparecen al seleccionar una operación."],
    ], [140, WIDTH - 140]))
    story += [Spacer(1, 18), p("El color expresa un patrón observado durante un periodo. No es un estado en tiempo real ni una prueba de avería, sensor defectuoso o responsabilidad sobre otra máquina."),
              p(_scope(records, days, scenario)), PageBreak(), heading("1 · EDA: qué información existe y qué falta")]
    story.append(table(["Comprobación", "Resultado"], [[str(k), str(v)] for k, v in prepared.audit.items()], [300, WIDTH - 300]))
    story += [p(f"Configuración: {len(prepared.configuration)} operaciones en {prepared.configuration.Linea.nunique()} líneas. "
                "La granularidad aceptada es una fila por línea, operación, año, semana y día. Si existen turnos o eventos separados, hay que adaptar la clave antes de usar estas reglas."),
              p("La cobertura se contrasta con las operaciones de configuración. Una operación ausente no se interpreta como parada ni como producción cero. El calendario puede revelar días completamente ausentes; sin él no se conoce todo el universo de jornadas previstas.")]
    flags = prepared.records[FLAGS].sum()
    story.append(table(["Señal de revisión", "Registros"], [[key, str(int(value))] for key, value in flags.items()], [360, WIDTH - 360]))
    story += [heading("Días sin actividad y análisis de sensibilidad"),
              p("Un festivo civil no demuestra un cierre de fábrica. Se admite un calendario de planificación opcional; los cierres por convenio, turnos especiales y paradas generales requieren contexto de planta. TBF=0 y TAP=22 por sí solos no identifican una avería.")]
    day_counts = prepared.days.groupby("day_status").size()
    story.append(table(["Estado del día", "Jornadas-línea"], [[DAY_LABELS.get(k, k), str(v)] for k, v in day_counts.items()], [370, WIDTH - 370]))
    comparisons = []
    for label, key in [("Todos los datos", "all"), ("Solo cierres confirmados excluidos", "confirmed"), ("Sin actividad pendiente excluida (provisional)", "provisional")]:
        # Restringir a las semanas incluidas en el informe, no a un calendario distinto.
        weeks = selected_weeks if selected_weeks is not None else list(map(tuple, prepared.days[["Year", "Week"]].drop_duplicates().to_numpy()))
        r, d = select_scenario(prepared, key, weeks)
        analysis = analyse(r, d, prepared.configuration, settings)
        eligible = analysis.operations.loc[analysis.operations.eligible]
        comparisons.append([label, str(len(d)), str(len(eligible)), str(int(eligible.availability_pct.lt(settings.availability_target).sum()))])
    story.append(table(["Escenario", "Días-línea", "Comparables", "Bajo objetivo propio"], comparisons, [265, 70, 75, WIDTH - 410]))
    story += [PageBreak(), heading("Distribuciones y balance de tiempo")]
    if not prepared.records.empty:
        profile = prepared.records[TIMES + ["NAP", "NPR"]].describe(percentiles=[0.5, 0.95])
        rows = [[name, fmt(profile.loc["min", name]), fmt(profile.loc["50%", name]),
                 fmt(profile.loc["95%", name]), fmt(profile.loc["max", name])] for name in profile.columns]
        story.append(table(["Variable", "Mínimo", "Mediana", "P95", "Máximo"], rows))
        total = prepared.records[TIMES].sum(axis=1)
        story.append(p(f"Perfil de todos los registros utilizables antes de seleccionar calendario. Tiempos en horas. "
                       f"Registros sin piezas: {int(prepared.records.NPR.eq(0).sum())}; sin tiempo registrado: {int(total.eq(0).sum())}; "
                       f"fuera de la referencia horaria: {int(prepared.records.time_reference_mismatch.sum())}. "
                       "P95 es el valor por debajo del que queda el 95% de observaciones. Los extremos se investigan; no se recortan automáticamente."))
        fig = Figure(figsize=(9, 3.3))
        ax = fig.subplots()
        ax.hist(total, bins=30, color="#4b87bb", edgecolor="white")
        reference = prepared.days.reference_hours.median()
        ax.axvline(reference, color="#dc4848", linestyle="--", label=f"Referencia mediana: {reference:g} h")
        ax.set(xlabel="TBF + TAP + DES + SAT (h / operación / día)", ylabel="Registros")
        ax.legend(fontsize=8)
        fig.tight_layout()
        story += [_image(fig, 200), p("El histograma muestra concentración, huecos y excesos de tiempo. No demuestra por sí solo un error: pueden existir jornadas distintas, redondeos o información incompleta. La referencia real puede variar por día según el calendario.")]
    else:
        story.append(p("No hay registros utilizables para calcular distribuciones."))
    story += [PageBreak(), heading("2 · Limpieza y trazabilidad"),
              p("Los archivos originales no se reescriben. Se normalizan espacios, tipos y unidades; no se cambian identificadores ni se imputan tiempos o piezas. Source_Row identifica el ordinal del registro de origen contando la cabecera, no una fecha ni un identificador de motor."),
              table(["Regla", "Tratamiento y motivo"], [
                  ["Cabeceras y texto", "strip() en cabeceras e identificadores. Las cabeceras repetidas y configuración ambigua se rechazan."],
                  ["Copias idénticas", "Se conserva una copia y se registra qué copias se retiraron. Se detectan antes de añadir Source_Row."],
                  ["Clave diaria repetida con datos distintos", "Se apartan todas las versiones contradictorias; no se suman como si fueran turnos ni se elige una arbitrariamente."],
                  ["Rangos", "Año 1-9999, semana 1-53, día 1-7; valores finitos y no negativos; NAP y NPR enteros. No valida por sí solo la existencia de una fecha ISO."],
                  ["Configuración", "Unión validada por Linea + Operacion. Orden_OP repetido puede ser legítimo en paralelo. No crea conexiones físicas."],
                  ["Unidades", "Entrada en horas, minutos o segundos; salida de tiempos en horas. El calendario siempre indica Planned_Hours en horas."],
                  ["Señales operativas dudosas", "Se conservan. NPR>0 con TBF=0 invalida el ciclo. TAP/NAP diario incoherente impide usar la media para señalar microparadas."],
                  ["Balance horario", "Se contrasta con Planned_Hours o la referencia configurable (22 h por defecto), con tolerancia de 0,10 h. No se fuerza el total ni se elimina por ese motivo."],
                  ["Calendario", "Un día previsto se conserva aunque toda la línea se pare. Si un cierre tiene actividad registrada, se conserva como contradicción a revisar. Motivo es un texto opcional aportado por la planta; no se infiere."],
              ], [140, WIDTH - 140]),
              p("El análisis provisional excluye días completos sin actividad únicamente cuando la cobertura es completa y no consta producción prevista. El usuario puede incluirlos y contrastar el resultado. La exclusión no determina su causa."),
              PageBreak(), heading("3 · Variables: matemáticas y unidades")]
    formulas = [
        ["TR registrado", "TBF + TAP + DES + SAT", "Horas clasificadas; no se impone TR=22."],
        ["TAI", "DES + SAT", "Horas inducidas."],
        ["Disponibilidad propia", "100 × TBF / (TBF + TAP)", "Porcentaje; objetivo actual configurable."],
        ["Funcionamiento / TR", "100 × TBF / TR", "Porcentaje productivo incluyendo esperas."],
        ["Peso de cada parada", "100 × TAP/TR; 100 × DES/TR; 100 × SAT/TR", "Porcentajes comparables entre periodos."],
        ["Peso propio en las paradas", "100 × TAP / (TAP + DES + SAT)", "Descripción del reparto; no prueba responsabilidad."],
        ["FPM", f"{settings.stop_rate_base} × NAP / NPR", f"Paradas por {settings.stop_rate_base} piezas. Base acordada para el reto: 1000."],
        ["Tiempo medio de parada", "60 × TAP / NAP", "Minutos/parada; TAP ya está en horas."],
        ["Ciclo de funcionamiento", "6000 × TBF / NPR", "cmin/pieza; 1 h = 6000 cmin y 1 cmin = 0,6 s."],
        ["TAP / 1000 piezas", "1000 × TAP / NPR", "Horas de parada propia por 1000 piezas."],
        ["Cobertura", "100 × días observados / días esperados", "Por operación y periodo seleccionado."],
    ]
    story += [table(["Variable", "Fórmula", "Interpretación"], formulas, [115, 180, WIDTH - 295]),
              p("Se suman tiempos y contadores antes de dividir. Ejemplo: 2 horas con 4 paradas y 1 hora con 1 parada dan (3 × 60)/5 = 36 minutos, no la media simple de 30 y 60 (=45). Un denominador cero deja el indicador sin definir."),
              p(f"Parámetros actuales: funcionamiento/TR >= {settings.availability_target:g}%; ciclo <= {settings.cycle_target_cmin:g} cmin/pieza. Disponibilidad propia y TBF/TR no son equivalentes. No se suma NPR de todas las estaciones como producción final, porque las mismas piezas pueden contarse varias veces."),
              PageBreak(), heading("4 · El criterio unificado y la leyenda")]
    story += [p("Se aplica la misma función de clasificación a cualquier línea y periodo con este esquema. Primero se comprueba si el dato permite interpretar el estado; después se evalúan las señales propias e inducidas; finalmente, el ciclo. No se decide por el TAP absoluto más alto ni por el nombre de la máquina."),
              legend_table(settings),
              p(f"Condición previa de cualquier señal: TBF/TR < {settings.availability_target:g}%. "
                "Después se elige el mayor tiempo de pérdida entre TAP, DES y SAT. TAP gana los empates. "
                "Si TAP no es el mayor y DES/SAT difieren por un factor inferior a 1,5, se muestran ambos colores. "
                "Las mismas señales alimentan filtros y recurrencia: un color inducido no queda fuera de su seguimiento por usar otra regla."),
              p("La media no modifica por sí sola el color principal. Señal de paradas frecuentes y breves: FPM >= P75 de operaciones comparables de la misma línea y media inferior al umbral breve. "
                f"Umbrales actuales: breve < {settings.short_stop_minutes:g} min; prolongada >= {settings.long_stop_minutes:g} min; P25 distingue pocas y prolongadas. Son hipótesis ajustables, no diagnósticos de sensores ni inventario de eventos."),
              PageBreak(), heading("5 · Mapa de operaciones: lectura y navegación"),
              p("La vista de línea comienza por el mapa. Cada caja contiene exclusivamente el nombre y el color. Se recorre en una fila horizontal desplazable o se abre la cuadrícula completa. Al pulsar una caja, se muestra su evidencia debajo y se permite descargar el diagnóstico PDF."),
              p("Orden de línea: Orden_OP y nombre para desempatar, sin inferir conexiones. Por urgencia de reparación: grupos de color TAP, SAT, DES, mixto y funcionamiento aceptable, con casos de datos aparte. Dentro de cada grupo, TBF/TR de menor a mayor. Los empates se resuelven por Orden_OP y nombre; los porcentajes no definidos quedan al final de su grupo. Es una cola de investigación, no una estimación causal de producción perdida."),
              p("El filtro por categoría permite desplegar Otros: Sin producción, Revisar datos y Sin datos. Funcionamiento aceptable reúne Buen funcionamiento y Elemento lento, con colores distintos y un filtro adicional entre ambos. Las paradas totales con TBF cero y TAP positivo se destacan al principio. Los filtros no cambian el color. La leyenda permanece fuera de las cajas.")]
    for line, operations in result.operations.groupby("Linea"):
        operations = order_operations(operations)
        for start in range(0, len(operations), 126):
            chunk = operations.iloc[start:start + 126]
            story += [heading(f"Mapa · {line}"), p(f"Operaciones {start + 1}-{start + len(chunk)} de {len(operations)}; orden de configuración. No es un plano físico ni un grafo de propagación.", "SmallLossia"), map_drawing(chunk), Spacer(1, 12)]
    story += [PageBreak(), heading("6 · Gráficas: qué pregunta responde cada una")]
    story.append(table(["Visualización", "Interpretación correcta"], [
        ["Barras por operación", "Cada barra es una operación y suma 100% de TR registrado. Distingue pérdidas propias, falta de suministro y bloqueo."],
        ["Reparto diario", "Cada barra es un día y suma horas-máquina. No representa cuánto tiempo estuvo parada la línea ni permite sumar piezas recuperables."],
        ["Frecuencia-duración", "Derecha: mayor FPM. Abajo: menor media. Tamaño: TAP. Las escalas logarítmicas hacen visibles órdenes de magnitud. Los puntos rojos son señales exploratorias."],
        ["Mapas semanales TAP/DES/SAT", "Cada mapa selecciona operaciones por su propia pérdida. Color 0-100% con la misma escala; texto con cobertura. La recurrencia cuenta periodos afectados, no averías independientes."],
    ], [140, WIDTH - 140]))
    for line, operations in result.operations.groupby("Linea"):
        comparison = priority_figure(operations, settings)
        if comparison is not None:
            story += [heading(f"Prioridades e indicadores · {line}"), _image(comparison),
                      p("Ampliación del último gráfico del apartado 4 del notebook. Las mismas operaciones aparecen en todos los paneles; líneas rojas: objetivos. Los ejes de FPM, ciclo y media usan escala simétrica logarítmica. La media no describe todos los eventos.")]
        selected = operations.loc[operations.TR.gt(0)].assign(loss=lambda f: f.TAP_pct + f.DES_pct + f.SAT_pct).nlargest(12, "loss")
        if not selected.empty:
            fig = Figure(figsize=(10, 4.5))
            ax = fig.subplots()
            selected.set_index("Operacion")[[f"{x}_pct" for x in TIMES]].rename(columns={f"{x}_pct": x for x in TIMES}).plot.barh(
                stacked=True, ax=ax, color=[TIME_COLORS[x] for x in TIMES])
            ax.invert_yaxis()
            ax.set(xlim=(0, 100), xlabel="Tiempo registrado (%)", ylabel="Operación", title=f"{line} · Hasta 12 operaciones con mayor peso de paradas")
            ax.legend(ncol=4, fontsize=8)
            fig.tight_layout()
            story += [_image(fig), p("Esta selección muestra peso de pérdidas, no una prueba de quién limita la salida de motores.", "SmallLossia")]
        points = operations.loc[operations.eligible & operations.stop_duration_reliable & operations.fpm.gt(0) & operations.mean_stop_minutes.gt(0)]
        if not points.empty:
            story += [PageBreak(), heading(f"Frecuencia y duración · {line}")]
            fig = Figure(figsize=(10, 5))
            ax = fig.subplots()
            ax.scatter(points.fpm, points.mean_stop_minutes, s=30 + 200 * points.TAP / points.TAP.max(),
                       c=np.where(points.short_frequent_signal, "#dc4848", "#4b87bb"), alpha=0.8)
            ax.axhline(settings.short_stop_minutes, linestyle="--", color="#dc4848", label="Umbral breve")
            ax.axhline(settings.long_stop_minutes, linestyle="--", color="#667085", label="Umbral prolongado")
            ax.axvline(points.frequency_p75.iloc[0], linestyle=":", color="#667085", label="P75 frecuencia")
            for row in points.nlargest(3, "fpm").itertuples():
                ax.annotate(row.Operacion, (row.fpm, row.mean_stop_minutes), xytext=(3, 4), textcoords="offset points", fontsize=8)
            ax.set(xscale="log", yscale="log", xlabel=f"Paradas / {settings.stop_rate_base} piezas", ylabel="Duración media (min)")
            ax.legend(fontsize=8)
            fig.tight_layout()
            story += [_image(fig), p("P75 es una referencia relativa dentro de la línea: pertenecer al cuartil superior no acredita una avería. La media puede mezclar eventos cortos y largos. Se excluyen del scatter las medias inconsistentes y las operaciones no comparables.")]
        weekly = result.weekly.loc[result.weekly.Linea.eq(line)]
        if not weekly.empty:
            story += [heading(f"Recurrencia · {line}")]
            for kind in ["TAP", "DES", "SAT"]:
                names = operations.nlargest(7, f"{kind}_pct").Operacion.tolist()
                heat = weekly.pivot(index="Operacion", columns=["Year", "Week"], values=f"{kind}_pct").reindex(names)
                if heat.empty:
                    continue
                fig = Figure(figsize=(9, 3.2))
                ax = fig.subplots()
                image = ax.imshow(heat.to_numpy(dtype=float), cmap="YlOrRd", vmin=0, vmax=100, aspect="auto")
                ax.set_yticks(range(len(heat)), heat.index)
                ax.set_xticks(range(len(heat.columns)), [f"{y}-S{w}" for y, w in heat.columns])
                for i in range(len(heat)):
                    for j in range(len(heat.columns)):
                        value = heat.iloc[i, j]
                        ax.text(j, i, f"{value:.1f}%" if pd.notna(value) else "Sin datos", ha="center", va="center", fontsize=8)
                ax.set_title(f"{kind}/TR · Selección propia de hasta 7 operaciones")
                fig.colorbar(image, ax=ax)
                fig.tight_layout()
                story += [_image(fig, 200), Spacer(1, 8)]
    story += diagnostic_story(result.operations, records, settings, connections)
    story += [PageBreak(), heading("7 · Relaciones entre máquinas y límites del diagnóstico"),
              p("Conexiones opcionales: CSV Linea, Origen, Destino. Se validan los identificadores y se recorren ramas aguas arriba y abajo sin crear enlaces a partir de Orden_OP. "
                "Con TAP relevante en la operación elegida, SAT coincidente aguas arriba y DES coincidente aguas abajo son compatibles con un efecto sobre el flujo. "
                "También se buscan operaciones con TAP coincidente aguas arriba del DES recibido y aguas abajo del SAT recibido."),
              p("Con acumulados diarios no se conoce el orden temporal de los eventos, su solapamiento ni el tiempo de vaciado de buffers. Ni siquiera una conexión y una coincidencia diaria demuestran causalidad. "
                "El PDF individual enumera hipótesis y evidencia, no responsables confirmados. Sin topología enumera coincidencias con conexión por confirmar. Se excluyen de esta comparación días de cierre, sin actividad pendiente o con calendario contradictorio."),
              p("No se atribuyen causas humanas, picking, kitting o sensores sin registros adicionales. No se estiman retardos, alcance causal de una onda ni piezas finales recuperables a partir de estas coincidencias."),
              heading("8 · Escalabilidad, pruebas y siguientes validaciones"),
              table(["Decisión de diseño", "Alcance y límite"], [
                  ["Separación de módulos", "cleaning prepara, analysis clasifica, reports explica y app visualiza. El informe puede generarse sin interfaz."],
                  ["Claves compuestas", "La misma operación puede existir en distintas líneas sin mezclar sus datos."],
                  ["Configuración y umbrales", "Rutas, unidades, periodo y objetivos ajustables. Actualmente los objetivos son comunes en una ejecución; objetivos por producto/operación requieren ampliar configuración."],
                  ["Metadatos opcionales", "Zona y Planta se conservan si existen. No se inventan zonas a partir del identificador."],
                  ["Pruebas sintéticas", "Duplicados, unidades, medias ponderadas, calendario, cobertura, varias líneas, señales inducidas y PDF. Verifican reglas, no la verdad de las causas industriales."],
                  ["Límite de datos", "El contrato es diario, con tablas en memoria. Grandes volúmenes, turnos o eventos requieren otra granularidad y evaluar rendimiento."],
              ], [140, WIDTH - 140]),
              p("Validación pendiente con la planta: significado de los contadores, calendario de trabajo, actividad prevista por operación, objetivos de disponibilidad y ciclo, topología y umbrales de microparadas. FPM acordado por 1000 piezas. "
                "Para comprobar que una actuación evita repetición se necesitan datos posteriores e incidencias comparables; no se predicen fallos con cuatro semanas de agregados."),
              PageBreak(), heading("Fuentes y parámetros del informe"), p(_scope(records, days, scenario)), _source_table(source_info),
              table(["Parámetro", "Valor"], [[k, str(v)] for k, v in asdict(settings).items()], [300, WIDTH - 300])]
    return _build(story, "LOSSIA · Informe técnico y criterio unificado")


def diagnostic_story(operations, records, settings, connections=None):
    story = [PageBreak(), heading("Validación del alcance tras identificar pérdidas propias")]
    candidates = critical_candidates(operations, records)
    pairs = impact_pairs(candidates, operations, records, settings, connections)
    summary = impact_summary(pairs)
    story.append(p("Se revisan todas las demás operaciones de la misma línea, incluyendo las que no tienen coincidencias o datos pareados. Se compara DES y SAT en días con y sin señal propia de la candidata. Cada media es 100 × suma de la espera / suma de TR. Se requieren al menos 3 días de cada grupo; diferencia positiva no implica significación estadística ni causalidad. No se suman horas inducidas como producción recuperable."))
    if not summary.empty:
        story.append(table(["Candidata", "Otras", "Con datos", "Coinciden", "Comparables", "Asoc. +", "Ruta compatible +"],
            [[r.candidate, r.other_operations, r.observed_operations, r.coincident_operations,
              r.comparable_operations, r.positive_operations, r.compatible_positive_operations] for r in summary.itertuples()],
            [85, 45, 55, 65, 75, 55, WIDTH - 380]))
        story.append(p("Coinciden: operaciones con DES/SAT relevante en algún día de señal propia. Comparables: disponen de los dos grupos de días. Asoc. +: espera mayor con señal propia y alguna coincidencia. Ruta compatible +: además hay conexión en la dirección esperada. Sin topología, esta última cifra es cero por falta de evidencia de ruta. La misma operación solo cuenta una vez, aunque presente DES y SAT. El detalle completo se exporta con run_analysis.py."))
    else:
        story.append(p("No hay parejas de candidatas y otras operaciones para analizar en este periodo."))
    stops = total_stops(records)
    story += [heading("Paradas totales: lista separada de investigación"),
              p("TBF=0 y NPR=0 con tiempo registrado. No desaparecen por exigir producción en el ranking habitual. La planificación disponible es de línea: siempre hay que confirmar si la operación concreta debía trabajar. Cierres y días pendientes no se consideran averías automáticamente.")]
    if stops.empty:
        story.append(p("No hay registros de parada total en el escenario seleccionado."))
    else:
        story.append(table(["Operación", "Periodo", "TAP h", "DES+SAT h", "Contexto"],
            [[r.Operacion, r.Periodo, fmt(r.TAP), fmt(r.DES + r.SAT), r.activity_context] for r in stops.itertuples()],
            [80, 90, 55, 70, WIDTH - 295]))
    micro, _ = microstop_assessment(records, settings)
    micro = micro.loc[micro.brief_frequent_days.gt(0)]
    story += [heading("Dónde pueden ser relevantes las microparadas"),
              p(f"Días con duración media < {settings.short_stop_minutes:g} min y FPM >= P75 de la línea calculado con agregados de días fiables por operación. Relevancia exploratoria: TAP de esos días >= {settings.microstop_loss_threshold_pct:g}% del TR de los días válidos. La cifra es TAP completo en días compatibles, no tiempo confirmado de microparadas. No son averías grandes confirmadas; la media puede mezclar interrupciones breves con eventos largos.")]
    if micro.empty:
        story.append(p("No hay días con ambas señales y contadores consistentes."))
    else:
        story.append(table(["Operación", "Días señal/válidos", "TAP días señal h", "% TR válido", "Relevante"],
            [[r.Operacion, f"{r.brief_frequent_days}/{r.valid_days}", fmt(r.tap_on_signal_days_h),
              fmt(r.tap_on_signal_days_pct), "Sí" if r.significant else "No"] for r in micro.itertuples()],
            [85, 100, 110, 95, WIDTH - 390]))
    story += [p("Prioridad alta: investigar pérdidas recurrentes y contrastar incidencias/intervenciones. Después de actuar, comparar TAP/TR, FPM y recurrencia con periodos de carga y producto similares. No se identifican averías repetidas concretas sin códigos de incidencia ni se predicen fallos con este histórico.")]
    return story


def operation_report(row, records, days, settings, scenario, *, connections=None, source_info=None):
    selected = records.loc[records.Linea.eq(row.Linea) & records.Operacion.eq(row.Operacion)].sort_values(DAY_KEYS)
    color = STATUS_COLORS[row['status']]
    if row['status'] == "Mixto":
        label = mixed_label("Mixto", WIDTH / 2 - 14)
    else:
        style = ParagraphStyle("StatusLabel", parent=STYLES["CellLossia"], textColor=colors.HexColor(text_color(color)))
        label = Paragraph(escape(row['status']), style)
    status = table(["Operación", "Estado del periodo"], [[p(row.Operacion, "CellLossia"), label]], [WIDTH / 2] * 2)
    status.setStyle(TableStyle([("BACKGROUND", (1, 1), (1, 1), colors.HexColor(color))]))
    story = [p(f"Diagnóstico · {row.Operacion}", "TitleLossia"), p(f"Línea: {row.Linea} · Orden configurado: {row.Orden_OP:g}"),
             status, Spacer(1, 12), p(_scope(selected, days.loc[days.Linea.eq(row.Linea)], scenario)),
             heading("Por qué tiene este color")]
    story += [p(reason) for reason in state_explanation(row, settings)]
    story += [p(row.recommendation), heading("Datos y cálculos que sustentan la decisión")]
    calculations = [["TBF / TAP / DES / SAT (h)", f"{fmt(row.TBF)} / {fmt(row.TAP)} / {fmt(row.DES)} / {fmt(row.SAT)}"],
                    ["Piezas y paradas registradas", f"NPR={fmt(row.NPR, 0)}; NAP={fmt(row.NAP, 0)}"],
                    ["Disponibilidad propia", f"100 × TBF / (TBF + TAP) = {fmt(row.availability_pct)}%"],
                    ["Ciclo de funcionamiento", f"6000 × TBF / NPR = {fmt(row.cycle_cmin)} cmin/pieza"],
                    [f"Paradas / {settings.stop_rate_base} piezas", fmt(row.fpm)],
                    ["Duración media de parada", f"60 × TAP / NAP = {fmt(row.mean_stop_minutes)} min"],
                    ["Media consistente para clasificar", "Sí" if row.stop_duration_reliable else "No; revisar contadores antes de interpretar duración"],
                    ["Cobertura", f"{int(row.observed_days)} / {int(row.expected_days)} días; {fmt(row.coverage_pct)}%"],
                    ["Recurrencia semanal", f"TAP {int(row.recurrence_own)}; DES {int(row.recurrence_des)}; SAT {int(row.recurrence_sat)}; semanas evaluables {int(row.evaluable_week)}"]]
    story += [table(["Indicador", "Evidencia"], calculations, [195, WIDTH - 195]),
              p("Los datos se agregan solo para la línea, operación, semanas y escenario seleccionados. Se conservan los días con parada real y se excluyen únicamente según el escenario. "
                "Un valor no definido no se interpreta como cero. Las filas señaladas no se corrigen inventando tiempos."),
              heading("Otras operaciones: efectos o fuentes que hay que contrastar")]
    has_topology = connections is not None and not connections.loc[connections.Linea.eq(row.Linea)].empty
    story.append(p("Hay conexiones aportadas por el usuario. La lista muestra operaciones conectadas con señales compatibles en el mismo día, no máquinas afectadas de forma demostrada."
                   if has_topology else "No se ha aportado la topología de esta línea. No se puede afirmar a qué máquinas afecta ni qué máquinas la afectan. "
                   "La lista siguiente contiene únicamente coincidencias diarias con conexión pendiente de confirmar; no se deduce la relación a partir del orden."))
    evidence = propagation_evidence(row, records, settings, connections)
    if evidence.empty:
        story.append(p("No se han encontrado coincidencias utilizables con las reglas y el periodo elegidos. Esto no demuestra ausencia de efectos."))
    else:
        rows = [[r.Operacion, r["Hipótesis"], r["Señal"], str(int(r["Días coincidentes"])),
                 fmt(r["Horas coincidentes"]), fmt(r.Distancia, 0) if has_topology else "No conocida"] for _, r in evidence.iterrows()]
        story.append(table(["Operación", "Hipótesis", "Señal", "Días", "Horas", "Saltos"], rows,
                           [70, WIDTH - 270, 45, 35, 55, 65]))
    story += [p("Las horas son el acumulado diario completo de la señal en días coincidentes, no horas de solapamiento con esta operación. "
                "Se excluyen cierres, días sin actividad pendientes de confirmar, calendarios contradictorios y producción sin funcionamiento. "
                "Sin eventos con marcas temporales no se conoce qué ocurrió primero, cuánto duró la propagación ni si intervino un buffer."),
              PageBreak(), heading("Registros seleccionados y trazabilidad")]
    if selected.empty:
        story.append(p("No hay registros utilizables de esta operación. Consultar la cobertura y los registros apartados."))
    else:
        rows = [[str(int(r.Source_Row)), r.Periodo, fmt(r.TBF), fmt(r.TAP), fmt(r.DES), fmt(r.SAT),
                 fmt(r.NAP, 0), fmt(r.NPR, 0)] for r in selected.itertuples()]
        story.append(table(["Registro", "Periodo", "TBF h", "TAP h", "DES h", "SAT h", "NAP", "NPR"], rows,
                           [44, 104, 55, 55, 55, 55, 70, WIDTH - 438]))
        story += [heading("Balance horario de los registros diarios"),
                  p("Balance = TBF + TAP + DES + SAT frente a la referencia de cada jornada. "
                    "Las etiquetas orientan la revisión de planificación, categorías y captura; no confirman una avería.")]
        balance_rows = [[str(int(r.Source_Row)), r.Periodo, fmt(r.recorded_hours), fmt(r.reference_hours),
                         fmt(r.balance_delta_minutes), fmt(r.balance_band_minutes), r.balance_label]
                        for r in selected.itertuples()]
        story.append(table(["Registro", "Periodo", "Horas registradas", "Horas referencia", "Desvío min", "Banda ± min", "Etiqueta"],
                           balance_rows, [44, 100, 65, 65, 55, 55, WIDTH - 384]))
    story += [heading("Fuentes y parámetros"), _source_table(source_info),
              table(["Parámetro", "Valor"], [[k, str(v)] for k, v in asdict(settings).items()], [300, WIDTH - 300])]
    return _build(story, f"LOSSIA · Diagnóstico de {row.Operacion}")


def file_identity(path):
    path = Path(path)
    return f"{path.name} | SHA-256 {sha256(path.read_bytes()).hexdigest()}"


def main():
    parser = argparse.ArgumentParser(description="Generar el informe técnico LOSSIA sin interfaz.")
    parser.add_argument("--data", default="data/datos_hackaton.csv")
    parser.add_argument("--config", default="data/config_hackaton.csv")
    parser.add_argument("--calendar")
    parser.add_argument("--connections")
    parser.add_argument("--scenario", choices=["all", "confirmed", "provisional"], default="provisional")
    parser.add_argument("--output", default="outputs/informe_tecnico_LOSSIA.pdf")
    args = parser.parse_args()
    calendar = pd.read_csv(args.calendar) if args.calendar else None
    prepared = prepare_data(pd.read_csv(args.data), pd.read_csv(args.config), calendar=calendar)
    links = validate_connections(pd.read_csv(args.connections), prepared.configuration) if args.connections else None
    records, days = select_scenario(prepared, args.scenario)
    settings = Settings()
    result = analyse(records, days, prepared.configuration, settings)
    sources = {"Producción": file_identity(args.data), "Configuración": file_identity(args.config),
               "Calendario": file_identity(args.calendar) if args.calendar else "No aportado",
               "Conexiones": file_identity(args.connections) if args.connections else "No aportadas"}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(technical_report(prepared, records, days, result, settings, args.scenario, connections=links, source_info=sources))
    print(f"Informe generado: {output.resolve()}")


if __name__ == "__main__":
    main()
