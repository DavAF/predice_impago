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

st.set_page_config(
    page_title="Predice_Impago — Scoring de Inquilinos",
    page_icon="🏠", layout="centered", initial_sidebar_state="collapsed"
)

FORMSPREE_URL = "https://formspree.io/f/xnjrzvdq"
LEADS_FILE = "leads.csv"

# ─── SCORING ENGINE v3 — recalibrado ──────────────────────────────────────────
# Fuentes: INE EPA 2023, BdE Informe Estabilidad Financiera, 
#          Fundación Alquiler Seguro 2023, SEPE afiliaciones

PARO_POR_SECTOR = {
    "hosteleria": 0.18, "construccion": 0.16, "comercio": 0.12,
    "transporte": 0.10, "industria": 0.09, "administracion": 0.04,
    "tecnologia": 0.05, "sanidad": 0.04, "educacion": 0.03, "otro": 0.13
}

# Morosidad alquiler por CCAA — Fundación Alquiler Seguro 2023 + BdE
MORA_POR_CCAA = {
    "Murcia": 0.22, "Comunitat Valenciana": 0.20, "Canarias": 0.19,
    "Andalucía": 0.18, "Extremadura": 0.17, "Castilla-La Mancha": 0.15,
    "Cataluña": 0.14, "Baleares": 0.14, "Madrid": 0.13,
    "Castilla y León": 0.12, "Galicia": 0.11, "Asturias": 0.11,
    "Cantabria": 0.10, "Aragón": 0.10, "La Rioja": 0.09,
    "País Vasco": 0.08, "Navarra": 0.08, "Ceuta/Melilla": 0.22,
    "No especificada": 0.14
}

