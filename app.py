import streamlit as st
import os
import io
import math
import requests
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether, PageBreak

st.set_page_config(
    page_title="Predice_Impago — Scoring de Inquilinos",
    page_icon="🏠", layout="centered", initial_sidebar_state="collapsed"
)

# Versión sin recogida de datos

def analizar_ocupantes(ocupantes):
    if not ocupantes:
        return 0.0, MESES_DESAHUCIO_BASE, [], "Sin información de ocupantes"
    meses_extra = 0; alertas = []; riesgo_vuln = 0.0
    menores = [o for o in ocupantes if "Menor" in o]
    mayores = [o for o in ocupantes if "65+" in o]
    bebes   = [o for o in ocupantes if "0-3" in o]
    adultos = [o for o in ocupantes if o == "Adulto (18-64)"]
    for o in ocupantes:
        riesgo_vuln = max(riesgo_vuln, RIESGO_OCUPANTE.get(o, 0.0))
        meses_extra = max(meses_extra, MESES_EXTRA.get(o, 0))
    if bebes:
        alertas.append(f"⚠️ {len(bebes)} menor(es) de 3 años — suspensión automática desahucio (Ley 12/2023)")
    if menores:
        alertas.append(f"⚠️ {len(menores)} menor(es) — proceso puede extenderse {MESES_DESAHUCIO_BASE + meses_extra} meses")
    if mayores:
        alertas.append(f"⚠️ {len(mayores)} mayor(es) de 65 años — protección especial según CCAA")
    if len(adultos) == 1 and menores:
        alertas.append("⚠️ Posible unidad monoparental con menor — categoría de vulnerabilidad especial")
    if len(menores) >= 2:
        alertas.append("⚠️ Dos o más menores — puede acogerse a ayudas de vivienda como argumento de paralización")
    nivel = "Sin alertas legales relevantes detectadas"
    if riesgo_vuln >= 0.15: nivel = "Vulnerabilidad muy alta"
    elif riesgo_vuln >= 0.10: nivel = "Vulnerabilidad alta"
    elif riesgo_vuln > 0: nivel = "Vulnerabilidad moderada"
    return riesgo_vuln, MESES_DESAHUCIO_BASE + meses_extra, alertas, nivel

# Perfil medio español para gráfico comparativo
PERFIL_MEDIO = {
    "Ratio alquiler/renta": 0.12,
    "Historial impagos": 0.00,
    "Contrato laboral": 0.08,
    "Antigüedad laboral": 0.06,
    "Fuente de ingresos": 0.06,
    "Mora CCAA": 0.13,
    "Sector laboral": 0.10,
    "Franja de edad": 0.09,
}

def riesgo_ratio(alquiler, nomina):
    if nomina <= 0: return 0.60
    r = alquiler / nomina
    if r <= 0.25: return 0.02
    if r <= 0.30: return 0.06
    if r <= 0.35: return 0.12
    if r <= 0.40: return 0.22
    if r <= 0.50: return 0.35
    return 0.55

@st.cache_data(show_spinner=False)
def calcular_score(edad, nomina, alquiler, contrato, antiguedad,
                   fuente, impagos, sector, ccaa, nacionalidad, ocupantes):
    r = {
        "Ratio alquiler/renta":  riesgo_ratio(alquiler, nomina),
        "Historial impagos":     RIESGO_IMPAGOS.get(impagos, 0.00),
        "Contrato laboral":      RIESGO_CONTRATO.get(contrato, 0.20),
        "Antigüedad laboral":    RIESGO_ANTIGUEDAD.get(antiguedad, 0.08),
        "Fuente de ingresos":    RIESGO_FUENTE.get(fuente, 0.10),
        "Mora CCAA":             MORA_POR_CCAA.get(ccaa, 0.13),
        "Sector laboral":        PARO_POR_SECTOR.get(sector, 0.12),
        "Franja de edad":        PARO_POR_EDAD.get(edad, 0.12),
    }
    pesos = [0.28, 0.22, 0.14, 0.10, 0.09, 0.07, 0.05, 0.03]
    score = sum(v * p for v, p in zip(r.values(), pesos))
    score += CORR_NAC.get(nacionalidad, 0.00) * 0.01
    # Vulnerabilidad de ocupantes afecta al score de impago
    riesgo_vuln, meses, alertas, nivel_vuln = analizar_ocupantes(ocupantes)
    score += riesgo_vuln * 0.05
    return round(min(0.90, max(0.02, score)), 4), r, riesgo_vuln, meses, alertas, nivel_vuln

def interpretar(prob):
    if prob < 0.08:
        return "Riesgo Bajo (orientativo)", "#16a34a", \
            "El perfil analizado presenta indicadores financieros sólidos. La índice de riesgo estimado se sitúa en niveles bajos según los parámetros evaluados.", \
            "El ratio de esfuerzo y la estabilidad laboral están dentro de márgenes favorables."
    if prob < 0.18:
        return "Riesgo Moderado (orientativo)", "#d97706", \
            "El perfil presenta alguna variable con indicadores de atención. La índice de riesgo estimado es moderada.", \
            "Existen factores de riesgo menores. Considerar garantías adicionales como aval o meses extra de fianza."
    if prob < 0.32:
        return "Riesgo Elevado (orientativo)", "#ea580c", \
            "Varias variables del perfil presentan indicadores desfavorables. La índice de riesgo estimado es elevada.", \
            "El perfil muestra fragilidad financiera. Se identifican factores de riesgo relevantes a valorar."
    return "Riesgo Muy Alto (orientativo)", "#dc2626", \
        "El perfil analizado presenta múltiples indicadores de riesgo simultáneos. La índice de riesgo estimado es muy alta.", \
        "El ratio de esfuerzo y/o el historial superan los umbrales críticos establecidos por el modelo."

# ─── MOTOR DE RECOMENDACIONES ────────────────────────────────────────────────
def generar_recomendaciones(prob, factores, nivel_vuln, meses, ocupantes):
    recos = []

    r_ratio    = factores.get("Ratio alquiler/renta", 0)
    r_impagos  = factores.get("Historial impagos", 0)
    r_contrato = factores.get("Contrato laboral", 0)
    r_fuente   = factores.get("Fuente de ingresos", 0)
    r_ccaa     = factores.get("Mora CCAA", 0)

    tiene_menores  = any("Menor" in o for o in ocupantes)
    tiene_mayores  = any("65+" in o for o in ocupantes)
    tiene_vuln     = nivel_vuln not in ("Sin alertas legales relevantes detectadas", "")

    # ── NIVEL BAJO ────────────────────────────────────────────────────────────
    if prob < 0.08:
        recos.append({
            "tipo": "ok",
            "titulo": "Perfil favorable — fianza estándar suficiente",
            "detalle": "1 mes de fianza legal es adecuado para este perfil. No se requieren garantías adicionales.",
            "coste": "Sin coste adicional"
        })
        if not tiene_vuln:
            recos.append({
                "tipo": "opcional",
                "titulo": "Seguro de impago opcional",
                "detalle": "Dado el bajo riesgo, un seguro de impago básico (~€15-25/mes) sería suficiente cobertura si buscas tranquilidad total.",
                "coste": "~€180-300/año"
            })

    # ── NIVEL MODERADO ────────────────────────────────────────────────────────
    elif prob < 0.18:
        if r_contrato >= 0.12:
            recos.append({
                "tipo": "alerta",
                "titulo": "Contrato temporal — solicitar aval bancario",
                "detalle": "El tipo de contrato es el factor de riesgo principal. Un aval bancario equivalente a 2-3 meses de alquiler cubre el riesgo de pérdida de empleo.",
                "coste": "Coste para el inquilino, no para ti"
            })
        if r_ratio >= 0.12:
            recos.append({
                "tipo": "alerta",
                "titulo": "Ratio de esfuerzo elevado — pedir 3 nóminas recientes",
                "detalle": "Solicita las últimas 3 nóminas para verificar estabilidad de ingresos. Si hay variabilidad, pide 2 meses de fianza adicional.",
                "coste": "Sin coste adicional"
            })
        recos.append({
            "tipo": "recomendado",
            "titulo": "Seguro de impago recomendado",
            "detalle": "Para este nivel de riesgo, un seguro de impago de alquiler cubre cuotas impagadas (habitualmente hasta 12 meses) y gastos de desahucio. Coste típico: 3-4% de la renta anual.",
            "coste": "~€270-360/año para alquiler de €750/mes"
        })

    # ── NIVEL ELEVADO ─────────────────────────────────────────────────────────
    elif prob < 0.32:
        recos.append({
            "tipo": "urgente",
            "titulo": "Seguro de impago obligatorio antes de firmar",
            "detalle": "Este perfil requiere cobertura. Mapfre Alquiler Seguro, AXA o Mutua ofrecen pólizas desde ~4% de la renta anual que cubren impago + defensa jurídica + desahucio.",
            "coste": "~€360-480/año para alquiler de €750/mes"
        })
        if r_impagos >= 0.25:
            recos.append({
                "tipo": "urgente",
                "titulo": "Historial de impagos — consultar ficheros de morosos",
                "detalle": "Verifica en ASNEF, RAI o BADEXCUG antes de firmar. El coste de consulta es de €5-15. Si aparece en ficheros, reconsidera el arrendamiento.",
                "coste": "€5-15 consulta"
            })
        if r_fuente >= 0.28:
            recos.append({
                "tipo": "urgente",
                "titulo": "Ingresos por prestación — exigir fiador solidario",
                "detalle": "Los ingresos por desempleo son temporales por definición. Un fiador solidario (persona con nómina estable que responde ante impago) es la garantía más efectiva.",
                "coste": "Sin coste adicional"
            })
        if r_ratio >= 0.22:
            recos.append({
                "tipo": "alerta",
                "titulo": "Ratio crítico — negociar reducción de renta o rechazar",
                "detalle": "El esfuerzo financiero supera los umbrales del Banco de España. Considera negociar una renta más baja, o rechazar si el ratio supera el 50%.",
                "coste": "Sin coste adicional"
            })

    # ── NIVEL MUY ALTO ────────────────────────────────────────────────────────
    else:
        recos.append({
            "tipo": "urgente",
            "titulo": "Riesgo muy alto — valorar no arrendar",
            "detalle": "El perfil acumula múltiples factores de riesgo simultáneos. La índice de riesgo estimado justifica reconsiderar el arrendamiento o exigir garantías muy sólidas.",
            "coste": "—"
        })
        recos.append({
            "tipo": "urgente",
            "titulo": "Si decides arrendar — paquete completo de garantías",
            "detalle": "Mínimo: seguro de impago + fiador solidario con nómina + 2 meses de depósito adicional + cláusula de domiciliación bancaria obligatoria.",
            "coste": "Seguro ~€480-600/año + depósito adicional"
        })
        if r_impagos >= 0.35:
            recos.append({
                "tipo": "urgente",
                "titulo": "Impagos previos — consulta voluntaria de ficheros de morosidad",
                "detalle": "Con impagos declarados, puede consultarse voluntariamente en ficheros públicos de morosidad antes de firmar. Si figura en ellos con deuda activa activo, no arrendar.",
                "coste": "€5-15 consulta"
            })

    # ── VULNERABILIDAD LEGAL (independiente del score) ────────────────────────
    if tiene_vuln and meses > 8:
        recos.append({
            "tipo": "legal",
            "titulo": f"Protección legal — proceso estimado {meses} meses",
            "detalle": f"La presencia de ocupantes vulnerables (menores o mayores) puede extender el proceso de desahucio hasta {meses} meses. Un seguro con cobertura jurídica incluida es especialmente recomendable.",
            "coste": "Incluido en la mayoría de seguros de impago"
        })
    if tiene_menores:
        recos.append({
            "tipo": "legal",
            "titulo": "Menores en el hogar — incluir cláusula de mediación",
            "detalle": "Incluye en el contrato una cláusula de mediación previa obligatoria antes de cualquier acción judicial. Esto protege tus intereses y cumple con la normativa de vulnerabilidad.",
            "coste": "Sin coste — redacción en contrato"
        })

    # ── SIEMPRE RECOMENDADO ───────────────────────────────────────────────────
    recos.append({
        "tipo": "siempre",
        "titulo": "Domiciliar el pago en contrato",
        "detalle": "Incluye en el contrato la obligatoriedad de pago por domiciliación bancaria. Reduce fricciones y acelera la detección temprana de impago.",
        "coste": "Sin coste adicional"
    })

    return recos

