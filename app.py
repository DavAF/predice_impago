import streamlit as st
import csv
import os
import io
import math
import re
import secrets
import requests
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

st.set_page_config(
    page_title="Predice_Impago — Scoring de Inquilinos",
    page_icon="🏠", layout="centered", initial_sidebar_state="collapsed"
)

FORMSPREE_URL = "https://formspree.io/f/xnjrzvdq"
RESEND_API_KEY = "RE_PLACEHOLDER"  # ← sustituir por tu key re_xxxx

# Dominios desechables bloqueados
DOMINIOS_DESECHABLES = {
    "mailinator.com","tempmail.com","guerrillamail.com","throwam.com",
    "yopmail.com","trashmail.com","sharklasers.com","guerrillamailblock.com",
    "grr.la","guerrillamail.info","spam4.me","10minutemail.com",
    "10minutemail.net","dispostable.com","fakeinbox.com","mailnull.com",
    "maildrop.cc","spamgourmet.com","spamgourmet.net","spamgourmet.org",
    "spamhereplease.com","spamoff.de","trashmail.at","trashmail.io",
    "trashmail.me","trashmail.net","discard.email","spamfree24.org",
}
LEADS_FILE = "leads.csv"
TRACKER_FILE = "tracker.csv"

def registrar_analisis(prob, factores, label, ccaa, sector, contrato, ratio):
    fila = {"timestamp": datetime.now().isoformat(), "prob": round(prob*100),
            "resultado": label, "ccaa": ccaa, "sector": sector,
            "contrato": contrato, "ratio": ratio}
    existe = os.path.exists(TRACKER_FILE)
    try:
        with open(TRACKER_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fila.keys())
            if not existe: writer.writeheader()
            writer.writerow(fila)
    except Exception:
        pass


# ─── DATOS ACTUALIZADOS Q4 2025 ────────────────────────────────────────────────
# INE EPA Q4 2025 + SEPE Informe Mercado Trabajo 2024 + Fundación Alquiler Seguro 2023

PARO_POR_SECTOR = {
    "hosteleria": 0.16, "construccion": 0.14, "comercio": 0.11,
    "transporte": 0.09, "industria": 0.08, "administracion": 0.04,
    "tecnologia": 0.05, "sanidad": 0.04, "educacion": 0.03, "otro": 0.12
}

MORA_POR_CCAA = {
    "Murcia": 0.22, "Comunitat Valenciana": 0.20, "Canarias": 0.19,
    "Andalucía": 0.18, "Extremadura": 0.17, "Castilla-La Mancha": 0.15,
    "Cataluña": 0.14, "Baleares": 0.14, "Madrid": 0.13,
    "Castilla y León": 0.12, "Galicia": 0.11, "Asturias": 0.11,
    "Cantabria": 0.10, "Aragón": 0.09, "La Rioja": 0.09,
    "País Vasco": 0.08, "Navarra": 0.08, "Ceuta/Melilla": 0.22,
    "No especificada": 0.13
}

# EPA Q4 2025 — tasa paro por edad actualizada
PARO_POR_EDAD = {
    "18-24": 0.26, "25-34": 0.13, "35-44": 0.08,
    "45-54": 0.09, "55-64": 0.13, "65+": 0.07
}

RIESGO_CONTRATO = {
    "Indefinido": 0.02, "Fijo discontinuo": 0.14,
    "Temporal": 0.24, "Autónomo": 0.20, "Sin contrato": 0.48
}
RIESGO_ANTIGUEDAD = {
    "Menos de 6 meses": 0.30, "6-12 meses": 0.18,
    "1-3 años": 0.08, "Más de 3 años": 0.02
}
RIESGO_FUENTE = {
    "Nómina empresa privada": 0.06,
    "Funcionario / empleado público": 0.01,
    "Pensión": 0.03,
    "Autónomo con facturación regular": 0.14,
    "Prestación desempleo": 0.30,
    "Otros ingresos": 0.20
}
RIESGO_IMPAGOS = {
    "Ninguno conocido": 0.00, "1 impago": 0.35,
    "2 impagos": 0.55, "3 o más": 0.75
}
CORR_NAC = {
    "Español / historial completo": 0.00,
    "Extranjero con historial en España": 0.03,
    "Extranjero sin historial en España": 0.07
}
# Tipos de ocupante — Ley 12/2023 Vivienda + decretos autonómicos
TIPOS_OCUPANTE = ["Adulto (18-64)", "Menor 0-3 años", "Menor 3-18 años", "Mayor 65+ años"]