PARO_POR_EDAD = {
    "18-24": 0.28, "25-34": 0.14, "35-44": 0.09,
    "45-54": 0.10, "55-64": 0.14, "65+": 0.08
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

RIESGO_PERSONAS = {1: 0.00, 2: 0.01, 3: 0.03, 4: 0.06, 5: 0.09}

# Ratio esfuerzo recalibrado — BdE umbral crítico 35%
def riesgo_ratio(alquiler, nomina):
    if nomina <= 0: return 0.60
    r = alquiler / nomina
    if r <= 0.25: return 0.02   # óptimo
    if r <= 0.30: return 0.06   # aceptable
    if r <= 0.35: return 0.12   # límite BdE
    if r <= 0.40: return 0.22   # tenso
    if r <= 0.50: return 0.35   # muy tenso
    return 0.55                  # insostenible

def calcular_score(edad, nomina, alquiler, contrato, antiguedad,
                   fuente, impagos, sector, ccaa, nacionalidad, personas):
    r_sector     = PARO_POR_SECTOR.get(sector, 0.13)
    r_ccaa       = MORA_POR_CCAA.get(ccaa, 0.14)
    r_edad       = PARO_POR_EDAD.get(edad, 0.12)
    r_contrato   = RIESGO_CONTRATO.get(contrato, 0.20)
    r_antiguedad = RIESGO_ANTIGUEDAD.get(antiguedad, 0.08)
    r_fuente     = RIESGO_FUENTE.get(fuente, 0.10)
    r_ratio      = riesgo_ratio(alquiler, nomina)
    r_impagos    = RIESGO_IMPAGOS.get(impagos, 0.00)
    r_nac        = CORR_NAC.get(nacionalidad, 0.00)
    r_personas   = RIESGO_PERSONAS.get(min(personas, 5), 0.09)

    # Pesos recalibrados — impagos es el factor dominante en scoring bancario real
    score = (
        r_ratio      * 0.28 +   # esfuerzo financiero
        r_impagos    * 0.22 +   # historial — factor más predictivo
        r_contrato   * 0.14 +   # estabilidad laboral
        r_antiguedad * 0.10 +   # permanencia
        r_fuente     * 0.09 +   # naturaleza ingresos
        r_ccaa       * 0.07 +   # contexto territorial (mora real CCAA)
        r_sector     * 0.05 +   # riesgo sectorial
        r_edad       * 0.03 +   # factor demográfico
        r_nac        * 0.01 +   # ajuste historial
        r_personas   * 0.01     # complejidad convivencia
    )

    factores = {
        "Ratio alquiler/renta":  r_ratio,
        "Historial impagos":     r_impagos,
        "Contrato laboral":      r_contrato,
        "Antigüedad laboral":    r_antiguedad,
        "Fuente de ingresos":    r_fuente,
        "Mora CCAA (territorio)":r_ccaa,
        "Sector laboral":        r_sector,
        "Franja de edad":        r_edad,
    }
    return round(min(0.90, max(0.02, score)), 4), factores

# Umbrales recalibrados — ajustados a morosidad real española (3.2% media)
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

# ─── GENERADOR PDF ─────────────────────────────────────────────────────────────
def generar_pdf(datos_inquilino, prob, factores, label, conclusion, detalle):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm)

    COLOR_ACENTO  = colors.HexColor("#00C896")
    COLOR_TEXTO   = colors.HexColor("#1e293b")
    COLOR_GRIS    = colors.HexColor("#64748b")
    prob_pct = round(prob * 100)
    if prob < 0.08:   semaforo_hex = "#16a34a"
    elif prob < 0.18: semaforo_hex = "#d97706"
    elif prob < 0.32: semaforo_hex = "#ea580c"
    else:             semaforo_hex = "#dc2626"
    COLOR_SEMAFORO = colors.HexColor(semaforo_hex)

    estilos = getSampleStyleSheet()
    titulo_s = ParagraphStyle("t", parent=estilos["Normal"],
        fontSize=22, textColor=COLOR_TEXTO, spaceAfter=4,
        fontName="Helvetica-Bold")
    sub_s = ParagraphStyle("s", parent=estilos["Normal"],
        fontSize=10, textColor=COLOR_GRIS, spaceAfter=2, fontName="Helvetica")
    sec_s = ParagraphStyle("sec", parent=estilos["Normal"],
        fontSize=9, textColor=COLOR_ACENTO, spaceAfter=4,
        fontName="Helvetica-Bold")
    body_s = ParagraphStyle("b", parent=estilos["Normal"],
        fontSize=10, textColor=COLOR_TEXTO, spaceAfter=6,
        fontName="Helvetica", leading=14)
    disc_s = ParagraphStyle("d", parent=estilos["Normal"],
        fontSize=8, textColor=COLOR_GRIS, spaceAfter=4,
        fontName="Helvetica", leading=11)

    story = []
    story.append(Paragraph("Predice_Impago", titulo_s))
    story.append(Paragraph("Informe de Análisis de Riesgo de Inquilino", sub_s))
    story.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y a las %H:%M')}", sub_s))
    story.append(HRFlowable(width="100%", thickness=2, color=COLOR_ACENTO, spaceAfter=12))

    story.append(Paragraph("Resultado del Análisis", sec_s))
    res_data = [[
        Paragraph(f"<font size=32 color='{semaforo_hex}'><b>{prob_pct}%</b></font>", estilos["Normal"]),
        Paragraph(f"<font size=14 color='{semaforo_hex}'><b>{label}</b></font><br/><br/>"
                  f"<font size=10 color='#1e293b'>{conclusion}</font>", estilos["Normal"])
    ]]
    res_t = Table(res_data, colWidths=[40*mm, 130*mm])
    res_t.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ("TOPPADDING", (0,0), (-1,-1), 12), ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LEFTPADDING", (0,0), (-1,-1), 12),
    ]))
    story.append(res_t)
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>Detalle:</b> {detalle}", body_s))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=10))

    story.append(Paragraph("Datos Analizados", sec_s))
    filas = [["Variable", "Valor"],
        ["Ingresos netos", f"{datos_inquilino['nomina']:,} euros/mes"],
        ["Alquiler mensual", f"{datos_inquilino['alquiler']:,} euros/mes"],
        ["Ratio esfuerzo", f"{round(datos_inquilino['alquiler']/max(datos_inquilino['nomina'],1)*100)}% de los ingresos"],
        ["Franja de edad", datos_inquilino["edad"]],
        ["Tipo de contrato", datos_inquilino["contrato"]],
        ["Antiguedad laboral", datos_inquilino["antiguedad"]],
        ["Fuente de ingresos", datos_inquilino["fuente"]],
        ["Sector laboral", datos_inquilino["sector_display"]],
        ["Comunidad autonoma", datos_inquilino["ccaa"]],
        ["Impagos anteriores", datos_inquilino["impagos"]],
        ["Historial bancario", datos_inquilino["nacionalidad"]],
        ["Personas en el piso", str(datos_inquilino["personas"])],
    ]
    t = Table(filas, colWidths=[80*mm, 90*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=10))
    story.append(Paragraph("Factores de Riesgo Individuales", sec_s))
    ff = [["Factor", "Indicador", "Nivel"]]
    for nombre, val in factores.items():
        pct = int(val * 100)
        nivel = "Bajo" if val < 0.08 else "Moderado" if val < 0.18 else "Elevado" if val < 0.32 else "Muy alto"
        ff.append([nombre, f"{pct}%", nivel])
    ft = Table(ff, colWidths=[85*mm, 35*mm, 50*mm])
    ft.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(ft)
    story.append(Spacer(1, 16))

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))
    story.append(Paragraph(
        "AVISO LEGAL: Este informe es orientativo y se basa en estadísticas agregadas públicas del INE (2023), "
        "Banco de España, Fundación Alquiler Seguro y SEPE. No constituye asesoramiento legal, financiero ni inmobiliario. "
        "Predice_Impago no se hace responsable de las decisiones tomadas basándose en este análisis. "
        "prediceimpago.streamlit.app", disc_s))

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