# ─── GRÁFICO ARAÑA (SVG puro) ─────────────────────────────────────────────────
# ─── DATOS JUDICIALES Y OKUPACIÓN POR CCAA ────────────────────────────────────
# Fuente: CGPJ Informe Anual 2024
DATOS_JUDICIALES = {
    "Andalucía":           {"lanzamientos_lau": 4027, "ocupaciones": 310, "meses_proceso": 10, "pct_total": 14.6},
    "Aragón":              {"lanzamientos_lau": 420,  "ocupaciones": 45,  "meses_proceso": 8,  "pct_total": 1.5},
    "Asturias":            {"lanzamientos_lau": 280,  "ocupaciones": 30,  "meses_proceso": 9,  "pct_total": 1.0},
    "Baleares":            {"lanzamientos_lau": 510,  "ocupaciones": 55,  "meses_proceso": 9,  "pct_total": 1.9},
    "Canarias":            {"lanzamientos_lau": 890,  "ocupaciones": 95,  "meses_proceso": 11, "pct_total": 3.2},
    "Cantabria":           {"lanzamientos_lau": 180,  "ocupaciones": 20,  "meses_proceso": 8,  "pct_total": 0.7},
    "Castilla-La Mancha":  {"lanzamientos_lau": 620,  "ocupaciones": 60,  "meses_proceso": 9,  "pct_total": 2.3},
    "Castilla y León":     {"lanzamientos_lau": 580,  "ocupaciones": 50,  "meses_proceso": 9,  "pct_total": 2.1},
    "Cataluña":            {"lanzamientos_lau": 7381, "ocupaciones": 463, "meses_proceso": 14, "pct_total": 26.8},
    "Ceuta/Melilla":       {"lanzamientos_lau": 85,   "ocupaciones": 12,  "meses_proceso": 10, "pct_total": 0.3},
    "Comunitat Valenciana":{"lanzamientos_lau": 3610, "ocupaciones": 280, "meses_proceso": 11, "pct_total": 13.1},
    "Extremadura":         {"lanzamientos_lau": 310,  "ocupaciones": 28,  "meses_proceso": 9,  "pct_total": 1.1},
    "Galicia":             {"lanzamientos_lau": 520,  "ocupaciones": 45,  "meses_proceso": 9,  "pct_total": 1.9},
    "La Rioja":            {"lanzamientos_lau": 120,  "ocupaciones": 12,  "meses_proceso": 7,  "pct_total": 0.4},
    "Madrid":              {"lanzamientos_lau": 2375, "ocupaciones": 195, "meses_proceso": 12, "pct_total": 8.6},
    "Murcia":              {"lanzamientos_lau": 980,  "ocupaciones": 88,  "meses_proceso": 10, "pct_total": 3.6},
    "Navarra":             {"lanzamientos_lau": 195,  "ocupaciones": 18,  "meses_proceso": 8,  "pct_total": 0.7},
    "País Vasco":          {"lanzamientos_lau": 380,  "ocupaciones": 35,  "meses_proceso": 9,  "pct_total": 1.4},
    "No especificada":     {"lanzamientos_lau": 0,    "ocupaciones": 0,   "meses_proceso": 9,  "pct_total": 0},
}

# ─── RECURSOS POR CCAA ────────────────────────────────────────────────────────
RECURSOS_CCAA = {
    "Andalucía": [
        ("Agencia de Vivienda y Rehabilitación de Andalucía (AVRA)", "avra.es", "Gestión vivienda pública y mediación"),
        ("Oficinas Municipales de Información al Consumidor (OMIC)", "juntadeandalucia.es/consumo", "Asesoría gratuita en conflictos de alquiler"),
    ],
    "Aragón": [
        ("Instituto Aragonés de Consumo", "aragon.es/consumo", "Mediación y arbitraje en conflictos de alquiler"),
    ],
    "Asturias": [
        ("Sociedad Regional de Vivienda y Suelo (VIPASA)", "vipasa.es", "Mediación y vivienda pública"),
        ("Consejería de Vivienda y Bienestar Social", "asturias.es/vivienda", "Programas de ayuda al alquiler"),
    ],
    "Baleares": [
        ("Institut Balear de l'Habitatge (IBAVI)", "habitatgeilles.es", "Mediación y alquiler asequible"),
        ("Direcció General de Consum", "caib.es/consum", "Arbitraje y asesoría al consumidor"),
    ],
    "Canarias": [
        ("Instituto Canario de la Vivienda", "gobiernodecanarias.org/icv", "Mediación y parque público de alquiler"),
        ("Dirección General de Consumo de Canarias", "gobiernodecanarias.org/consumo", "Arbitraje y mediación en conflictos"),
    ],
    "Cantabria": [
        ("Dirección General de Urbanismo y Vivienda de Cantabria", "cantabria.es/vivienda", "Ayudas y mediación"),
        ("OMIC Cantabria", "cantabria.es/consumo", "Asesoría en conflictos de alquiler"),
    ],
    "Castilla-La Mancha": [
        ("Dirección General de Vivienda y Suelo", "castillalamancha.es/vivienda", "Programas de alquiler y mediación"),
    ],
    "Castilla y León": [
        ("Agencia de Vivienda de Castilla y León", "jcyl.es/vivienda", "Ayudas y mediación en arrendamiento"),
    ],
    "Cataluña": [
        ("Agència de l'Habitatge de Catalunya", "habitatge.gencat.cat", "Oficinas de mediación y ayudas al alquiler"),
        ("Sindicat de Llogateres", "sindicatdellogateres.org", "Defensa de derechos de inquilinos"),
    ],
    "Ceuta/Melilla": [
        ("OCU — Organización de Consumidores y Usuarios", "ocu.org", "Asesoría legal en alquiler"),
    ],
    "Comunitat Valenciana": [
        ("Entitat Valenciana d'Habitatge i Sòl (EVha)", "habitatge.gva.es", "Mediación y vivienda asequible"),
        ("FACUA Comunitat Valenciana", "facua.org/cv", "Denuncias y asesoría consumidores"),
    ],
    "Extremadura": [
        ("Junta Arbitral de Consumo de Extremadura", "gobex.es/consumo", "Arbitraje gratuito en conflictos"),
    ],
    "Galicia": [
        ("Instituto Galego da Vivenda e Solo (IGVS)", "igvs.xunta.gal", "Mediación y ayudas al alquiler"),
    ],
    "La Rioja": [
        ("Dirección General de Urbanismo y Vivienda", "larioja.org/vivienda", "Ayudas y mediación en alquiler"),
    ],
    "Madrid": [
        ("Agencia de Vivienda Social de Madrid", "avs.madrid.es", "Ayudas, mediación y vivienda pública"),
        ("OFECUM — Oficina de Conciliación", "madrid.es/ofecum", "Mediación previa obligatoria (Ley 1/2025)"),
        ("Sindicato de Inquilinas de Madrid", "sindicatodeinquilinas.org", "Orientación legal a inquilinos"),
    ],
    "Murcia": [
        ("Instituto de Vivienda y Suelo de Murcia (IVSU)", "ivsu.es", "Vivienda pública y mediación"),
        ("Dirección General de Consumo — Región de Murcia", "consumo.carm.es", "Asesoría y arbitraje de consumo"),
    ],
    "Navarra": [
        ("Nasuvinsa — Navarra de Suelo y Vivienda", "nasuvinsa.es", "Vivienda pública y alquiler asequible"),
    ],
    "País Vasco": [
        ("Alokabide", "alokabide.net", "Gestión vivienda pública en alquiler"),
        ("KONTSUMOBIDE", "euskadi.eus/kontsumobide", "Servicio vasco del consumidor"),
    ],
    "No especificada": [
        ("Ministerio de Vivienda y Agenda Urbana", "vivienda.gob.es", "Recursos nacionales y ayudas al alquiler"),
        ("OCU — Organización de Consumidores", "ocu.org", "Asesoría legal gratuita en alquiler"),
    ],
}