RIESGO_OCUPANTE = {
    "Adulto (18-64)": 0.00,
    "Menor 0-3 años": 0.18,
    "Menor 3-18 años": 0.12,
    "Mayor 65+ años": 0.10,
}

MESES_DESAHUCIO_BASE = 8
MESES_EXTRA = {"Menor 0-3 años": 16, "Menor 3-18 años": 10, "Mayor 65+ años": 8}

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
    nivel = "Sin vulnerabilidad aparente"
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
        return "Riesgo Bajo", "#16a34a", \
            "El perfil analizado presenta indicadores financieros sólidos. La probabilidad de impago se sitúa en niveles bajos según los parámetros evaluados.", \
            "El ratio de esfuerzo y la estabilidad laboral están dentro de márgenes favorables."
    if prob < 0.18:
        return "Riesgo Moderado", "#d97706", \
            "El perfil presenta alguna variable con indicadores de atención. La probabilidad de impago es moderada.", \
            "Existen factores de riesgo menores. Considerar garantías adicionales como aval o meses extra de fianza."
    if prob < 0.32:
        return "Riesgo Elevado", "#ea580c", \
            "Varias variables del perfil presentan indicadores desfavorables. La probabilidad de impago es elevada.", \
            "El perfil muestra fragilidad financiera. Se identifican factores de riesgo relevantes a valorar."
    return "Riesgo Muy Alto", "#dc2626", \
        "El perfil analizado presenta múltiples indicadores de riesgo simultáneos. La probabilidad de impago es muy alta.", \
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
    tiene_vuln     = nivel_vuln not in ("Sin vulnerabilidad aparente", "")

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
            "detalle": "El perfil acumula múltiples factores de riesgo simultáneos. La probabilidad de impago justifica reconsiderar el arrendamiento o exigir garantías muy sólidas.",
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
                "titulo": "Impagos previos — consultar ASNEF/RAI obligatorio",
                "detalle": "Con impagos declarados, la consulta en ficheros de morosos es imprescindible. Si figura en ASNEF activo, no arrendar.",
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
def radar_svg(factores_inquilino, factores_medio, size=320):
    labels = list(factores_inquilino.keys())
    vals_i = list(factores_inquilino.values())
    vals_m = list(factores_medio.values())
    n = len(labels)
    cx, cy, r = size//2, size//2, size//2 - 50
    angles = [math.pi/2 - 2*math.pi*i/n for i in range(n)]

    def point(val, angle, max_val=0.6):
        v = min(val / max_val, 1.0)
        return cx + r * v * math.cos(angle), cy - r * v * math.sin(angle)

    # Rejilla
    grid_lines = ""
    for lvl in [0.25, 0.5, 0.75, 1.0]:
        pts = " ".join(f"{cx + r*lvl*math.cos(a):.1f},{cy - r*lvl*math.sin(a):.1f}" for a in angles)
        grid_lines += f'<polygon points="{pts}" fill="none" stroke="#e2e8f0" stroke-width="1"/>\n'

    # Ejes
    axis_lines = ""
    for a in angles:
        x2, y2 = cx + r*math.cos(a), cy - r*math.sin(a)
        axis_lines += f'<line x1="{cx}" y1="{cy}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#e2e8f0" stroke-width="1"/>\n'

    # Polígono medio
    pts_m = " ".join(f"{point(v, a)[0]:.1f},{point(v, a)[1]:.1f}" for v, a in zip(vals_m, angles))
    # Polígono inquilino
    pts_i = " ".join(f"{point(v, a)[0]:.1f},{point(v, a)[1]:.1f}" for v, a in zip(vals_i, angles))

    # Labels
    label_els = ""
    short_labels = ["Ratio", "Impagos", "Contrato", "Antigüedad",
                    "Ingresos", "CCAA", "Sector", "Edad"]
    for i, (a, lbl) in enumerate(zip(angles, short_labels)):
        lx = cx + (r + 28) * math.cos(a)
        ly = cy - (r + 28) * math.sin(a)
        anchor = "middle" if abs(math.cos(a)) < 0.3 else ("start" if math.cos(a) > 0 else "end")
        label_els += f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" dominant-baseline="middle" font-size="10" fill="#64748b" font-family="DM Sans,sans-serif">{lbl}</text>\n'

    # Puntos
    dots_i = ""
    for v, a in zip(vals_i, angles):
        px, py = point(v, a)
        dots_i += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="#00C896" stroke="white" stroke-width="1.5"/>\n'

    svg = f'''<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}"
        xmlns="http://www.w3.org/2000/svg" style="max-width:100%;height:auto;">
        <rect width="{size}" height="{size}" fill="white" rx="12"/>
        {grid_lines}
        {axis_lines}
        <polygon points="{pts_m}" fill="#94a3b820" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="4,3"/>
        <polygon points="{pts_i}" fill="#00C89620" stroke="#00C896" stroke-width="2"/>
        {dots_i}
        {label_els}
        <circle cx="30" cy="{size-28}" r="6" fill="#00C896"/>
        <text x="40" y="{size-24}" font-size="10" fill="#475569" font-family="DM Sans,sans-serif">Inquilino</text>
        <line x1="90" y1="{size-28}" x2="102" y2="{size-28}" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="4,3"/>
        <circle cx="108" cy="{size-28}" r="4" fill="#94a3b8"/>
        <text x="116" y="{size-24}" font-size="10" fill="#475569" font-family="DM Sans,sans-serif">Perfil medio</text>
    </svg>'''
    return svg

