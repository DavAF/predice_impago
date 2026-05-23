import streamlit as st
import csv
import os
import io
import requests
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# ─── CONFIG ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Predice_Impago — Scoring de Inquilinos",
    page_icon="🏠",
    layout="centered",
    initial_sidebar_state="collapsed"
)

FORMSPREE_URL = "https://formspree.io/f/xnjrzvdq"
LEADS_FILE = "leads.csv"

# ─── SCORING ENGINE ────────────────────────────────────────────────────────────
PARO_POR_SECTOR = {
    "hosteleria": 0.18, "construccion": 0.16, "comercio": 0.12,
    "transporte": 0.10, "industria": 0.09, "administracion": 0.04,
    "tecnologia": 0.05, "sanidad": 0.04, "educacion": 0.03, "otro": 0.13
}
PARO_POR_CCAA = {
    "Andalucía": 0.19, "Extremadura": 0.18, "Canarias": 0.17,
    "Murcia": 0.14, "Ceuta/Melilla": 0.22, "Castilla-La Mancha": 0.13,
    "Comunitat Valenciana": 0.12, "Castilla y León": 0.11,
    "Asturias": 0.11, "Cantabria": 0.10, "Galicia": 0.10,
    "La Rioja": 0.09, "Aragón": 0.09, "Cataluña": 0.09,
    "Baleares": 0.09, "País Vasco": 0.08, "Navarra": 0.08,
    "Madrid": 0.08, "No especificada": 0.12
}
PARO_POR_EDAD = {
    "18-24": 0.28, "25-34": 0.14, "35-44": 0.09,
    "45-54": 0.10, "55-64": 0.14, "65+": 0.08
}
RIESGO_CONTRATO = {
    "Indefinido": 0.00, "Fijo discontinuo": 0.12,
    "Temporal": 0.22, "Autónomo": 0.18, "Sin contrato": 0.45
}
RIESGO_ANTIGUEDAD = {
    "Menos de 6 meses": 0.28, "6-12 meses": 0.16,
    "1-3 años": 0.08, "Más de 3 años": 0.02
}
RIESGO_FUENTE = {
    "Nómina empresa privada": 0.06,
    "Funcionario / empleado público": 0.01,
    "Pensión": 0.03,
    "Autónomo con facturación regular": 0.14,
    "Prestación desempleo": 0.28,
    "Otros ingresos": 0.20
}
RIESGO_IMPAGOS = {
    "Ninguno conocido": 0.00, "1 impago": 0.25,
    "2 impagos": 0.40, "3 o más": 0.60
}
CORR_NAC = {
    "Español / historial completo": 0.00,
    "Extranjero con historial en España": 0.03,
    "Extranjero sin historial en España": 0.08
}
RIESGO_PERSONAS = {1: 0.00, 2: 0.02, 3: 0.05, 4: 0.08, 5: 0.12}

def riesgo_ratio(alquiler, nomina):
    if nomina <= 0: return 0.50
    r = alquiler / nomina
    if r <= 0.25: return 0.02
    if r <= 0.30: return 0.05
    if r <= 0.35: return 0.10
    if r <= 0.40: return 0.18
    if r <= 0.50: return 0.30
    return 0.50

def calcular_score(edad, nomina, alquiler, contrato, antiguedad,
                   fuente, impagos, sector, ccaa, nacionalidad, personas):
    r_sector     = PARO_POR_SECTOR.get(sector, 0.13)
    r_ccaa       = PARO_POR_CCAA.get(ccaa, 0.12)
    r_edad       = PARO_POR_EDAD.get(edad, 0.12)
    r_contrato   = RIESGO_CONTRATO.get(contrato, 0.20)
    r_antiguedad = RIESGO_ANTIGUEDAD.get(antiguedad, 0.08)
    r_fuente     = RIESGO_FUENTE.get(fuente, 0.10)
    r_ratio      = riesgo_ratio(alquiler, nomina)
    r_impagos    = RIESGO_IMPAGOS.get(impagos, 0.00)
    r_nac        = CORR_NAC.get(nacionalidad, 0.00)
    r_personas   = RIESGO_PERSONAS.get(min(personas, 5), 0.12)
    score = (
        r_sector * 0.08 + r_ccaa * 0.07 + r_edad * 0.07 +
        r_contrato * 0.15 + r_antiguedad * 0.10 + r_fuente * 0.10 +
        r_ratio * 0.25 + r_impagos * 0.13 + r_nac * 0.03 + r_personas * 0.02
    )
    factores = {
        "Ratio alquiler/renta":  r_ratio,
        "Contrato laboral":      r_contrato,
        "Historial impagos":     r_impagos,
        "Antigüedad laboral":    r_antiguedad,
        "Fuente de ingresos":    r_fuente,
        "Sector laboral":        r_sector,
        "Comunidad autónoma":    r_ccaa,
        "Franja de edad":        r_edad,
    }
    return round(min(0.92, max(0.02, score)), 4), factores