RECURSOS_COMUNES = [
    ("Ministerio de Vivienda y Agenda Urbana", "vivienda.gob.es", "Portal nacional con ayudas y legislación"),
    ("Consejo General del Poder Judicial (CGPJ)", "cgpj.es", "Estadísticas de desahucios y juzgados"),
    ("Ley 12/2023 de Vivienda — BOE", "boe.es", "Ley por el Derecho a la Vivienda"),
    ("Ley Orgánica 1/2025 — Mediación obligatoria", "boe.es", "Mediación previa obligatoria desde abril 2025"),
]

def generar_pdf(datos_inquilino, prob, factores, label, conclusion,
                detalle, recos=None, alertas_vuln=None, nivel_vuln="", meses=8):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=18*mm, leftMargin=18*mm,
        topMargin=18*mm, bottomMargin=18*mm)

    # Colores
    COLOR_ACENTO = colors.HexColor("#00C896")
    COLOR_DARK   = colors.HexColor("#0f172a")
    COLOR_TEXTO  = colors.HexColor("#1e293b")
    COLOR_GRIS   = colors.HexColor("#64748b")
    COLOR_LIGHT  = colors.HexColor("#f8fafc")

    prob_pct = round(prob * 100)
    if prob < 0.08:   sh, sl = "#16a34a", "#f0fdf4"
    elif prob < 0.18: sh, sl = "#d97706", "#fffbeb"
    elif prob < 0.32: sh, sl = "#ea580c", "#fff7ed"
    else:             sh, sl = "#dc2626", "#fef2f2"
    COLOR_SEM = colors.HexColor(sh)

    estilos = getSampleStyleSheet()
    def sty(name, **kw):
        return ParagraphStyle(name, parent=estilos["Normal"], **kw)

    t_s  = sty("t",  fontSize=18, textColor=COLOR_DARK,  spaceAfter=6,  fontName="Helvetica-Bold", leading=22)
    su_s = sty("su", fontSize=9,  textColor=COLOR_GRIS,  spaceAfter=3,  fontName="Helvetica", leading=12)
    se_s = sty("se", fontSize=8,  textColor=COLOR_ACENTO,spaceAfter=6,  fontName="Helvetica-Bold")
    b_s  = sty("b",  fontSize=9,  textColor=COLOR_TEXTO, spaceAfter=4,  fontName="Helvetica", leading=13)
    d_s  = sty("d",  fontSize=7,  textColor=COLOR_GRIS,  spaceAfter=4,  fontName="Helvetica", leading=10)
    reco_t_s = sty("rt", fontSize=9, textColor=COLOR_DARK, spaceAfter=2, fontName="Helvetica-Bold")
    reco_d_s = sty("rd", fontSize=8, textColor=COLOR_GRIS, spaceAfter=3, fontName="Helvetica", leading=11)

    story = []

    # ── PORTADA ───────────────────────────────────────────────────────────────
    story.append(Paragraph("Predice_Impago", t_s))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Informe de Análisis de Riesgo de Inquilino", su_s))
    story.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y a las %H:%M')}", su_s))
    story.append(HRFlowable(width="100%", thickness=2, color=COLOR_ACENTO, spaceAfter=12))

    # Score grande
    portada_data = [[
        Paragraph(f"<font size=40 color='{sh}'><b>{prob_pct}%</b></font>", estilos["Normal"]),
        [Paragraph(f"<font size=14 color='{sh}'><b>{label}</b></font>", estilos["Normal"]),
         Spacer(1,4),
         Paragraph(conclusion, b_s),
         Spacer(1,6),
         Paragraph(f"<b>Detalle:</b> {detalle}", b_s)]
    ]]
    pt = Table(portada_data, colWidths=[45*mm, 125*mm])
    pt.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor(sl)),
        ("TOPPADDING",(0,0),(-1,-1),14),("BOTTOMPADDING",(0,0),(-1,-1),14),
        ("LEFTPADDING",(0,0),(-1,-1),12),("RIGHTPADDING",(0,0),(-1,-1),12),
    ]))
    story.append(pt)
    story.append(Spacer(1,10))

    # ── DATOS DEL INQUILINO ───────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))
    story.append(Paragraph("DATOS ANALIZADOS", se_s))
    filas = [["Variable","Valor"],
        ["Ingresos netos totales", f"{datos_inquilino.get('nomina',0):,} euros/mes"],
        ["Perceptores de ingresos", f"{datos_inquilino.get('n_perceptores',1)} persona(s): {datos_inquilino.get('ingresos_detalle','—')}"],
        ["Alquiler mensual", f"{datos_inquilino.get('alquiler',0):,} euros/mes"],
        ["Ratio esfuerzo", f"{round(datos_inquilino.get('alquiler',0)/max(datos_inquilino.get('nomina',1),1)*100)}%"],
        ["Franja de edad titular", datos_inquilino.get("edad","—")],
        ["Tipo de contrato", datos_inquilino.get("contrato","—")],
        ["Antiguedad laboral", datos_inquilino.get("antiguedad","—")],
        ["Fuente de ingresos", datos_inquilino.get("fuente","—")],
        ["Sector laboral", datos_inquilino.get("sector_display","—")],
        ["Comunidad autonoma", datos_inquilino.get("ccaa","—")],
        ["Impagos anteriores", datos_inquilino.get("impagos","—")],
        ["Historial bancario", datos_inquilino.get("nacionalidad","—")],
        ["Ocupantes", datos_inquilino.get("ocupantes","—")],
    ]
    t = Table(filas, colWidths=[72*mm, 98*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),COLOR_DARK),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f8fafc")]),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#e2e8f0")),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),7),
    ]))
    story.append(t)
    story.append(Spacer(1,8))

    # ── VULNERABILIDAD LEGAL ──────────────────────────────────────────────────
    if alertas_vuln or (nivel_vuln and nivel_vuln != "Sin alertas legales relevantes detectadas"):
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))
        story.append(Paragraph("PROTECCIÓN LEGAL ESTIMADA", se_s))
        vuln_data = [[
            Paragraph(f"<font size=20 color='#d97706'><b>{meses}</b></font><br/><font size=7 color='#94a3b8'>meses estimados</font>", estilos["Normal"]),
            [Paragraph(f"<b>{nivel_vuln}</b>", reco_t_s)] +
            [Paragraph(f"• {a.replace('⚠️ ','')}", reco_d_s) for a in (alertas_vuln or [])] +
            [Paragraph("Basado en Ley 12/2023 de Vivienda y decretos autonómicos.", d_s)]
        ]]
        vt = Table(vuln_data, colWidths=[30*mm, 140*mm])
        vt.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#fffbeb")),
            ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
            ("LEFTPADDING",(0,0),(-1,-1),10),
        ]))
        story.append(vt)
        story.append(Spacer(1,8))

    # ── FACTORES VS MEDIA ─────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))
    story.append(Paragraph("FACTORES DE RIESGO VS PERFIL MEDIO ESPAÑA", se_s))
    PERFIL_MEDIO_PDF = {
        "Ratio alquiler/renta":0.12,"Historial impagos":0.00,"Contrato laboral":0.08,
        "Antigüedad laboral":0.06,"Fuente de ingresos":0.06,"Mora CCAA":0.13,
        "Sector laboral":0.10,"Franja de edad":0.09,
    }
    ff = [["Factor","Inquilino","Media","Diferencia"]]
    for nombre, val in factores.items():
        med = PERFIL_MEDIO_PDF.get(nombre, 0.10)
        diff = int(val*100) - int(med*100)
        signo = f"+{diff}pp" if diff > 0 else f"{diff}pp"
        ff.append([nombre, f"{int(val*100)}%", f"{int(med*100)}%", signo])
    ft = Table(ff, colWidths=[82*mm, 25*mm, 25*mm, 28*mm+10])
    ft.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),COLOR_DARK),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f8fafc")]),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#e2e8f0")),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),7),
    ]))
    story.append(ft)
    story.append(Spacer(1,8))

    # ── GRÁFICO BARRAS COMPARATIVO ───────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))
    story.append(Paragraph("ANÁLISIS COMPARATIVO: INQUILINO VS PERFIL MEDIO ESPAÑA", se_s))
    _PM = {"Ratio alquiler/renta":0.12,"Historial impagos":0.00,"Contrato laboral":0.08,
           "Antigüedad laboral":0.06,"Fuente de ingresos":0.06,"Mora CCAA":0.13,
           "Sector laboral":0.10,"Franja de edad":0.09}
    _MC = 20
    _cw = (170*mm - 45*mm - 12*mm) / _MC
    def _bc(val, inq, mv=0.60):
        f = round(min(val/mv,1.0)*_MC)
        if inq:
            fc = (colors.HexColor("#16a34a") if val<0.08 else colors.HexColor("#d97706") if val<0.18 else colors.HexColor("#ea580c") if val<0.32 else colors.HexColor("#dc2626"))
            ec = colors.HexColor("#f1f5f9")
        else:
            fc = colors.HexColor("#94a3b8"); ec = colors.HexColor("#f8fafc")
        return [fc if i<f else ec for i in range(_MC)]
    _cws = [45*mm]+[_cw]*_MC+[12*mm]
    _hdr = [Paragraph("<b>Factor</b>", sty("_h", fontSize=7, fontName="Helvetica-Bold", textColor=colors.white))]+[Paragraph("",estilos["Normal"])]*_MC+[Paragraph("<b>%</b>", sty("_p", fontSize=7, fontName="Helvetica-Bold", textColor=colors.white))]
    _td=[_hdr]
    _sc=[("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0f172a")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTSIZE",(0,0),(-1,-1),7),("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2),("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),1),("VALIGN",(0,0),(-1,-1),"MIDDLE")]
    _ri=1
    for _n,_v in factores.items():
        _m=_PM.get(_n,0.10)
        _td.append([Paragraph(f"<font size='7'>{_n[:22]}</font>",estilos["Normal"])]+[Paragraph("",estilos["Normal"])]*_MC+[Paragraph(f"<font size='7'><b>{int(_v*100)}%</b></font>",estilos["Normal"])])
        for _ci,_bg in enumerate(_bc(_v,True)): _sc.append(("BACKGROUND",(_ci+1,_ri),(_ci+1,_ri),_bg))
        _sc.append(("BACKGROUND",(0,_ri),(0,_ri),colors.HexColor("#f8fafc"))); _ri+=1
        _td.append([Paragraph("",estilos["Normal"])]+[Paragraph("",estilos["Normal"])]*_MC+[Paragraph(f"<font size='6' color='#94a3b8'>m {int(_m*100)}%</font>",estilos["Normal"])])
        for _ci,_bg in enumerate(_bc(_m,False)): _sc.append(("BACKGROUND",(_ci+1,_ri),(_ci+1,_ri),_bg))
        _sc.append(("LINEBELOW",(0,_ri),(-1,_ri),0.4,colors.HexColor("#e2e8f0"))); _ri+=1
    _ct=Table(_td,colWidths=_cws); _ct.setStyle(TableStyle(_sc))
    story.append(_ct)
    story.append(Paragraph("<font size='7' color='#16a34a'>&#9632; Bajo</font>  <font size='7' color='#d97706'>&#9632; Moderado</font>  <font size='7' color='#ea580c'>&#9632; Elevado</font>  <font size='7' color='#dc2626'>&#9632; Muy alto</font>  <font size='7' color='#94a3b8'>&#9632; Media</font>", estilos["Normal"]))
    story.append(Spacer(1,8))

    # ── RECOMENDACIONES ───────────────────────────────────────────────────────
    if recos:
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))
        story.append(Paragraph("RECOMENDACIONES PARA EL PROPIETARIO", se_s))
        TIPO_COLOR = {
            "ok":"#16a34a","opcional":"#0ea5e9","alerta":"#d97706",
            "recomendado":"#7c3aed","urgente":"#dc2626","legal":"#0f172a","siempre":"#475569"
        }
        TIPO_ICONO = {
            "ok":"✓","opcional":"◎","alerta":"⚠","recomendado":"★",
            "urgente":"!","legal":"⚖","siempre":"→"
        }
        for reco in recos:
            col_hex = TIPO_COLOR.get(reco["tipo"], "#475569")
            icono = TIPO_ICONO.get(reco["tipo"], "→")
            reco_row = [[
                Paragraph(f"<font color='{col_hex}'><b>{icono} {reco['titulo']}</b></font>", reco_t_s),
                Paragraph(f"<font color='#64748b'>{reco['coste']}</font>", reco_d_s)
            ],[
                Paragraph(reco["detalle"], reco_d_s), ""
            ]]
            rt = Table(reco_row, colWidths=[130*mm, 40*mm])
            rt.setStyle(TableStyle([
                ("VALIGN",(0,0),(-1,-1),"TOP"),
                ("SPAN",(0,1),(1,1)),
                ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#f8fafc")),
                ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
                ("LEFTPADDING",(0,0),(-1,-1),8),
                ("LINEBELOW",(0,-1),(-1,-1),0.3,colors.HexColor("#e2e8f0")),
            ]))
            story.append(rt)
        story.append(Spacer(1,8))

    # ── DISCLAIMER ────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=6))
    story.append(Paragraph(
        "AVISO LEGAL: Herramienta orientativa. No constituye asesoramiento legal, financiero ni inmobiliario. "
        "Datos estadísticos de referencia: INE, Banco de España, Alquiler Seguro, SEPE. "
        "prediceimpago.streamlit.app", d_s))

    # ── CALCULADORA COSTE REAL ───────────────────────────────────────────────
    meses_calc = meses if meses else 8
    coste_rentas = datos_inquilino.get("alquiler",0) * meses_calc
    coste_jud    = 2800 if prob < 0.32 else 4200
    coste_seg    = round(datos_inquilino.get("alquiler",0) * 12 * 0.035)
    coste_total  = coste_rentas + coste_jud

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))
    story.append(Paragraph("CALCULADORA DE COSTE REAL DEL IMPAGO", se_s))
    calc_data = [
        ["Concepto", "Importe estimado"],
        [f"Rentas sin cobrar ({meses_calc} meses proceso)", f"€{coste_rentas:,}"],
        ["Costes judiciales estimados", f"€{coste_jud:,}"],
        ["COSTE TOTAL SIN SEGURO", f"€{coste_total:,}"],
        ["Seguro de impago anual (~3.5% renta)", f"€{coste_seg:,}/año"],
        [f"Ahorro potencial con seguro", f"€{max(0, coste_total-coste_seg):,}"],
    ]
    ct = Table(calc_data, colWidths=[120*mm, 50*mm])
    ct.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0f172a")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),9),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f8fafc")]),
        ("BACKGROUND",(0,3),(-1,3),colors.HexColor("#fef2f2")),
        ("TEXTCOLOR",(0,3),(-1,3),colors.HexColor("#dc2626")),
        ("FONTNAME",(0,3),(-1,3),"Helvetica-Bold"),
        ("BACKGROUND",(0,5),(-1,5),colors.HexColor("#f0fdf9")),
        ("TEXTCOLOR",(0,5),(-1,5),colors.HexColor("#16a34a")),
        ("FONTNAME",(0,5),(-1,5),"Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#e2e8f0")),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING",(0,0),(-1,-1),8),
    ]))
    story.append(ct)
    story.append(Spacer(1,4))

    # ── SEMÁFORO DE CONTRATO ──────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=6))
    _cl_title = Paragraph("CLÁUSULAS RECOMENDADAS PARA EL CONTRATO", se_s)
    cl_data = [["Cláusula", "Prioridad", "Descripción"]]
    clausulas_pdf = [
        ("Domiciliación bancaria obligatoria", "Siempre", "Pago por domiciliación — facilita detección temprana de impago"),
        ("Fianza legal (1 mes)", "Siempre", "Obligatoria por ley. Depositar en organismo autonómico"),
        ("Inventario detallado", "Siempre", "Fotografías fechadas y firmadas del estado del inmueble"),
        ("Actualización anual IPC", "Siempre", "Cláusula de actualización referenciada al IPC oficial"),
        ("Mediación previa obligatoria", "Obligatorio desde 04/2025", "Ley 1/2025: mediación previa antes de cualquier desahucio"),
        ("2 meses garantía adicional", "Riesgo moderado+" , "Máximo legal: 2 meses adicionales sobre la fianza"),
        ("Aval bancario o fiador", "Riesgo elevado+", "Persona con nómina estable que responde solidariamente"),
        ("Seguro de impago contratado", "Riesgo elevado+", "Propietario contrata antes de firmar — cubre impago + desahucio"),
        ("Consulta voluntaria de ficheros de morosos", "Riesgo muy alto", "Verificar ficheros de morosos antes de firmar (€5-15)"),
    ]
    for cl, pri, desc in clausulas_pdf:
        if "muy alto" in pri.lower():    pc = colors.HexColor("#dc2626")
        elif "elevado" in pri.lower():   pc = colors.HexColor("#ea580c")
        elif "moderado" in pri.lower():  pc = colors.HexColor("#d97706")
        elif "obligatorio" in pri.lower(): pc = colors.HexColor("#7c3aed")
        else:                             pc = colors.HexColor("#16a34a")
        cl_data.append([cl, Paragraph(f"<font color='{pc.hexval() if hasattr(pc,"hexval") else str(pc)}'>{pri}</font>", estilos["Normal"]), desc])

    # Simpler approach for colors
    cl_data2 = [["Cláusula", "Prioridad", "Descripción"]]
    for cl, pri, desc in clausulas_pdf:
        cl_data2.append([cl, pri, desc])

    clt = Table(cl_data2, colWidths=[60*mm, 38*mm, 72*mm])
    clt.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0f172a")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f8fafc")]),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#e2e8f0")),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),("VALIGN",(0,0),(-1,-1),"TOP"),
    ]))
    story.append(KeepTogether([_cl_title, clt]))
    story.append(Spacer(1,6))

    # ── DATOS JUDICIALES Y OKUPACIÓN ─────────────────────────────────────────
    ccaa_key = datos_inquilino.get("ccaa","No especificada")
    jud = DATOS_JUDICIALES.get(ccaa_key, DATOS_JUDICIALES["No especificada"])

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))
    story.append(Paragraph(f"CONTEXTO JUDICIAL Y OKUPACIÓN — {ccaa_key.upper()}", se_s))
    story.append(Paragraph(
        "Datos reales de 2024 para tu comunidad autónoma. Fuente: CGPJ Informe Anual 2024.",
        b_s))
    story.append(Spacer(1,4))

    jud_data = [
        ["Indicador", "Tu CCAA", "España total", "Contexto"],
        ["Desahucios por impago alquiler (2024)",
         f"{jud['lanzamientos_lau']:,}",
         "20.558",
         f"{jud['pct_total']}% del total nacional"],
        ["Juicios por okupación ilegal (2024)",
         f"{jud['ocupaciones']:,}",
         "2.309",
         "Juicios verbales posesorios CGPJ"],
        ["Duración media del proceso",
         f"{jud['meses_proceso']} meses",
         "9 meses",
         "Desde demanda hasta lanzamiento"],
        ["Incremento desahucios vs 2023",
         "+4.5%",
         "+3.4%",
         "Tendencia creciente en toda España"],
    ]

    jt = Table(jud_data, colWidths=[58*mm, 28*mm, 28*mm, 56*mm])
    jt.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0f172a")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f8fafc")]),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#e2e8f0")),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING",(0,0),(-1,-1),6),("VALIGN",(0,0),(-1,-1),"TOP"),
        # Highlight CCAA column
        ("BACKGROUND",(1,1),(1,-1),colors.HexColor("#fff7ed")),
        ("TEXTCOLOR",(1,1),(1,-1),colors.HexColor("#ea580c")),
        ("FONTNAME",(1,1),(1,-1),"Helvetica-Bold"),
    ]))
    story.append(jt)

    # Nota de contexto
    if jud["lanzamientos_lau"] > 2000:
        nota_jud = f"⚠ {ccaa_key} es una de las comunidades con mayor volumen de desahucios por alquiler en España. El proceso judicial puede ser más lento por saturación de juzgados."
    elif jud["lanzamientos_lau"] > 500:
        nota_jud = f"{ccaa_key} presenta un volumen de desahucios medio. Los plazos judiciales estimados son estándar a nivel nacional."
    else:
        nota_jud = f"{ccaa_key} presenta un volumen de desahucios bajo. Los procesos judiciales tienden a resolverse con mayor rapidez."

    story.append(Paragraph(nota_jud, sty("nj", fontSize=8, textColor=colors.HexColor("#64748b"),
                           leading=11, spaceAfter=6, backColor=colors.HexColor("#f8fafc"),
                           borderPadding=5)))
    story.append(Spacer(1,8))

    # ── RECURSOS POR CCAA ─────────────────────────────────────────────────────
    ccaa_doc = datos_inquilino.get("ccaa", "No especificada")
    recursos_ccaa = RECURSOS_CCAA.get(ccaa_doc, RECURSOS_CCAA["No especificada"])

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))
    story.append(Paragraph(f"RECURSOS Y ORGANISMOS ÚTILES — {ccaa_doc.upper()}", se_s))
    story.append(Paragraph(
        "Servicios e instituciones a los que puedes acudir en caso de conflicto de alquiler en tu zona.",
        b_s))
    story.append(Spacer(1,4))

    rec_data = [["Organismo", "Web", "Para qué sirve"]]
    for nombre, web, desc in recursos_ccaa:
        rec_data.append([nombre, web, desc])

    rec_t = Table(rec_data, colWidths=[55*mm, 45*mm, 70*mm])
    rec_t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0f172a")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),7),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f8fafc")]),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#e2e8f0")),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),("VALIGN",(0,0),(-1,-1),"TOP"),
    ]))
    story.append(rec_t)
    story.append(Spacer(1,8))

    # Recursos comunes nacionales
    story.append(Paragraph("RECURSOS NACIONALES", se_s))
    com_data = [["Organismo / Norma", "Web", "Referencia"]]
    for nombre, web, desc in RECURSOS_COMUNES:
        com_data.append([nombre, web, desc])
    com_t = Table(com_data, colWidths=[55*mm, 45*mm, 70*mm])
    com_t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0f172a")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),7),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f8fafc")]),
        ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#e2e8f0")),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),("VALIGN",(0,0),(-1,-1),"TOP"),
    ]))
    story.append(com_t)
    story.append(Spacer(1,8))

    # Nota mediación obligatoria
    story.append(Paragraph(
        "⚖ IMPORTANTE — Desde el 3 de abril de 2025 (Ley Orgánica 1/2025) es obligatorio "
        "intentar mediación o conciliación antes de iniciar cualquier proceso judicial de desahucio. "
        "Contacta con la oficina de mediación de tu CCAA antes de acudir al juzgado.",
        sty("nota", fontSize=8, textColor=colors.HexColor("#92400e"),
            backColor=colors.HexColor("#fffbeb"), leading=11,
            borderPadding=6, spaceAfter=6)))
    story.append(Spacer(1,6))

    doc.build(story)
    buffer.seek(0)
    return buffer