# ─── GRÁFICO BARRAS COMPARATIVO (SVG puro) ────────────────────────────────────
def barras_svg(factores_inquilino, factores_medio, width=600, bar_h=28, gap=10):
    labels = list(factores_inquilino.keys())
    vals_i = list(factores_inquilino.values())
    vals_m = list(factores_medio.values())
    n = len(labels)
    label_w = 150
    chart_w = width - label_w - 20
    max_val = 0.6
    row_h = bar_h * 2 + gap + 8
    total_h = n * row_h + 50

    bars = ""
    for i, (lbl, vi, vm) in enumerate(zip(labels, vals_i, vals_m)):
        y0 = 30 + i * row_h
        wi = min(vi / max_val, 1.0) * chart_w
        wm = min(vm / max_val, 1.0) * chart_w
        pct_i = int(vi * 100)
        pct_m = int(vm * 100)

        color_i = "#16a34a" if vi < 0.08 else "#d97706" if vi < 0.18 else "#ea580c" if vi < 0.32 else "#dc2626"

        bars += f'''
        <text x="{label_w-8}" y="{y0+bar_h//2+4}" text-anchor="end" font-size="10"
              fill="#475569" font-family="DM Sans,sans-serif">{lbl}</text>
        <rect x="{label_w}" y="{y0}" width="{wi:.1f}" height="{bar_h}"
              fill="{color_i}" rx="4"/>
        <text x="{label_w+wi+5:.1f}" y="{y0+bar_h//2+4}" font-size="10"
              fill="{color_i}" font-weight="600" font-family="DM Sans,sans-serif">{pct_i}%</text>
        <rect x="{label_w}" y="{y0+bar_h+4}" width="{wm:.1f}" height="{bar_h-4}"
              fill="#94a3b840" rx="4" stroke="#94a3b8" stroke-width="1"/>
        <text x="{label_w+wm+5:.1f}" y="{y0+bar_h+4+(bar_h-4)//2+4}" font-size="9"
              fill="#94a3b8" font-family="DM Sans,sans-serif">{pct_m}%</text>
        '''

    svg = f'''<svg width="100%" viewBox="0 0 {width} {total_h}"
        xmlns="http://www.w3.org/2000/svg" style="max-width:100%;height:auto;">
        <rect width="{width}" height="{total_h}" fill="white" rx="12"/>
        <text x="10" y="18" font-size="11" font-weight="600" fill="#0f172a"
              font-family="DM Sans,sans-serif">Comparativa factor a factor</text>
        {bars}
        <circle cx="10" cy="{total_h-15}" r="5" fill="#00C896"/>
        <text x="20" y="{total_h-11}" font-size="10" fill="#475569"
              font-family="DM Sans,sans-serif">Inquilino analizado</text>
        <rect x="130" y="{total_h-20}" width="12" height="8"
              fill="#94a3b840" stroke="#94a3b8" stroke-width="1" rx="2"/>
        <text x="146" y="{total_h-11}" font-size="10" fill="#94a3b8"
              font-family="DM Sans,sans-serif">Perfil medio España</text>
    </svg>'''
    return svg