def interpretar(prob):
    if prob < 0.10:
        return "Riesgo Bajo", "#1a7a4a", \
            "El perfil analizado presenta indicadores financieros sólidos. La probabilidad de impago se sitúa en niveles bajos según los parámetros evaluados.", \
            "El ratio de esfuerzo y la estabilidad laboral están dentro de márgenes favorables."
    if prob < 0.22:
        return "Riesgo Moderado", "#a07820", \
            "El perfil presenta alguna variable con indicadores de atención. La probabilidad de impago es moderada.", \
            "Existen factores de riesgo menores. Considerar garantías adicionales como aval o meses extra de fianza."
    if prob < 0.40:
        return "Riesgo Elevado", "#b85020", \
            "Varias variables del perfil presentan indicadores desfavorables. La probabilidad de impago es elevada.", \
            "El perfil muestra fragilidad financiera. Se identifican factores de riesgo relevantes a valorar."
    return "Riesgo Muy Alto", "#c03030", \
        "El perfil analizado presenta múltiples indicadores de riesgo simultáneos. La probabilidad de impago es muy alta.", \
        "El ratio de esfuerzo y/o el historial superan los umbrales críticos establecidos por el modelo."

# ─── GENERADOR PDF ─────────────────────────────────────────────────────────────
def generar_pdf(datos_inquilino, prob, factores, label, conclusion, detalle):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm)

    COLOR_PRINCIPAL = colors.HexColor("#0A0A0F")
    COLOR_ACENTO    = colors.HexColor("#00C896")
    COLOR_TEXTO     = colors.HexColor("#333333")
    COLOR_GRIS      = colors.HexColor("#666666")

    prob_pct = round(prob * 100)
    if prob < 0.10:   semaforo_hex = "#1a7a4a"
    elif prob < 0.22: semaforo_hex = "#a07820"
    elif prob < 0.40: semaforo_hex = "#b85020"
    else:             semaforo_hex = "#c03030"
    COLOR_SEMAFORO = colors.HexColor(semaforo_hex)

    estilos = getSampleStyleSheet()
    titulo_style = ParagraphStyle("titulo", parent=estilos["Normal"],
        fontSize=22, textColor=COLOR_PRINCIPAL, spaceAfter=4,
        fontName="Helvetica-Bold", alignment=TA_LEFT)
    subtitulo_style = ParagraphStyle("subtitulo", parent=estilos["Normal"],
        fontSize=10, textColor=COLOR_GRIS, spaceAfter=2,
        fontName="Helvetica", alignment=TA_LEFT)
    seccion_style = ParagraphStyle("seccion", parent=estilos["Normal"],
        fontSize=9, textColor=COLOR_ACENTO, spaceAfter=4,
        fontName="Helvetica-Bold", alignment=TA_LEFT,
        textTransform="uppercase", letterSpacing=1)
    body_style = ParagraphStyle("body", parent=estilos["Normal"],
        fontSize=10, textColor=COLOR_TEXTO, spaceAfter=6,
        fontName="Helvetica", leading=14)
    disclaimer_style = ParagraphStyle("disclaimer", parent=estilos["Normal"],
        fontSize=8, textColor=COLOR_GRIS, spaceAfter=4,
        fontName="Helvetica", leading=11)

    story = []

    # Cabecera
    story.append(Paragraph("Predice_Impago", titulo_style))
    story.append(Paragraph("Informe de Análisis de Riesgo de Inquilino", subtitulo_style))
    story.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y a las %H:%M')}", subtitulo_style))
    story.append(HRFlowable(width="100%", thickness=2, color=COLOR_ACENTO, spaceAfter=12))

    # Resultado principal
    story.append(Paragraph("Resultado del Análisis", seccion_style))
    resultado_data = [
        [Paragraph(f"<font size=32 color='{semaforo_hex}'><b>{prob_pct}%</b></font>", estilos["Normal"]),
         Paragraph(f"<font size=14 color='{semaforo_hex}'><b>{label}</b></font><br/><br/>"
                   f"<font size=10 color='#333333'>{conclusion}</font>", estilos["Normal"])]
    ]
    resultado_table = Table(resultado_data, colWidths=[40*mm, 130*mm])
    resultado_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f8f8f8")),
        ("ROUNDEDCORNERS", [6]),
        ("TOPPADDING", (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LEFTPADDING", (0,0), (-1,-1), 12),
    ]))
    story.append(resultado_table)
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>Detalle:</b> {detalle}", body_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd"), spaceAfter=10))

    # Datos del inquilino
    story.append(Paragraph("Datos Analizados", seccion_style))
    filas = [
        ["Variable", "Valor"],
        ["Ingresos netos", f"{datos_inquilino['nomina']:,} €/mes"],
        ["Alquiler mensual", f"{datos_inquilino['alquiler']:,} €/mes"],
        ["Ratio esfuerzo", f"{round(datos_inquilino['alquiler']/datos_inquilino['nomina']*100)}% de los ingresos"],
        ["Franja de edad", datos_inquilino["edad"]],
        ["Tipo de contrato", datos_inquilino["contrato"]],
        ["Antigüedad laboral", datos_inquilino["antiguedad"]],
        ["Fuente de ingresos", datos_inquilino["fuente"]],
        ["Sector laboral", datos_inquilino["sector_display"]],
        ["Comunidad autónoma", datos_inquilino["ccaa"]],
        ["Impagos anteriores", datos_inquilino["impagos"]],
        ["Historial bancario", datos_inquilino["nacionalidad"]],
        ["Personas en el piso", str(datos_inquilino["personas"])],
    ]
    tabla = Table(filas, colWidths=[80*mm, 90*mm])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), COLOR_PRINCIPAL),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#dddddd")),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(tabla)
    story.append(Spacer(1, 10))

    # Factores de riesgo
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd"), spaceAfter=10))
    story.append(Paragraph("Factores de Riesgo Individuales", seccion_style))
    factor_filas = [["Factor", "Indicador de riesgo", "Nivel"]]
    for nombre, val in factores.items():
        pct = int(val * 100)
        if val < 0.10:   nivel = "Bajo"
        elif val < 0.22: nivel = "Moderado"
        elif val < 0.40: nivel = "Elevado"
        else:            nivel = "Muy alto"
        factor_filas.append([nombre, f"{pct}%", nivel])
    ftabla = Table(factor_filas, colWidths=[80*mm, 40*mm, 50*mm])
    ftabla.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), COLOR_PRINCIPAL),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#dddddd")),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(ftabla)
    story.append(Spacer(1, 16))

    # Disclaimer
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd"), spaceAfter=8))
    story.append(Paragraph(
        "AVISO LEGAL: Este informe es orientativo y se basa en estadísticas agregadas públicas del INE (2023) "
        "y del Banco de España. No constituye asesoramiento legal, financiero ni inmobiliario. "
        "Predice_Impago no se hace responsable de las decisiones tomadas basándose en este análisis. "
        "prediceimpago.streamlit.app",
        disclaimer_style))

    doc.build(story)
    buffer.seek(0)
    return buffer