# ─── PERSISTENCIA ──────────────────────────────────────────────────────────────
def enviar_formspree(email, datos):
    try:
        r = requests.post(FORMSPREE_URL, json={"email": email, "_subject": "Nuevo lead Predice_Impago", **datos}, timeout=5)
        return r.status_code == 200
    except:
        return False

# ─── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;}
.stApp{background-color:#FFFFFF;color:#1e293b;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding-top:2rem;padding-bottom:2rem;max-width:640px;}
h1,h2,h3{font-family:'DM Serif Display',serif!important;color:#0f172a!important;}
.stSelectbox>div>div,.stNumberInput>div>div>input{background-color:#F8FAFC!important;border:1px solid #E2E8F0!important;color:#1e293b!important;border-radius:8px!important;}
.stSelectbox label,.stNumberInput label,.stTextInput label{color:#64748b!important;font-size:0.78rem!important;font-weight:600!important;letter-spacing:0.08em!important;text-transform:uppercase!important;}
.stButton>button{background:#00C896!important;color:#0f172a!important;border:none!important;border-radius:8px!important;font-weight:600!important;font-family:'DM Sans',sans-serif!important;font-size:1rem!important;padding:0.6rem 2rem!important;width:100%;box-shadow:0 2px 8px rgba(0,200,150,0.25)!important;}
.stButton>button:hover{background:#00b386!important;}
.stTextInput>div>div>input{background-color:#F8FAFC!important;border:1px solid #E2E8F0!important;color:#1e293b!important;border-radius:8px!important;}
.stCheckbox label{color:#475569!important;font-size:0.85rem!important;}
.stDownloadButton>button{background:#f0fdf9!important;color:#00C896!important;border:1px solid #00C89640!important;border-radius:8px!important;font-weight:600!important;width:100%;}
hr{border-color:#E2E8F0!important;}
</style>
""", unsafe_allow_html=True)

# ─── COOKIES ──────────────────────────────────────────────────────────────────
if "cookies_ok" not in st.session_state:
    st.session_state.cookies_ok = False
if "candidatos" not in st.session_state:
    st.session_state.candidatos = []
if "n_analisis" not in st.session_state:
    st.session_state.n_analisis = 0
if "ultimo_analisis" not in st.session_state:
    st.session_state.ultimo_analisis = 0.0
if "captcha_ok" not in st.session_state:
    st.session_state.captcha_ok = False
if "captcha_q" not in st.session_state:
    import random as _random
    _ops = [
        lambda a,b: (f"{a} + {b}", a+b),
        lambda a,b: (f"{a} × {b}", a*b),
        lambda a,b: (f"{a} − {b}", a-b),
    ]
    _op = _random.choice(_ops)
    _a, _b = _random.randint(2,9), _random.randint(2,9)
    _txt, _res = _op(_a, _b)
    if _res < 0:  # avoid negatives for subtraction
        _a, _b = max(_a,_b), min(_a,_b)
        _txt, _res = f"{_a} − {_b}", _a-_b
    st.session_state.captcha_q = _txt
    st.session_state.captcha_r = _res
if not st.session_state.cookies_ok:
    st.markdown("""<div style="background:#F0F9FF;border:1px solid #BAE6FD;border-radius:12px;padding:20px 24px;margin-bottom:24px;">
        <p style="color:#0f172a;font-size:0.9rem;margin:0 0 12px 0;">🍪 <strong>Cookies analíticas</strong> — Datos de uso anónimos para mejorar el modelo. Sin datos personales a terceros.</p>
    </div>""", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("✓ Aceptar"):
            st.session_state.cookies_ok = True; st.rerun()
    with c2:
        if st.button("Solo esenciales"):
            st.session_state.cookies_ok = True; st.rerun()
    st.stop()

# ─── CAPTCHA ──────────────────────────────────────────────────────────────────
if not st.session_state.captcha_ok:
    st.markdown("""
    <div style="max-width:400px;margin:10vh auto;text-align:center;">
        <div style="font-size:3rem;margin-bottom:8px;">🏠</div>
        <div style="font-family:'DM Serif Display',serif;font-size:1.8rem;
                    color:#0f172a;margin-bottom:6px;">Predice_Impago</div>
        <p style="color:#64748b;font-size:0.95rem;margin-bottom:4px;font-weight:300;">
            Herramienta para propietarios responsables.
        </p>
        <p style="color:#94a3b8;font-size:0.82rem;margin-bottom:24px;">
            🤖 Pequeña verificación para alejar a los robots con malas intenciones.<br>
            <em>Los humanos honestos no tienen problema con esto.</em>
        </p>
    </div>
    """, unsafe_allow_html=True)

    col_l, col_c, col_r = st.columns([1,2,1])
    with col_c:
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#f0fdf9 0%,#f8fafc 100%);
                    border:2px solid #00C89640;border-radius:16px;
                    padding:32px 24px;text-align:center;
                    box-shadow:0 4px 20px rgba(0,200,150,0.10);">
            <div style="font-size:1.8rem;margin-bottom:8px;">🧮</div>
            <div style="font-size:0.72rem;letter-spacing:0.12em;text-transform:uppercase;
                        color:#00C896;font-weight:600;margin-bottom:14px;">
                Demuestra que eres humano
            </div>
            <div style="font-family:'DM Serif Display',serif;font-size:3.2rem;
                        color:#0f172a;font-weight:700;margin-bottom:6px;
                        letter-spacing:-1px;">
                {st.session_state.captcha_q}
            </div>
            <div style="font-size:0.78rem;color:#94a3b8;margin-bottom:18px;">
                = ?
            </div>
            <div style="font-size:0.72rem;color:#cbd5e1;margin-top:16px;">
                🔒 Solo te lo preguntamos una vez por sesión
            </div>
        </div>
        """, unsafe_allow_html=True)

        respuesta = st.text_input("Tu respuesta", placeholder="Escribe el resultado...",
                                   key="captcha_input",
                                   label_visibility="collapsed")

        if st.button("Continuar →", key="captcha_btn"):
            try:
                _resp_int = int(respuesta.strip())
            except (ValueError, AttributeError):
                st.error("Escribe un número como respuesta.")
                st.stop()
            if _resp_int == st.session_state.captcha_r:
                st.session_state.captcha_ok = True
                st.rerun()
            else:
                st.error("Respuesta incorrecta — inténtalo de nuevo 🤖")
                # Generate new question on failure
                import random as _random
                _ops = [
                    lambda a,b: (f"{a} + {b}", a+b),
                    lambda a,b: (f"{a} × {b}", a*b),
                    lambda a,b: (f"{a} − {b}", a-b),
                ]
                _op = _random.choice(_ops)
                _a, _b = _random.randint(2,9), _random.randint(2,9)
                _txt, _res = _op(_a, _b)
                if _res < 0:
                    _a, _b = max(_a,_b), min(_a,_b)
                    _txt, _res = f"{_a} − {_b}", _a-_b
                st.session_state.captcha_q = _txt
                st.session_state.captcha_r = _res
                st.rerun()
    st.stop()

# ─── HEADER ───────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;padding:2rem 0 1rem 0;">
    <span style="font-size:11px;font-weight:600;letter-spacing:0.15em;text-transform:uppercase;
                 color:#00C896;border:1px solid #00C89640;padding:5px 14px;border-radius:100px;background:#f0fdf9;">
        Scoring de Inquilinos · Beta Gratuita
    </span>
    <h1 style="font-size:2.4rem;margin:1rem 0 0.5rem 0;line-height:1.15;">
        ¿Tu inquilino dejará<br><em style="color:#00C896;">de pagar?</em>
    </h1>
    <p style="color:#64748b;font-size:1rem;max-width:420px;margin:0 auto 2rem auto;line-height:1.7;font-weight:300;">
        El análisis combina variables económicas, laborales y territoriales
        utilizando estadísticas agregadas públicas y modelos estadísticos orientativos.
        Herramienta de apoyo a la decisión, no vinculante.
    </p>
</div>""", unsafe_allow_html=True)

c1,c2,c3 = st.columns(3)
for col,num,lbl in zip([c1,c2,c3],["9.93%","8 meses","€7.600"],
    ["Paro España Q4 2025","Proceso medio desahucio","Deuda media impago 2023"]):
    col.markdown(f"""<div style="text-align:center;padding:16px;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
        <div style="font-family:'DM Serif Display',serif;font-size:1.5rem;color:#0f172a;font-weight:700;">{num}</div>
        <div style="font-size:0.7rem;color:#94a3b8;margin-top:4px;">{lbl}</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
st.markdown("---")

# ─── FORMULARIO ───────────────────────────────────────────────────────────────
st.markdown("### Datos del inquilino")
st.markdown("<p style='color:#94a3b8;font-size:0.88rem;margin-top:-12px;margin-bottom:20px;'>10 variables · Modelos estadísticos orientativos · Resultado instantáneo</p>", unsafe_allow_html=True)

# Restaurar valores del formulario si hay resultado guardado
_prev = st.session_state.get("resultado", {}).get("datos", {})

col_a,col_b = st.columns(2)
with col_a: alquiler = st.number_input("Alquiler mensual (€)", min_value=0, max_value=10000, value=int(_prev.get("alquiler",750)), step=50, key="w_alquiler")
with col_b: n_perceptores = st.number_input("Número de perceptores de ingresos", min_value=1, max_value=4, value=1, step=1, key="w_nperc")

st.markdown("<div style='font-size:0.78rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;margin-bottom:6px;margin-top:4px;'>Ingresos netos por perceptor (€/mes)</div>", unsafe_allow_html=True)
_perc_cols = st.columns(int(n_perceptores))
_ingresos = []
_labels = ["Titular", "Perceptor 2", "Perceptor 3", "Perceptor 4"]
for _pi in range(int(n_perceptores)):
    with _perc_cols[_pi]:
        _val = st.number_input(_labels[_pi], min_value=0, max_value=15000,
                               value=int(_prev.get("nomina",1800)) if _pi==0 else 0,
                               step=100, key=f"ingreso_{_pi}")
        _ingresos.append(_val)
nomina = sum(_ingresos)

# Mostrar total
if int(n_perceptores) > 1:
    st.markdown(f"""<div style="background:#f0fdf9;border:1px solid #00C89640;border-radius:8px;
                padding:10px 16px;margin:4px 0 12px 0;">
        <span style="font-size:0.8rem;color:#64748b;">Ingresos netos totales: </span>
        <span style="font-size:1rem;font-weight:700;color:#00C896;">€{nomina:,}/mes</span>
        <span style="font-size:0.75rem;color:#94a3b8;margin-left:8px;">
            ({int(n_perceptores)} perceptores)
        </span>
    </div>""", unsafe_allow_html=True)

col_c,col_d = st.columns(2)
with col_c: edad = st.selectbox("Franja de edad del titular", list(PARO_POR_EDAD.keys()), index=2)
with col_d: n_ocupantes = st.number_input("Número de ocupantes", min_value=1, max_value=8, value=1, step=1)

# Ocupantes dinámicos
st.markdown("<div style='font-size:0.78rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;margin-bottom:8px;'>Tipo de cada ocupante</div>", unsafe_allow_html=True)
ocupantes = []
n = int(n_ocupantes)
if n <= 2:
    cols_ocu = st.columns(n)
    for i in range(n):
        with cols_ocu[i]:
            tipo = st.selectbox(f"Ocupante {i+1}", TIPOS_OCUPANTE, key=f"ocu_{i}")
            ocupantes.append(tipo)
else:
    rows = [st.columns(2) for _ in range((n + 1) // 2)]
    for i in range(n):
        with rows[i // 2][i % 2]:
            tipo = st.selectbox(f"Ocupante {i+1}", TIPOS_OCUPANTE, key=f"ocu_{i}")
            ocupantes.append(tipo)

col_e,col_f = st.columns(2)
with col_e: contrato  = st.selectbox("Tipo de contrato",   list(RIESGO_CONTRATO.keys()))
with col_f: antiguedad= st.selectbox("Antigüedad laboral", list(RIESGO_ANTIGUEDAD.keys()), index=2)

fuente = st.selectbox("Fuente principal de ingresos", list(RIESGO_FUENTE.keys()))

sector_labels = {
    "tecnologia":"Tecnología","sanidad":"Sanidad","educacion":"Educación",
    "administracion":"Administración pública","industria":"Industria / manufactura",
    "comercio":"Comercio","transporte":"Transporte / logística",
    "hosteleria":"Hostelería / turismo","construccion":"Construcción","otro":"Otro"
}
col_g,col_h = st.columns(2)
with col_g:
    sector_display = st.selectbox("Sector laboral", list(sector_labels.values()))
    sector = [k for k,v in sector_labels.items() if v == sector_display][0]
with col_h: ccaa = st.selectbox("Comunidad autónoma", list(MORA_POR_CCAA.keys()))

col_i,col_j = st.columns(2)
with col_i: impagos     = st.selectbox("Impagos anteriores",       list(RIESGO_IMPAGOS.keys()))
with col_j: nacionalidad= st.selectbox("Historial bancario España", list(CORR_NAC.keys()))

if nomina > 0:
    ratio_live = round(alquiler/nomina*100)
    cr = "#16a34a" if ratio_live<=30 else "#d97706" if ratio_live<=40 else "#ea580c" if ratio_live<=50 else "#dc2626"
    icono = "✓ óptimo" if ratio_live<=30 else "⚠ límite BdE" if ratio_live<=40 else "✗ excede umbral crítico" if ratio_live>50 else "⚠ tenso"
    st.markdown(f"""<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
                padding:10px 16px;margin:8px 0 16px 0;">
        <span style="font-size:0.8rem;color:#64748b;">Ratio de esfuerzo: </span>
        <span style="font-size:1rem;font-weight:700;color:{cr};">{ratio_live}%</span>
        <span style="font-size:0.75rem;color:#94a3b8;margin-left:8px;">{icono}</span>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ─── CÁLCULO ──────────────────────────────────────────────────────────────────
# ── Rate limiting ────────────────────────────────────────────────────────────
import time as _time
_COOLDOWN_SEG = 10
_MAX_ANALISIS = 20
_ahora = _time.time()
_tiempo_restante = max(0, _COOLDOWN_SEG - (_ahora - st.session_state.ultimo_analisis))
_limite_alcanzado = st.session_state.n_analisis >= _MAX_ANALISIS

if _limite_alcanzado:
    st.markdown("""<div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:8px;
                padding:12px 16px;margin-bottom:12px;">
        <div style="font-size:0.85rem;color:#dc2626;font-weight:600;">
            Límite de sesión alcanzado
        </div>
        <div style="font-size:0.8rem;color:#64748b;margin-top:4px;">
            Has realizado 20 análisis en esta sesión. Recarga la página para continuar.
        </div>
    </div>""", unsafe_allow_html=True)
elif _tiempo_restante > 0:
    st.markdown(f"""<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
                padding:10px 16px;margin-bottom:12px;">
        <div style="font-size:0.8rem;color:#94a3b8;">
            ⏱ Espera {int(_tiempo_restante)+1}s antes del siguiente análisis
        </div>
    </div>""", unsafe_allow_html=True)

if st.button("Analizar perfil →", disabled=(_tiempo_restante > 0 or _limite_alcanzado)):
    if nomina <= 0:
        st.warning("Introduce unos ingresos válidos.")
    else:
        prob, factores, riesgo_vuln, meses, alertas_vuln, nivel_vuln = calcular_score(
            edad, nomina, alquiler, contrato, antiguedad,
            fuente, impagos, sector, ccaa, nacionalidad, tuple(ocupantes))
        label, color, conclusion, detalle = interpretar(prob)
        st.session_state.n_analisis += 1
        st.session_state.ultimo_analisis = _time.time()

        st.session_state["resultado"] = {
            "prob": prob, "factores": factores, "label": label,
            "color": color, "conclusion": conclusion, "detalle": detalle,
            "riesgo_vuln": riesgo_vuln, "meses": meses,
            "alertas_vuln": alertas_vuln, "nivel_vuln": nivel_vuln,
            "datos": {"nomina": nomina, "alquiler": alquiler, "edad": edad,
                      "personas": len(ocupantes), "contrato": contrato, "antiguedad": antiguedad,
                      "fuente": fuente, "sector": sector, "sector_display": sector_display,
                      "ccaa": ccaa, "impagos": impagos, "nacionalidad": nacionalidad,
                      "ocupantes": ", ".join(ocupantes),
                      "n_perceptores": int(n_perceptores),
                      "ingresos_detalle": ", ".join([f"€{v:,}" for v in _ingresos if v > 0])}
        }
if "resultado" in st.session_state:
    r = st.session_state["resultado"]
    prob=r["prob"]; factores=r["factores"]; label=r["label"]
    color=r["color"]; conclusion=r["conclusion"]; detalle=r["detalle"]
    alertas_vuln=r.get("alertas_vuln",[]); nivel_vuln=r.get("nivel_vuln","")
    meses=r.get("meses", 8); riesgo_vuln=r.get("riesgo_vuln", 0)

    st.markdown("---")

    col_res, col_nuevo = st.columns([3,1])
    with col_res:
        st.markdown("### Resultado del análisis")
    with col_nuevo:
        if st.button("＋ Nuevo inquilino", key="nuevo_inq"):
            # Keep candidatos but clear resultado to force new analysis
            del st.session_state["resultado"]
            st.rerun()

    st.markdown(f"""
    <div style="text-align:center;padding:2rem 0 1.5rem 0;">
        <div style="font-family:'DM Serif Display',serif;font-size:5rem;line-height:1;
                    color:{color};margin-bottom:8px;font-weight:700;">{round(prob*100)}%</div>
        <div style="font-size:0.72rem;letter-spacing:0.12em;text-transform:uppercase;
                    color:#94a3b8;margin-bottom:12px;">Índice orientativo de riesgo</div>
        <span style="background:{color}15;color:{color};border:1px solid {color}40;
                     padding:6px 20px;border-radius:100px;font-size:0.9rem;font-weight:600;">
            {label}
        </span>
    </div>""", unsafe_allow_html=True)

    st.markdown(f"""
    <div style="background:{color}08;border:1px solid {color}30;border-radius:10px;padding:18px 20px;margin-bottom:12px;">
        <div style="font-size:0.68rem;letter-spacing:0.12em;text-transform:uppercase;color:{color};font-weight:600;margin-bottom:6px;">Análisis</div>
        <div style="font-size:0.92rem;color:#1e293b;line-height:1.6;">{conclusion}</div>
    </div>
    <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;padding:18px 20px;margin-bottom:12px;">
        <div style="font-size:0.68rem;letter-spacing:0.12em;text-transform:uppercase;color:#64748b;font-weight:600;margin-bottom:6px;">Detalle</div>
        <div style="font-size:0.92rem;color:#1e293b;line-height:1.6;">{detalle}</div>
    </div>
    <div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;padding:12px 16px;margin-bottom:24px;">
        <div style="font-size:0.72rem;color:#92400e;line-height:1.5;">
            ⚠️ Análisis orientativo basado en estadísticas agregadas públicas. No constituye asesoramiento legal, financiero ni inmobiliario.
        </div>
    </div>""", unsafe_allow_html=True)

    # ── BLOQUE VULNERABILIDAD LEGAL ───────────────────────────────────────────
    if alertas_vuln or nivel_vuln:
        vuln_color = "#dc2626" if riesgo_vuln >= 0.15 else "#d97706" if riesgo_vuln >= 0.10 else "#64748b"
        alertas_html = "".join(f"<div style='margin-top:6px;font-size:0.85rem;color:#1e293b;'>{a}</div>" for a in alertas_vuln)
        st.markdown(f"""
        <div style="background:{vuln_color}08;border:1px solid {vuln_color}30;
                    border-radius:10px;padding:18px 20px;margin-bottom:16px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <div style="font-size:0.68rem;letter-spacing:0.12em;text-transform:uppercase;
                            color:{vuln_color};font-weight:600;">Protección legal estimada</div>
                <span style="background:{vuln_color}15;color:{vuln_color};border:1px solid {vuln_color}30;
                             padding:3px 12px;border-radius:100px;font-size:0.78rem;font-weight:600;">
                    {nivel_vuln}
                </span>
            </div>
            <div style="display:flex;gap:24px;margin-bottom:8px;">
                <div style="text-align:center;">
                    <div style="font-family:'DM Serif Display',serif;font-size:1.8rem;
                                color:{vuln_color};font-weight:700;">{meses}</div>
                    <div style="font-size:0.7rem;color:#94a3b8;">meses estimados<br>proceso desahucio</div>
                </div>
                <div style="flex:1;">{alertas_html if alertas_html else "<div style='color:#64748b;font-size:0.85rem;'>Sin alertas de vulnerabilidad.</div>"}</div>
            </div>
            <div style="font-size:0.72rem;color:#94a3b8;margin-top:8px;border-top:1px solid {vuln_color}20;padding-top:8px;">
                Basado en Ley 12/2023 de Vivienda y decretos autonómicos de vulnerabilidad.
                Este dato es orientativo y no constituye asesoramiento legal.
            </div>
        </div>""", unsafe_allow_html=True)

    # ── RECOMENDACIONES ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Recomendaciones para el propietario")

    ocupantes_res = r.get("datos", {}).get("ocupantes", "")
    ocupantes_list = r.get("datos", {}).get("ocupantes", "").split(", ") if ocupantes_res else []
    recos = generar_recomendaciones(prob, factores, nivel_vuln, meses, ocupantes_list)

    RECO_CONFIG = {
        "ok":          ("#16a34a", "#f0fdf4", "✓"),
        "opcional":    ("#0ea5e9", "#f0f9ff", "◎"),
        "alerta":      ("#d97706", "#fffbeb", "⚠"),
        "recomendado": ("#7c3aed", "#faf5ff", "★"),
        "urgente":     ("#dc2626", "#fef2f2", "!"),
        "legal":       ("#0f172a", "#f8fafc", "⚖"),
        "siempre":     ("#475569", "#f8fafc", "→"),
    }

    for reco in recos:
        cfg = RECO_CONFIG.get(reco["tipo"], ("#475569", "#f8fafc", "→"))
        col_r, bg_r, icono = cfg
        st.markdown(f"""
        <div style="background:{bg_r};border:1px solid {col_r}25;border-left:3px solid {col_r};
                    border-radius:8px;padding:14px 16px;margin-bottom:10px;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
                <div style="flex:1;">
                    <div style="font-size:0.82rem;font-weight:600;color:{col_r};margin-bottom:4px;">
                        {icono} {reco["titulo"]}
                    </div>
                    <div style="font-size:0.82rem;color:#1e293b;line-height:1.5;">{reco["detalle"]}</div>
                </div>
                <div style="text-align:right;flex-shrink:0;">
                    <span style="font-size:0.72rem;color:{col_r};background:{col_r}15;
                                 padding:2px 8px;border-radius:100px;white-space:nowrap;">
                        {reco["coste"]}
                    </span>
                </div>
            </div>
        </div>""", unsafe_allow_html=True)

    # ── GRÁFICOS ──────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Análisis visual")
    st.markdown("<p style='color:#94a3b8;font-size:0.85rem;margin-top:-12px;margin-bottom:16px;'>Comparativa del perfil del inquilino vs media española.</p>", unsafe_allow_html=True)

    import pandas as pd
    _pm = {"Ratio alquiler/renta":0.12,"Historial impagos":0.00,"Contrato laboral":0.08,
           "Antigüedad laboral":0.06,"Fuente de ingresos":0.06,"Mora CCAA":0.13,
           "Sector laboral":0.10,"Franja de edad":0.09}
    _short = {"Ratio alquiler/renta":"Ratio","Historial impagos":"Impagos",
              "Contrato laboral":"Contrato","Antigüedad laboral":"Antigüedad",
              "Fuente de ingresos":"Ingresos","Mora CCAA":"CCAA",
              "Sector laboral":"Sector","Franja de edad":"Edad"}
    _df = pd.DataFrame({
        "Inquilino (%)": {_short.get(k,k): round(v*100) for k,v in factores.items()},
        "Media España (%)": {_short.get(k,k): round(_pm.get(k,0.10)*100) for k in factores}
    })
    st.bar_chart(_df, color=["#00C896","#cbd5e1"])

    # ── Barras detalle ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("<div style='font-size:0.7rem;letter-spacing:0.1em;text-transform:uppercase;"
                "color:#94a3b8;margin-bottom:12px;font-weight:600;'>Factores analizados</div>",
                unsafe_allow_html=True)
    for nombre, val in factores.items():
        pct = int(val*100)
        med = int(PERFIL_MEDIO.get(nombre, 0.10)*100)
        bar_color = "#16a34a" if val<0.08 else "#d97706" if val<0.18 else "#ea580c" if val<0.32 else "#dc2626"
        diff = pct - med
        diff_txt = f"+{diff}pp vs media" if diff > 0 else f"{diff}pp vs media"
        diff_col = "#dc2626" if diff > 0 else "#16a34a"
        st.markdown(f"""
        <div style="margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                <span style="font-size:0.8rem;color:#475569;">{nombre}</span>
                <span style="font-size:0.75rem;color:{diff_col};font-weight:600;">{diff_txt}</span>
            </div>
            <div style="flex:1;height:6px;background:#E2E8F0;border-radius:100px;overflow:hidden;position:relative;">
                <div style="width:{med}%;height:100%;background:#cbd5e1;border-radius:100px;position:absolute;"></div>
                <div style="width:{pct}%;height:100%;background:{bar_color};border-radius:100px;position:absolute;opacity:0.85;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;margin-top:2px;">
                <span style="font-size:0.68rem;color:{bar_color};font-weight:600;">{pct}%</span>
                <span style="font-size:0.68rem;color:#94a3b8;">media: {med}%</span>
            </div>
        </div>""", unsafe_allow_html=True)

    
# ── HISTORIAL ─────────────────────────────────────────────────────────────
    if len(st.session_state.get("candidatos",[])) > 1:
        st.markdown("---")
        st.markdown("### Comparativa de candidatos")
        for _c in st.session_state.candidatos:
            _pc=_c["prob"]; _cc="#16a34a" if _pc<8 else "#d97706" if _pc<18 else "#ea580c" if _pc<32 else "#dc2626"
            _ea=_c["n"]==len(st.session_state.candidatos)
            st.markdown(f'<div style="background:{"#f0fdf9" if _ea else "#f8fafc"};border:{"2px" if _ea else "1px"} solid {_cc};border-radius:8px;padding:12px 16px;margin-bottom:8px;display:flex;align-items:center;justify-content:space-between;"><div style="display:flex;align-items:center;gap:12px;"><div style="font-size:1.8rem;font-weight:700;color:{_cc};min-width:52px;">{_pc}%</div><div><div style="font-size:0.82rem;font-weight:600;color:#0f172a;">Candidato {_c["n"]}{"  ← actual" if _ea else ""}</div><div style="font-size:0.75rem;color:#94a3b8;">{_c["ccaa"]} · {_c["contrato"]} · ratio {_c["ratio"]}%</div></div></div><span style="background:{_cc}15;color:{_cc};padding:3px 12px;border-radius:100px;font-size:0.78rem;font-weight:600;">{_c["label"]}</span></div>', unsafe_allow_html=True)
        if st.button("🗑 Limpiar historial",key="clr"): st.session_state.candidatos=[]; st.rerun()

    
# ── CALCULADORA ───────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Coste real estimado del impago")
    _alq2=r.get("datos",{}).get("alquiler",750); _mc=meses if meses else 8
    _cr=_alq2*_mc; _cj=2800 if prob<0.32 else 4200; _cs=round(_alq2*12*0.035); _ct=_cr+_cj; _ah=max(0,_ct-_cs)
    _c1,_c2,_c3=st.columns(3)
    for _col,_val,_lbl,_clr in [(_c1,f"€{_cr:,}",f"Rentas sin cobrar ({_mc}m)","#dc2626"),(_c2,f"€{_cj:,}","Costes judiciales","#ea580c"),(_c3,f"€{_ct:,}","Total sin seguro","#0f172a")]:
        _col.markdown(f'<div style="text-align:center;padding:14px;background:white;border:1px solid #e2e8f0;border-radius:10px;"><div style="font-size:1.4rem;font-weight:700;color:{_clr};">{_val}</div><div style="font-size:0.7rem;color:#94a3b8;margin-top:4px;">{_lbl}</div></div>',unsafe_allow_html=True)
    st.markdown(f'<div style="background:#f0fdf9;border:1px solid #00C89640;border-radius:8px;padding:14px 16px;margin:12px 0;display:flex;justify-content:space-between;align-items:center;"><div><b style="font-size:0.82rem;">Seguro de impago anual</b><div style="font-size:0.78rem;color:#64748b;">~3.5% renta · hasta 12 meses + gastos judiciales</div></div><div style="text-align:right;"><div style="font-size:1.2rem;font-weight:700;color:#00C896;">€{_cs:,}/año</div><div style="font-size:0.72rem;color:#16a34a;">Ahorro potencial: €{_ah:,}</div></div></div>',unsafe_allow_html=True)

    
# ── SEMÁFORO CLÁUSULAS ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Cláusulas recomendadas para el contrato")
    for _a,_i,_c,_t,_d in [(True,"✓","#16a34a","Domiciliación bancaria obligatoria","Pago por domiciliación — detecta impago en el primer mes."),(True,"✓","#16a34a","Fianza legal (1 mes)","Obligatoria por ley. Depositar en organismo autonómico."),(True,"✓","#16a34a","Inventario detallado con fotografías","Fotografías fechadas y firmadas del estado del inmueble."),(True,"✓","#16a34a","Actualización anual según IPC","Cláusula referenciada al IPC oficial."),(True,"⚖","#7c3aed","Mediación previa obligatoria (Ley 1/2025)","Obligatoria desde abril 2025 antes de cualquier desahucio."),(prob>=0.08,"⚠" if prob>=0.08 else "—","#d97706" if prob>=0.08 else "#94a3b8","2 meses garantía adicional","Máximo legal: 2 meses adicionales sobre la fianza."),(prob>=0.18,"⚠" if prob>=0.18 else "—","#ea580c" if prob>=0.18 else "#94a3b8","Aval bancario o fiador solidario","Fiador con ingresos estables que responde solidariamente."),(prob>=0.18,"⚠" if prob>=0.18 else "—","#ea580c" if prob>=0.18 else "#94a3b8","Seguro de impago antes de firmar","Cubre impago + desahucio + defensa jurídica."),(prob>=0.32,"!" if prob>=0.32 else "—","#dc2626" if prob>=0.32 else "#94a3b8","Consulta voluntaria de ficheros de morosos","Consulta voluntaria en ficheros públicos de morosidad antes de firmar. Independiente de esta herramienta.")]:
        st.markdown(f'<div style="background:{_c}08 if {_a} else #f8fafc;border:1px solid {_c}30;border-left:3px solid {_c};border-radius:8px;padding:10px 14px;margin-bottom:8px;opacity:{"1" if _a else "0.35"};"><div style="display:flex;gap:10px;align-items:flex-start;"><span style="color:{_c};font-weight:700;min-width:20px;">{_i}</span><div><div style="font-size:0.82rem;font-weight:600;color:#0f172a;">{_t}</div><div style="font-size:0.78rem;color:#64748b;">{_d}</div></div></div></div>',unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)



    st.markdown("---")
    st.markdown("""<div style="text-align:center;margin-bottom:20px;">
        <div style="font-family:'DM Serif Display',serif;font-size:1.4rem;color:#0f172a;margin-bottom:6px;">
            Descarga tu informe completo en PDF
        </div>
        <div style="font-size:0.88rem;color:#475569;max-width:420px;margin:0 auto;line-height:1.6;">
            Incluye estadísticas judiciales de tu zona, recursos legales,
            calculadora de coste real y cláusulas contractuales recomendadas.
        </div>
    </div>""", unsafe_allow_html=True)

    recos_list = generar_recomendaciones(prob, factores, nivel_vuln, meses,
        r.get("datos",{}).get("ocupantes","").split(", ")
        if r.get("datos",{}).get("ocupantes") else [])
    pdf_buffer = generar_pdf(
        r["datos"], prob, factores, label, conclusion, detalle,
        recos_list, alertas_vuln, nivel_vuln, meses)
    st.download_button(
        label="⬇ Descargar informe PDF completo",
        data=pdf_buffer,
        file_name=f"predice_impago_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
        mime="application/pdf"
    )

# ── # ─── FOOTER ───────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("""<div style="text-align:center;padding:1rem 0;">
    <p style="font-size:0.75rem;color:#cbd5e1;line-height:1.6;">
        Predice_Impago · Herramienta de apoyo orientativo basada en estadísticas agregadas públicas. No constituye asesoramiento legal, financiero ni inmobiliario. No reemplaza la valoración profesional.<br>
        Datos estadísticos: INE · Banco de España · Alquiler Seguro · SEPE<br>
        
    </p>
</div>""", unsafe_allow_html=True)
    # ── RECOMENDACIONES ─────────────────────────────────────────────────────────