# ─── GENERADOR PDF ─────────────────────────────────────────────────────────────
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

    t_s  = sty("t",  fontSize=24, textColor=COLOR_DARK,  spaceAfter=4,  fontName="Helvetica-Bold")
    su_s = sty("su", fontSize=9,  textColor=COLOR_GRIS,  spaceAfter=2,  fontName="Helvetica")
    se_s = sty("se", fontSize=8,  textColor=COLOR_ACENTO,spaceAfter=6,  fontName="Helvetica-Bold")
    b_s  = sty("b",  fontSize=9,  textColor=COLOR_TEXTO, spaceAfter=4,  fontName="Helvetica", leading=13)
    d_s  = sty("d",  fontSize=7,  textColor=COLOR_GRIS,  spaceAfter=4,  fontName="Helvetica", leading=10)
    reco_t_s = sty("rt", fontSize=9, textColor=COLOR_DARK, spaceAfter=2, fontName="Helvetica-Bold")
    reco_d_s = sty("rd", fontSize=8, textColor=COLOR_GRIS, spaceAfter=3, fontName="Helvetica", leading=11)

    story = []

    # ── PORTADA ───────────────────────────────────────────────────────────────
    story.append(Paragraph("Predice_Impago", t_s))
    story.append(Paragraph("Informe de Análisis de Riesgo de Inquilino", su_s))
    story.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y a las %H:%M')}", su_s))
    story.append(HRFlowable(width="100%", thickness=2, color=COLOR_ACENTO, spaceAfter=10))

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
        ["Ingresos netos", f"{datos_inquilino.get('nomina',0):,} euros/mes"],
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
    if alertas_vuln or (nivel_vuln and nivel_vuln != "Sin vulnerabilidad aparente"):
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
        "AVISO LEGAL: Informe orientativo basado en estadísticas públicas INE EPA Q4 2025, Banco de España, "
        "Fundación Alquiler Seguro 2023 y SEPE. No constituye asesoramiento legal, financiero ni inmobiliario. "
        "prediceimpago.streamlit.app", d_s))

    doc.build(story)
    buffer.seek(0)
    return buffer


# ─── PERSISTENCIA ──────────────────────────────────────────────────────────────
def validar_email(email):
    """Valida formato y bloquea dominios desechables."""
    email = email.strip().lower()
    # Formato básico
    patron = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
    if not re.match(patron, email):
        return False, "Formato de email inválido."
    dominio = email.split("@")[1]
    if dominio in DOMINIOS_DESECHABLES:
        return False, "Este dominio de email no está permitido. Usa tu email personal o profesional."
    return True, ""