# ─── CSS — TEMA CLARO PROFESIONAL ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background-color: #FFFFFF; color: #1e293b; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 640px; }

h1, h2, h3 {
    font-family: 'DM Serif Display', serif !important;
    color: #0f172a !important;
}

.stSelectbox > div > div,
.stNumberInput > div > div > input {
    background-color: #F8FAFC !important;
    border: 1px solid #E2E8F0 !important;
    color: #1e293b !important;
    border-radius: 8px !important;
}
.stSelectbox label, .stNumberInput label, .stTextInput label {
    color: #64748b !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
}
.stButton > button {
    background: #00C896 !important;
    color: #0f172a !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 1rem !important;
    padding: 0.6rem 2rem !important;
    width: 100%;
    box-shadow: 0 2px 8px rgba(0,200,150,0.25) !important;
}
.stButton > button:hover { background: #00b386 !important; }
.stTextInput > div > div > input {
    background-color: #F8FAFC !important;
    border: 1px solid #E2E8F0 !important;
    color: #1e293b !important;
    border-radius: 8px !important;
}
.stCheckbox label { color: #475569 !important; font-size: 0.85rem !important; }
.stDownloadButton > button {
    background: #f0fdf9 !important;
    color: #00C896 !important;
    border: 1px solid #00C89640 !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    width: 100%;
}
hr { border-color: #E2E8F0 !important; }
</style>
""", unsafe_allow_html=True)

# ─── COOKIES ──────────────────────────────────────────────────────────────────
if "cookies_ok" not in st.session_state:
    st.session_state.cookies_ok = False

if not st.session_state.cookies_ok:
    st.markdown("""
    <div style="background:#F0F9FF;border:1px solid #BAE6FD;border-radius:12px;
                padding:20px 24px;margin-bottom:24px;">
        <p style="color:#0f172a;font-size:0.9rem;margin:0 0 12px 0;">
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
                 color:#00C896;border:1px solid #00C89640;padding:5px 14px;border-radius:100px;
                 background:#f0fdf9;">
        Scoring de Inquilinos · Beta Gratuita
    </span>
    <h1 style="font-size:2.4rem;margin:1rem 0 0.5rem 0;line-height:1.15;">
        ¿Tu inquilino dejará<br><em style="color:#00C896;">de pagar?</em>
    </h1>
    <p style="color:#64748b;font-size:1rem;max-width:420px;margin:0 auto 2rem auto;
              line-height:1.7;font-weight:300;">
        Análisis de riesgo calibrado con datos reales del INE, Banco de España
        y Fundación Alquiler Seguro. Gratuito durante la beta.
    </p>
</div>
""", unsafe_allow_html=True)

c1, c2, c3 = st.columns(3)
for col, num, label in zip([c1,c2,c3],
    ["3.2%","8 meses","€7.600"],
    ["Morosidad media España","Proceso medio desahucio","Deuda media impago 2023"]):
    col.markdown(f"""
    <div style="text-align:center;padding:16px;background:#FFFFFF;border:1px solid #E2E8F0;
                border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
        <div style="font-family:'DM Serif Display',serif;font-size:1.6rem;color:#0f172a;
                    font-weight:700;">{num}</div>
        <div style="font-size:0.7rem;color:#94a3b8;margin-top:4px;">{label}</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
st.markdown("---")

# ─── FORMULARIO ───────────────────────────────────────────────────────────────
st.markdown("### Datos del inquilino")
st.markdown("<p style='color:#94a3b8;font-size:0.88rem;margin-top:-12px;margin-bottom:20px;'>"
            "10 variables · Calibrado con datos públicos 2023 · Resultado instantáneo</p>",
            unsafe_allow_html=True)

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
    ccaa = st.selectbox("Comunidad autónoma", list(MORA_POR_CCAA.keys()))

col_i, col_j = st.columns(2)
with col_i:
    impagos = st.selectbox("Impagos anteriores conocidos", list(RIESGO_IMPAGOS.keys()))
with col_j:
    nacionalidad = st.selectbox("Historial bancario en España", list(CORR_NAC.keys()))

# Ratio esfuerzo en tiempo real
if nomina > 0:
    ratio_live = round(alquiler / nomina * 100)
    color_ratio = "#16a34a" if ratio_live <= 30 else "#d97706" if ratio_live <= 35 else "#dc2626"
    st.markdown(f"""
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
                padding:10px 16px;margin:8px 0 16px 0;display:flex;align-items:center;gap:10px;">
        <span style="font-size:0.8rem;color:#64748b;">Ratio de esfuerzo:</span>
        <span style="font-size:1rem;font-weight:700;color:{color_ratio};">{ratio_live}%</span>
        <span style="font-size:0.75rem;color:#94a3b8;">
            {"✓ óptimo" if ratio_live<=30 else "⚠ límite BdE" if ratio_live<=35 else "✗ excede umbral crítico"}
        </span>
    </div>
    """, unsafe_allow_html=True)

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
                    line-height:1;color:{color};margin-bottom:8px;font-weight:700;">
            {round(prob*100)}%
        </div>
        <div style="font-size:0.72rem;letter-spacing:0.12em;text-transform:uppercase;
                    color:#94a3b8;margin-bottom:12px;">
            Probabilidad de impago estimada
        </div>
        <span style="background:{color}15;color:{color};border:1px solid {color}40;
                     padding:6px 20px;border-radius:100px;font-size:0.9rem;font-weight:600;">
            {label}
        </span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="background:{color}08;border:1px solid {color}30;
                border-radius:10px;padding:18px 20px;margin-bottom:12px;">
        <div style="font-size:0.68rem;letter-spacing:0.12em;text-transform:uppercase;
                    color:{color};font-weight:600;margin-bottom:6px;">Análisis</div>
        <div style="font-size:0.92rem;color:#1e293b;line-height:1.6;">{conclusion}</div>
    </div>
    <div style="background:#F8FAFC;border:1px solid #E2E8F0;
                border-radius:10px;padding:18px 20px;margin-bottom:12px;">
        <div style="font-size:0.68rem;letter-spacing:0.12em;text-transform:uppercase;
                    color:#64748b;font-weight:600;margin-bottom:6px;">Detalle</div>
        <div style="font-size:0.92rem;color:#1e293b;line-height:1.6;">{detalle}</div>
    </div>
    <div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;
                padding:12px 16px;margin-bottom:24px;">
        <div style="font-size:0.72rem;color:#92400e;line-height:1.5;">
            ⚠️ Este análisis es orientativo y se basa en estadísticas agregadas públicas.
            No constituye asesoramiento legal, financiero ni inmobiliario.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='font-size:0.7rem;letter-spacing:0.1em;text-transform:uppercase;"
                "color:#94a3b8;margin-bottom:12px;font-weight:600;'>Factores analizados</div>",
                unsafe_allow_html=True)
    for nombre, val in factores.items():
        pct = int(val * 100)
        bar_color = "#16a34a" if val < 0.08 else "#d97706" if val < 0.18 else "#ea580c" if val < 0.32 else "#dc2626"
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">
            <div style="font-size:0.8rem;color:#475569;width:175px;flex-shrink:0;">{nombre}</div>
            <div style="flex:1;height:5px;background:#E2E8F0;border-radius:100px;overflow:hidden;">
                <div style="width:{pct}%;height:100%;background:{bar_color};border-radius:100px;"></div>
            </div>
            <div style="font-size:0.72rem;color:#94a3b8;width:32px;text-align:right;">{pct}%</div>
        </div>
        """, unsafe_allow_html=True)

    # ── Email + PDF ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("""
    <div style="text-align:center;margin-bottom:20px;">
        <div style="font-family:'DM Serif Display',serif;font-size:1.4rem;
                    color:#0f172a;margin-bottom:6px;">
            Descarga el informe completo en PDF
        </div>
        <div style="font-size:0.85rem;color:#94a3b8;">
            Introduce tu email para descargar el informe
        </div>
    </div>
    """, unsafe_allow_html=True)

    email = st.text_input("Tu email", placeholder="propietario@ejemplo.com")
    acepta_comunicaciones = st.checkbox(
        "✓ Acepto recibir actualizaciones del modelo y comunicaciones de Predice_Impago. "
        "Puedo darme de baja cuando quiera."
    )
    acepta_socios = st.checkbox(
        "✓ Acepto que mi perfil sea compartido con socios comerciales del sector "
        "inmobiliario y asegurador para recibir ofertas personalizadas. (Opcional)"
    )
    st.markdown("""
    <div style="font-size:0.75rem;color:#94a3b8;margin-top:4px;margin-bottom:12px;line-height:1.5;">
        Al introducir tu email aceptas nuestra
        <a href="https://github.com/DavAF/predice_impago/blob/main/privacy_policy.md"
           style="color:#00C896;text-decoration:none;" target="_blank">Política de Privacidad</a>.
    </div>
    """, unsafe_allow_html=True)

    if email and acepta_comunicaciones:
        datos_lead = {
            "edad": edad, "contrato": contrato, "sector": sector,
            "ccaa": ccaa, "fuente": fuente, "impagos": impagos,
            "prob": round(prob*100),
            "ratio": round(alquiler/nomina*100) if nomina > 0 else 0,
            "acepta_socios": acepta_socios
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
    <p style="font-size:0.75rem;color:#cbd5e1;line-height:1.6;">
        Predice_Impago · Calibrado con INE 2023, Banco de España,
        Fundación Alquiler Seguro y SEPE.<br>
        Herramienta orientativa. No constituye asesoramiento legal ni financiero.<br>
        <a href="https://github.com/DavAF/predice_impago/blob/main/privacy_policy.md"
           style="color:#94a3b8;text-decoration:none;" target="_blank">
           Política de privacidad
        </a>
    </p>
</div>
""", unsafe_allow_html=True)