# ─── PERSISTENCIA ──────────────────────────────────────────────────────────────
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
        payload = {"email": email, "_subject": "Nuevo lead Predice_Impago", **datos}
        r = requests.post(FORMSPREE_URL, json=payload, timeout=5)
        return r.status_code == 200
    except Exception:
        return False

# ─── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background-color: #0A0A0F; color: #E8E4DC; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 640px; }
h1, h2, h3 { font-family: 'DM Serif Display', serif !important; color: #F0EDE6 !important; }
.stSelectbox > div > div,
.stNumberInput > div > div > input {
    background-color: #12121A !important; border: 1px solid #1E1E2A !important;
    color: #E8E4DC !important; border-radius: 8px !important;
}
.stSelectbox label, .stNumberInput label, .stTextInput label {
    color: #9B9688 !important; font-size: 0.78rem !important;
    font-weight: 600 !important; letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
}
.stButton > button {
    background: #00C896 !important; color: #0A0A0F !important;
    border: none !important; border-radius: 8px !important;
    font-weight: 600 !important; font-family: 'DM Sans', sans-serif !important;
    font-size: 1rem !important; padding: 0.6rem 2rem !important; width: 100%;
}
.stButton > button:hover { background: #00E6AC !important; }
.stTextInput > div > div > input {
    background-color: #12121A !important; border: 1px solid #1E1E2A !important;
    color: #E8E4DC !important; border-radius: 8px !important;
}
.stCheckbox label { color: #9B9688 !important; font-size: 0.85rem !important; }
.stDownloadButton > button {
    background: transparent !important; color: #00C896 !important;
    border: 1px solid #00C89640 !important; border-radius: 8px !important;
    font-weight: 600 !important; width: 100%;
}
hr { border-color: #1E1E2A !important; }
</style>
""", unsafe_allow_html=True)

# ─── COOKIES ──────────────────────────────────────────────────────────────────
if "cookies_ok" not in st.session_state:
    st.session_state.cookies_ok = False

if not st.session_state.cookies_ok:
    st.markdown("""
    <div style="background:#12121A;border:1px solid #1E1E2A;border-radius:12px;padding:20px 24px;margin-bottom:24px;">
        <p style="color:#E8E4DC;font-size:0.9rem;margin:0 0 12px 0;">
            🍪 <strong>Cookies analíticas</strong> — Recogemos datos de uso anónimos
            (sector, franja de edad, resultado) para mejorar el modelo.
            No compartimos datos personales con terceros.
        </p>
    </div>
    """, unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("✓ Aceptar"):
            st.session_state.cookies_ok = True
            st.rerun()
    with c2:
        if st.button("Solo esenciales"):
            st.session_state.cookies_ok = True
            st.rerun()
    st.stop()

# ─── HEADER ───────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;padding:2rem 0 1rem 0;">
    <span style="font-size:11px;font-weight:600;letter-spacing:0.15em;text-transform:uppercase;
                 color:#00C896;border:1px solid #00C89640;padding:5px 14px;border-radius:100px;">
        Scoring de Inquilinos · Beta Gratuita
    </span>
    <h1 style="font-size:2.4rem;margin:1rem 0 0.5rem 0;line-height:1.15;">
        ¿Tu inquilino dejará<br><em style="color:#00C896;">de pagar?</em>
    </h1>
    <p style="color:#9B9688;font-size:1rem;max-width:420px;margin:0 auto 2rem auto;line-height:1.7;font-weight:300;">
        Análisis de riesgo calibrado con datos reales del INE y Banco de España. Gratuito durante la beta.
    </p>
</div>
""", unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
for col, num, label in zip([c1,c2,c3],
    ["3.2%","8 meses","€6.200"],
    ["Morosidad media España","Proceso medio desahucio","Coste medio impago anual"]):
    col.markdown(f"""
    <div style="text-align:center;padding:14px;background:#12121A;border:1px solid #1E1E2A;border-radius:10px;">
        <div style="font-family:'DM Serif Display',serif;font-size:1.5rem;color:#F0EDE6;">{num}</div>
        <div style="font-size:0.7rem;color:#6B6860;margin-top:4px;">{label}</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
st.markdown("---")

# ─── FORMULARIO ───────────────────────────────────────────────────────────────
st.markdown("### Datos del inquilino")
st.markdown("<p style='color:#9B9688;font-size:0.88rem;margin-top:-12px;'>10 variables. Resultado instantáneo.</p>", unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)

col_a, col_b = st.columns(2)
with col_a:
    nomina = st.number_input("Ingresos netos (€/mes)", min_value=0, max_value=20000, value=1800, step=100)
with col_b:
    alquiler = st.number_input("Alquiler mensual (€)", min_value=0, max_value=10000, value=750, step=50)

col_c, col_d = st.columns(2)
with col_c:
    edad = st.selectbox("Franja de edad", list(PARO_POR_EDAD.keys()), index=2)
with col_d:
    personas = st.number_input("Personas en el piso", min_value=1, max_value=8, value=1, step=1)

col_e, col_f = st.columns(2)
with col_e:
    contrato = st.selectbox("Tipo de contrato", list(RIESGO_CONTRATO.keys()))
with col_f:
    antiguedad = st.selectbox("Antigüedad laboral", list(RIESGO_ANTIGUEDAD.keys()), index=2)

fuente = st.selectbox("Fuente principal de ingresos", list(RIESGO_FUENTE.keys()))

sector_labels = {
    "tecnologia":"Tecnología","sanidad":"Sanidad","educacion":"Educación",
    "administracion":"Administración pública","industria":"Industria / manufactura",
    "comercio":"Comercio","transporte":"Transporte / logística",
    "hosteleria":"Hostelería / turismo","construccion":"Construcción","otro":"Otro"
}
col_g, col_h = st.columns(2)
with col_g:
    sector_display = st.selectbox("Sector laboral", list(sector_labels.values()))
    sector = [k for k,v in sector_labels.items() if v == sector_display][0]
with col_h:
    ccaa = st.selectbox("Comunidad autónoma", list(PARO_POR_CCAA.keys()))

col_i, col_j = st.columns(2)
with col_i:
    impagos = st.selectbox("Impagos anteriores conocidos", list(RIESGO_IMPAGOS.keys()))
with col_j:
    nacionalidad = st.selectbox("Historial bancario en España", list(CORR_NAC.keys()))

st.markdown("<br>", unsafe_allow_html=True)

# ─── CÁLCULO ──────────────────────────────────────────────────────────────────
if st.button("Analizar perfil →"):
    if nomina <= 0:
        st.warning("Introduce unos ingresos válidos.")
    else:
        prob, factores = calcular_score(
            edad, nomina, alquiler, contrato, antiguedad,
            fuente, impagos, sector, ccaa, nacionalidad, personas
        )
        label, color, conclusion, detalle = interpretar(prob)

        st.session_state["resultado"] = {
            "prob": prob, "factores": factores, "label": label,
            "color": color, "conclusion": conclusion, "detalle": detalle,
            "datos": {
                "nomina": nomina, "alquiler": alquiler, "edad": edad,
                "personas": personas, "contrato": contrato, "antiguedad": antiguedad,
                "fuente": fuente, "sector": sector, "sector_display": sector_display,
                "ccaa": ccaa, "impagos": impagos, "nacionalidad": nacionalidad
            }
        }

if "resultado" in st.session_state:
    r = st.session_state["resultado"]
    prob = r["prob"]; factores = r["factores"]
    label = r["label"]; color = r["color"]
    conclusion = r["conclusion"]; detalle = r["detalle"]

    st.markdown("---")
    st.markdown("### Resultado del análisis")

    st.markdown(f"""
    <div style="text-align:center;padding:2rem 0 1.5rem 0;">
        <div style="font-family:'DM Serif Display',serif;font-size:5rem;
                    line-height:1;color:{color};margin-bottom:8px;">
            {round(prob*100)}%
        </div>
        <div style="font-size:0.72rem;letter-spacing:0.12em;text-transform:uppercase;
                    color:#6B6860;margin-bottom:12px;">
            Probabilidad de impago estimada
        </div>
        <span style="background:{color}22;color:{color};border:1px solid {color}44;
                     padding:5px 18px;border-radius:100px;font-size:0.88rem;font-weight:600;">
            {label}
        </span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="background:{color}11;border:1px solid {color}33;
                border-radius:10px;padding:18px 20px;margin-bottom:12px;">
        <div style="font-size:0.68rem;letter-spacing:0.12em;text-transform:uppercase;
                    color:{color};font-weight:600;margin-bottom:6px;">Análisis</div>
        <div style="font-size:0.92rem;color:#E8E4DC;line-height:1.6;">{conclusion}</div>
    </div>
    <div style="background:#12121A;border:1px solid #1E1E2A;
                border-radius:10px;padding:18px 20px;margin-bottom:12px;">
        <div style="font-size:0.68rem;letter-spacing:0.12em;text-transform:uppercase;
                    color:#6B6860;font-weight:600;margin-bottom:6px;">Detalle</div>
        <div style="font-size:0.92rem;color:#E8E4DC;line-height:1.6;">{detalle}</div>
    </div>
    <div style="background:#0A0A0F;border:1px solid #1E1E2A;border-radius:8px;
                padding:12px 16px;margin-bottom:24px;">
        <div style="font-size:0.72rem;color:#6B6860;line-height:1.5;">
            ⚠️ Este análisis es orientativo y se basa en estadísticas agregadas públicas.
            No constituye asesoramiento legal, financiero ni inmobiliario.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='font-size:0.7rem;letter-spacing:0.12em;text-transform:uppercase;color:#6B6860;margin-bottom:12px;'>Factores analizados</div>", unsafe_allow_html=True)
    for nombre, val in factores.items():
        pct = int(val * 100)
        bar_color = "#00C896" if val < 0.10 else "#F5A623" if val < 0.22 else "#FF6B35" if val < 0.40 else "#E53E3E"
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
            <div style="font-size:0.8rem;color:#9B9688;width:170px;flex-shrink:0;">{nombre}</div>
            <div style="flex:1;height:4px;background:#1E1E2A;border-radius:100px;overflow:hidden;">
                <div style="width:{pct}%;height:100%;background:{bar_color};border-radius:100px;"></div>
            </div>
            <div style="font-size:0.72rem;color:#6B6860;width:32px;text-align:right;">{pct}%</div>
        </div>
        """, unsafe_allow_html=True)

    # ── Email + PDF ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("""
    <div style="text-align:center;margin-bottom:16px;">
        <div style="font-family:'DM Serif Display',serif;font-size:1.3rem;color:#F0EDE6;margin-bottom:6px;">
            Descarga el informe en PDF
        </div>
        <div style="font-size:0.85rem;color:#9B9688;">
            Introduce tu email para descargar el informe completo
        </div>
    </div>
    """, unsafe_allow_html=True)

    email = st.text_input("Tu email", placeholder="propietario@ejemplo.com")
    acepta = st.checkbox("Acepto recibir comunicaciones de Predice_Impago. Puedo darme de baja cuando quiera.")

    if email and acepta:
        datos_lead = {
            "edad": edad, "contrato": contrato, "sector": sector,
            "ccaa": ccaa, "fuente": fuente, "impagos": impagos,
            "prob": round(prob*100),
            "ratio": round(alquiler/nomina*100) if nomina > 0 else 0
        }
        guardar_lead_local(email, datos_lead)
        enviar_formspree(email, datos_lead)

        pdf_buffer = generar_pdf(
            r["datos"], prob, factores, label, conclusion, detalle
        )
        st.download_button(
            label="⬇ Descargar informe PDF",
            data=pdf_buffer,
            file_name=f"predice_impago_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            mime="application/pdf"
        )

# ─── FOOTER ───────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("""
<div style="text-align:center;padding:1rem 0;">
    <p style="font-size:0.75rem;color:#3A3A45;line-height:1.6;">
        Predice_Impago · Modelo calibrado con datos INE 2023 y Banco de España.<br>
        Herramienta orientativa. No constituye asesoramiento legal ni financiero.<br>
        <a href="#" style="color:#6B6860;text-decoration:none;">Política de privacidad</a> ·
        <a href="#" style="color:#6B6860;text-decoration:none;">Aviso legal</a>
    </p>
</div>
""", unsafe_allow_html=True)