def enviar_pdf_resend(email, pdf_bytes, datos_analisis):
    """Envía el PDF como adjunto via Resend."""
    import base64
    if RESEND_API_KEY == "RE_PLACEHOLDER":
        return False, "API key no configurada"
    try:
        prob = datos_analisis.get("prob", "—")
        label = datos_analisis.get("label", "—")
        ccaa = datos_analisis.get("ccaa", "—")
        pdf_b64 = base64.b64encode(pdf_bytes).decode()
        payload = {
            "from": "Predice_Impago <onboarding@resend.dev>",
            "to": [email],
            "subject": f"Tu informe de riesgo — {label} ({prob}%)",
            "html": f"""
            <div style="font-family:sans-serif;max-width:560px;margin:0 auto;color:#1e293b;">
                <div style="background:#0f172a;padding:32px;text-align:center;border-radius:8px 8px 0 0;">
                    <h1 style="color:white;font-size:1.4rem;margin:0;">Predice_Impago</h1>
                    <p style="color:#94a3b8;margin:8px 0 0 0;font-size:0.85rem;">Informe de Análisis de Riesgo</p>
                </div>
                <div style="background:#f8fafc;padding:32px;border:1px solid #e2e8f0;border-top:none;">
                    <p style="margin:0 0 16px 0;">Hola,</p>
                    <p style="margin:0 0 16px 0;">Adjunto encontrarás el informe completo del análisis de riesgo para el inquilino analizado en <strong>{ccaa}</strong>.</p>
                    <div style="background:white;border:1px solid #e2e8f0;border-radius:8px;padding:20px;margin:20px 0;text-align:center;">
                        <div style="font-size:3rem;font-weight:700;color:#ea580c;">{prob}%</div>
                        <div style="color:#94a3b8;font-size:0.8rem;margin-top:4px;">Probabilidad de impago estimada</div>
                        <div style="margin-top:12px;background:#ea580c15;color:#ea580c;
                                    border:1px solid #ea580c30;padding:4px 16px;
                                    border-radius:100px;display:inline-block;font-weight:600;">
                            {label}
                        </div>
                    </div>
                    <p style="margin:0 0 16px 0;font-size:0.85rem;color:#64748b;">
                        El informe PDF adjunto incluye el análisis completo, factores de riesgo,
                        gráficos comparativos y recomendaciones específicas para tu situación.
                    </p>
                    <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
                    <p style="font-size:0.75rem;color:#94a3b8;margin:0;">
                        Predice_Impago · Herramienta orientativa basada en datos públicos INE, BdE y Fundación Alquiler Seguro.<br>
                        No constituye asesoramiento legal ni financiero.
                        <a href="https://github.com/DavAF/predice_impago/blob/main/privacy_policy.md"
                           style="color:#00C896;">Política de privacidad</a>
                    </p>
                </div>
            </div>""",
            "attachments": [{
                "filename": f"predice_impago_{datetime.now().strftime('%Y%m%d')}.pdf",
                "content": pdf_b64,
                "content_type": "application/pdf"
            }]
        }
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=10
        )
        if resp.status_code in (200, 201):
            return True, ""
        return False, f"Error {resp.status_code}: {resp.text}"
    except Exception as e:
        return False, str(e)

def guardar_lead_local(email, datos):
    fila = {"timestamp": datetime.now().isoformat(), "email": email, **datos}
    existe = os.path.exists(LEADS_FILE)
    with open(LEADS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fila.keys())
        if not existe:
            writer.writeheader()
        writer.writerow(fila)

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
        Calibrado con INE EPA Q4 2025, Banco de España y Fundación Alquiler Seguro.
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
st.markdown("<p style='color:#94a3b8;font-size:0.88rem;margin-top:-12px;margin-bottom:20px;'>10 variables · INE EPA Q4 2025 · Resultado instantáneo</p>", unsafe_allow_html=True)

col_a,col_b = st.columns(2)
with col_a: nomina  = st.number_input("Ingresos netos (€/mes)", min_value=0, max_value=20000, value=1800, step=100)
with col_b: alquiler= st.number_input("Alquiler mensual (€)",   min_value=0, max_value=10000, value=750,  step=50)

col_c,col_d = st.columns(2)
with col_c: edad = st.selectbox("Franja de edad del titular", list(PARO_POR_EDAD.keys()), index=2)
with col_d: n_ocupantes = st.number_input("Número de ocupantes", min_value=1, max_value=8, value=1, step=1)

# Ocupantes dinámicos
st.markdown("<div style='font-size:0.78rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#64748b;margin-bottom:8px;'>Tipo de cada ocupante</div>", unsafe_allow_html=True)
ocupantes = []
cols_ocu = st.columns(min(int(n_ocupantes), 4))
for i in range(int(n_ocupantes)):
    with cols_ocu[i % 4]:
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
if st.button("Analizar perfil →"):
    if nomina <= 0:
        st.warning("Introduce unos ingresos válidos.")
    else:
        prob, factores, riesgo_vuln, meses, alertas_vuln, nivel_vuln = calcular_score(
            edad, nomina, alquiler, contrato, antiguedad,
            fuente, impagos, sector, ccaa, nacionalidad, ocupantes)
        label, color, conclusion, detalle = interpretar(prob)
        registrar_analisis(prob, factores, label, ccaa, sector, contrato, round(alquiler/nomina*100) if nomina > 0 else 0)
        st.session_state["resultado"] = {
            "prob": prob, "factores": factores, "label": label,
            "color": color, "conclusion": conclusion, "detalle": detalle,
            "riesgo_vuln": riesgo_vuln, "meses": meses,
            "alertas_vuln": alertas_vuln, "nivel_vuln": nivel_vuln,
            "datos": {"nomina": nomina, "alquiler": alquiler, "edad": edad,
                      "personas": len(ocupantes), "contrato": contrato, "antiguedad": antiguedad,
                      "fuente": fuente, "sector": sector, "sector_display": sector_display,
                      "ccaa": ccaa, "impagos": impagos, "nacionalidad": nacionalidad,
                      "ocupantes": ", ".join(ocupantes)}
        }
if "resultado" in st.session_state:
    r = st.session_state["resultado"]
    prob=r["prob"]; factores=r["factores"]; label=r["label"]
    color=r["color"]; conclusion=r["conclusion"]; detalle=r["detalle"]
    alertas_vuln=r.get("alertas_vuln",[]); nivel_vuln=r.get("nivel_vuln","")
    meses=r.get("meses", 8); riesgo_vuln=r.get("riesgo_vuln", 0)

    st.markdown("---")
    st.markdown("### Resultado del análisis")

    st.markdown(f"""
    <div style="text-align:center;padding:2rem 0 1.5rem 0;">
        <div style="font-family:'DM Serif Display',serif;font-size:5rem;line-height:1;
                    color:{color};margin-bottom:8px;font-weight:700;">{round(prob*100)}%</div>
        <div style="font-size:0.72rem;letter-spacing:0.12em;text-transform:uppercase;
                    color:#94a3b8;margin-bottom:12px;">Probabilidad de impago estimada</div>
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

    tab1, tab2 = st.tabs(["🕸 Gráfico araña", "📊 Comparativa por factor"])

    with tab1:
        st.markdown("<p style='color:#94a3b8;font-size:0.85rem;margin-bottom:12px;'>"
                    "Perfil del inquilino vs media española por cada factor de riesgo.</p>",
                    unsafe_allow_html=True)
        svg_radar = radar_svg(factores, PERFIL_MEDIO)
        import streamlit.components.v1 as components
        components.html(f"""
        <html><body style="margin:0;padding:0;background:white;display:flex;justify-content:center;">
        {svg_radar}
        </body></html>""", height=340)

    with tab2:
        st.markdown("<p style='color:#94a3b8;font-size:0.85rem;margin-bottom:12px;'>"
                    "Barra superior = inquilino · Barra inferior = perfil medio España.</p>",
                    unsafe_allow_html=True)
        svg_bars = barras_svg(factores, PERFIL_MEDIO)
        import streamlit.components.v1 as components
        components.html(f"""
        <html><body style="margin:0;padding:0;background:white;">
        {svg_bars}
        </body></html>""", height=520)

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

    # ── Email + PDF ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("""<div style="text-align:center;margin-bottom:20px;">
        <div style="font-family:'DM Serif Display',serif;font-size:1.4rem;color:#0f172a;margin-bottom:6px;">
            Descarga el informe completo en PDF
        </div>
        <div style="font-size:0.85rem;color:#94a3b8;">Incluye gráficos comparativos y tabla de factores</div>
    </div>""", unsafe_allow_html=True)

    email_input = st.text_input("Tu email", placeholder="propietario@ejemplo.com")

    # Validación en tiempo real
    email_ok = False
    if email_input:
        email_ok, msg_error = validar_email(email_input)
        if not email_ok:
            st.markdown(f"<div style='color:#dc2626;font-size:0.8rem;margin-top:-8px;margin-bottom:8px;'>✗ {msg_error}</div>",
                        unsafe_allow_html=True)
        else:
            st.markdown("<div style='color:#16a34a;font-size:0.8rem;margin-top:-8px;margin-bottom:8px;'>✓ Email válido</div>",
                        unsafe_allow_html=True)

    acepta_comunicaciones = st.checkbox("✓ Acepto recibir actualizaciones del modelo y comunicaciones de Predice_Impago. Puedo darme de baja cuando quiera.")
    acepta_socios = st.checkbox("✓ Acepto que mi perfil sea compartido con socios comerciales del sector inmobiliario y asegurador. (Opcional)")
    st.markdown("""<div style="font-size:0.75rem;color:#94a3b8;margin-top:4px;margin-bottom:12px;">
        Al introducir tu email aceptas nuestra
        <a href="https://github.com/DavAF/predice_impago/blob/main/privacy_policy.md"
           style="color:#00C896;text-decoration:none;" target="_blank">Política de Privacidad</a>.
        El informe se enviará a tu correo.
    </div>""", unsafe_allow_html=True)

    if email_input and email_ok and acepta_comunicaciones:
        if st.button("📨 Enviar informe a mi email →"):
            datos_lead = {"edad": edad, "contrato": contrato, "sector": sector,
                          "ccaa": ccaa, "fuente": fuente, "impagos": impagos,
                          "prob": round(prob*100),
                          "ratio": round(alquiler/nomina*100) if nomina > 0 else 0,
                          "acepta_socios": acepta_socios,
                          "label": label}
            guardar_lead_local(email_input, datos_lead)
            enviar_formspree(email_input, datos_lead)

            with st.spinner("Generando y enviando informe..."):
                recos_list = generar_recomendaciones(prob, factores, nivel_vuln, meses,
                    r.get("datos",{}).get("ocupantes","").split(", ") if r.get("datos",{}).get("ocupantes") else [])
                pdf_buffer = generar_pdf(r["datos"], prob, factores, label, conclusion,
                                         detalle, recos_list, alertas_vuln, nivel_vuln, meses)
                pdf_bytes = pdf_buffer.read()
                ok, err = enviar_pdf_resend(email_input, pdf_bytes,
                    {"prob": round(prob*100), "label": label, "ccaa": ccaa})

            if ok:
                st.success(f"✓ Informe enviado a **{email_input}**. Revisa tu bandeja de entrada.")
            else:
                st.warning("No se pudo enviar por email. Descarga directamente:")
                st.download_button(
                    label="⬇ Descargar informe PDF",
                    data=io.BytesIO(pdf_bytes),
                    file_name=f"predice_impago_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf"
                )

# ─── FOOTER ───────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("""<div style="text-align:center;padding:1rem 0;">
    <p style="font-size:0.75rem;color:#cbd5e1;line-height:1.6;">
        Predice_Impago · INE EPA Q4 2025 · Banco de España · Fundación Alquiler Seguro 2023 · SEPE<br>
        Herramienta orientativa. No constituye asesoramiento legal ni financiero.<br>
        <a href="https://github.com/DavAF/predice_impago/blob/main/privacy_policy.md"
           style="color:#94a3b8;text-decoration:none;" target="_blank">Política de privacidad</a>
    </p>
</div>""", unsafe_allow_html=True)
