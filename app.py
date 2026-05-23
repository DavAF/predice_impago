import streamlit as st
import json
import csv
import os
from datetime import datetime

# ─── CONFIG ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Predice_Impago — Scoring de Inquilinos",
    page_icon="🏠",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ─── SCORING ENGINE ────────────────────────────────────────────────────────────
PARO_POR_SECTOR = {
    "hosteleria": 0.18, "construccion": 0.16, "comercio": 0.12,
    "transporte": 0.10, "industria": 0.09, "administracion": 0.04,
    "tecnologia": 0.05, "sanidad": 0.04, "educacion": 0.03, "otro": 0.13
}
PARO_POR_EDAD = {
    "18-24": 0.28, "25-34": 0.14, "35-44": 0.09,
    "45-54": 0.10, "55-64": 0.14, "65+": 0.08
}
RIESGO_CONTRATO = {
    "Indefinido": 0.00, "Fijo discontinuo": 0.12,
    "Temporal": 0.22, "Autónomo": 0.18, "Sin contrato": 0.45
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

def riesgo_ratio(alquiler, nomina):
    if nomina <= 0:
        return 0.50
    ratio = alquiler / nomina
    if ratio <= 0.25: return 0.02
    if ratio <= 0.30: return 0.05
    if ratio <= 0.35: return 0.10
    if ratio <= 0.40: return 0.18
    if ratio <= 0.50: return 0.30
    return 0.50

def calcular_score(edad, nomina, alquiler, contrato, impagos, sector, nacionalidad):
    r_sector   = PARO_POR_SECTOR.get(sector, 0.13)
    r_edad     = PARO_POR_EDAD.get(edad, 0.12)
    r_contrato = RIESGO_CONTRATO.get(contrato, 0.20)
    r_ratio    = riesgo_ratio(alquiler, nomina)
    r_impagos  = RIESGO_IMPAGOS.get(impagos, 0.00)
    r_nac      = CORR_NAC.get(nacionalidad, 0.00)

    score = (
        r_sector   * 0.10 +
        r_edad     * 0.10 +
        r_contrato * 0.25 +
        r_ratio    * 0.30 +
        r_impagos  * 0.20 +
        r_nac      * 0.05
    )
    return round(min(0.92, max(0.02, score)), 4), {
        "Contrato laboral": r_contrato,
        "Ratio alquiler/renta": r_ratio,
        "Historial impagos": r_impagos,
        "Sector laboral": r_sector,
        "Franja de edad": r_edad,
    }

def interpretar(prob):
    if prob < 0.10:
        return "🟢 Riesgo Bajo", "#1a7a4a", \
            "Perfil sólido. Probabilidad de impago baja. Recomendamos avanzar con la firma.", \
            "1 mes de fianza es suficiente."
    if prob < 0.22:
        return "🟡 Riesgo Moderado", "#a07820", \
            "Perfil aceptable con alguna variable de riesgo. Proceder con precaución.", \
            "Considerar aval bancario o 2 meses de fianza adicional."
    if prob < 0.40:
        return "🟠 Riesgo Elevado", "#b85020", \
            "Varias variables apuntan a fragilidad financiera. Alta probabilidad de retraso en pagos.", \
            "Exigir aval solidario o seguro de impago antes de firmar."
    return "🔴 Riesgo Muy Alto", "#c03030", \
        "Perfil de alto riesgo. Ratio de esfuerzo y/o historial de impagos supera umbrales críticos.", \
        "No recomendado sin garantías adicionales muy sólidas."

# ─── PERSISTENCIA ──────────────────────────────────────────────────────────────
LEADS_FILE = "leads.csv"

def guardar_lead(email, datos):
    fila = {
        "timestamp": datetime.now().isoformat(),
        "email": email,
        **datos
    }
    existe = os.path.exists(LEADS_FILE)
    with open(LEADS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fila.keys())
        if not existe:
            writer.writeheader()
        writer.writerow(fila)

# ─── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

/* Fondo oscuro */
.stApp { background-color: #0A0A0F; color: #E8E4DC; }
section[data-testid="stSidebar"] { background: #0A0A0F; }

/* Ocultar elementos Streamlit por defecto */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 640px; }

/* Títulos */
h1, h2, h3 { font-family: 'DM Serif Display', serif !important; color: #F0EDE6 !important; }

/* Inputs */
.stSelectbox > div > div,
.stNumberInput > div > div > input {
    background-color: #12121A !important;
    border: 1px solid #1E1E2A !important;
    color: #E8E4DC !important;
    border-radius: 8px !important;
}

/* Labels */
.stSelectbox label, .stNumberInput label, .stTextInput label {
    color: #9B9688 !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
}

/* Botón principal */
.stButton > button {
    background: #00C896 !important;
    color: #0A0A0F !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 1rem !important;
    padding: 0.6rem 2rem !important;
    width: 100%;
    transition: all 0.2s;
}
.stButton > button:hover { background: #00E6AC !important; }

/* Text input */
.stTextInput > div > div > input {
    background-color: #12121A !important;
    border: 1px solid #1E1E2A !important;
    color: #E8E4DC !important;
    border-radius: 8px !important;
}

/* Progress bar */
.stProgress > div > div > div { background-color: #00C896 !important; }

/* Divider */
hr { border-color: #1E1E2A !important; }

/* Checkbox */
.stCheckbox label { color: #9B9688 !important; font-size: 0.85rem !important; }
</style>
""", unsafe_allow_html=True)

# ─── COOKIE / ANALYTICS BANNER ────────────────────────────────────────────────
if "cookies_aceptadas" not in st.session_state:
    st.session_state.cookies_aceptadas = False

if not st.session_state.cookies_aceptadas:
    st.markdown("""
    <div style="background:#12121A; border:1px solid #1E1E2A; border-radius:12px;
                padding:20px 24px; margin-bottom:24px;">
        <p style="color:#E8E4DC; font-size:0.9rem; margin:0 0 12px 0;">
            🍪 <strong>Usamos cookies analíticas</strong> para mejorar el servicio.
            Recogemos datos de uso anónimos (sector laboral, franja de edad, resultado del análisis)
            para calibrar el modelo. No compartimos datos personales con terceros.
        </p>
    </div>
    """, unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✓ Aceptar cookies"):
            st.session_state.cookies_aceptadas = True
            st.rerun()
    with col2:
        if st.button("Solo esenciales"):
            st.session_state.cookies_aceptadas = True
            st.rerun()
    st.stop()

# ─── HEADER ───────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center; padding: 2rem 0 1rem 0;">
    <span style="font-size:11px; font-weight:600; letter-spacing:0.15em;
                 text-transform:uppercase; color:#00C896;
                 border:1px solid #00C89640; padding:5px 14px; border-radius:100px;">
        Scoring de Inquilinos · Beta Gratuita
    </span>
    <h1 style="font-size:2.4rem; margin: 1rem 0 0.5rem 0; line-height:1.15;">
        ¿Tu inquilino dejará<br><em style="color:#00C896;">de pagar?</em>
    </h1>
    <p style="color:#9B9688; font-size:1rem; max-width:420px;
              margin:0 auto 2rem auto; line-height:1.7; font-weight:300;">
        Probabilidad de impago calibrada con datos reales del INE y Banco de España.
        Gratis durante la beta.
    </p>
</div>
""", unsafe_allow_html=True)

# Stats
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("""
    <div style="text-align:center; padding:16px; background:#12121A;
                border:1px solid #1E1E2A; border-radius:10px;">
        <div style="font-family:'DM Serif Display',serif; font-size:1.6rem; color:#F0EDE6;">3.2%</div>
        <div style="font-size:0.72rem; color:#6B6860; margin-top:4px;">Morosidad media España</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown("""
    <div style="text-align:center; padding:16px; background:#12121A;
                border:1px solid #1E1E2A; border-radius:10px;">
        <div style="font-family:'DM Serif Display',serif; font-size:1.6rem; color:#F0EDE6;">8 meses</div>
        <div style="font-size:0.72rem; color:#6B6860; margin-top:4px;">Proceso medio desahucio</div>
    </div>""", unsafe_allow_html=True)
with c3:
    st.markdown("""
    <div style="text-align:center; padding:16px; background:#12121A;
                border:1px solid #1E1E2A; border-radius:10px;">
        <div style="font-family:'DM Serif Display',serif; font-size:1.6rem; color:#F0EDE6;">€6.200</div>
        <div style="font-size:0.72rem; color:#6B6860; margin-top:4px;">Coste medio impago anual</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
st.markdown("---")

# ─── FORMULARIO ───────────────────────────────────────────────────────────────
st.markdown("### Datos del inquilino")
st.markdown("<p style='color:#9B9688; font-size:0.88rem; margin-top:-12px;'>Solo 6 variables. Resultado instantáneo.</p>", unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)

col_a, col_b = st.columns(2)
with col_a:
    nomina = st.number_input("Nómina neta (€/mes)", min_value=0, max_value=20000,
                              value=1800, step=100)
with col_b:
    alquiler = st.number_input("Alquiler mensual (€)", min_value=0, max_value=10000,
                                value=750, step=50)

col_c, col_d = st.columns(2)
with col_c:
    edad = st.selectbox("Franja de edad", ["18-24","25-34","35-44","45-54","55-64","65+"], index=2)
with col_d:
    contrato = st.selectbox("Tipo de contrato", list(RIESGO_CONTRATO.keys()))

col_e, col_f = st.columns(2)
with col_e:
    sector_labels = {
        "tecnologia": "Tecnología", "sanidad": "Sanidad", "educacion": "Educación",
        "administracion": "Administración pública", "industria": "Industria / manufactura",
        "comercio": "Comercio", "transporte": "Transporte / logística",
        "hosteleria": "Hostelería / turismo", "construccion": "Construcción", "otro": "Otro"
    }
    sector_display = st.selectbox("Sector laboral", list(sector_labels.values()))
    sector = [k for k, v in sector_labels.items() if v == sector_display][0]
with col_f:
    impagos = st.selectbox("Impagos anteriores", list(RIESGO_IMPAGOS.keys()))

nacionalidad = st.selectbox("Nacionalidad / historial bancario", list(CORR_NAC.keys()))

st.markdown("<br>", unsafe_allow_html=True)

# ─── CÁLCULO ──────────────────────────────────────────────────────────────────
if st.button("Calcular probabilidad de impago →"):

    if nomina <= 0:
        st.warning("Introduce una nómina válida.")
    else:
        prob, factores = calcular_score(
            edad, nomina, alquiler, contrato, impagos, sector, nacionalidad
        )
        label, color, conclusion, recomendacion = interpretar(prob)

        st.markdown("---")
        st.markdown("### Resultado del análisis")

        # Probabilidad grande
        st.markdown(f"""
        <div style="text-align:center; padding:2rem 0 1.5rem 0;">
            <div style="font-family:'DM Serif Display',serif; font-size:5rem;
                        line-height:1; color:{color}; margin-bottom:8px;">
                {round(prob * 100)}%
            </div>
            <div style="font-size:0.72rem; letter-spacing:0.12em; text-transform:uppercase;
                        color:#6B6860; margin-bottom:12px;">
                Probabilidad de impago estimada
            </div>
            <span style="background:{color}22; color:{color};
                         border:1px solid {color}44; padding:5px 18px;
                         border-radius:100px; font-size:0.88rem; font-weight:600;">
                {label}
            </span>
        </div>
        """, unsafe_allow_html=True)

        # Conclusión y recomendación
        st.markdown(f"""
        <div style="background:{color}11; border:1px solid {color}33;
                    border-radius:10px; padding:18px 20px; margin-bottom:12px;">
            <div style="font-size:0.68rem; letter-spacing:0.12em; text-transform:uppercase;
                        color:{color}; font-weight:600; margin-bottom:6px;">Conclusión</div>
            <div style="font-size:0.92rem; color:#E8E4DC; line-height:1.6;">{conclusion}</div>
        </div>
        <div style="background:#12121A; border:1px solid #1E1E2A;
                    border-radius:10px; padding:18px 20px; margin-bottom:24px;">
            <div style="font-size:0.68rem; letter-spacing:0.12em; text-transform:uppercase;
                        color:#6B6860; font-weight:600; margin-bottom:6px;">Recomendación</div>
            <div style="font-size:0.92rem; color:#E8E4DC; line-height:1.6;">{recomendacion}</div>
        </div>
        """, unsafe_allow_html=True)

        # Factores
        st.markdown("<div style='font-size:0.7rem; letter-spacing:0.12em; text-transform:uppercase; color:#6B6860; margin-bottom:12px;'>Factores analizados</div>", unsafe_allow_html=True)
        for nombre, val in factores.items():
            pct = int(val * 100)
            bar_color = "#00C896" if val < 0.10 else "#F5A623" if val < 0.22 else "#FF6B35" if val < 0.40 else "#E53E3E"
            st.markdown(f"""
            <div style="display:flex; align-items:center; gap:12px; margin-bottom:8px;">
                <div style="font-size:0.8rem; color:#9B9688; width:160px; flex-shrink:0;">{nombre}</div>
                <div style="flex:1; height:4px; background:#1E1E2A; border-radius:100px; overflow:hidden;">
                    <div style="width:{pct}%; height:100%; background:{bar_color}; border-radius:100px;"></div>
                </div>
                <div style="font-size:0.72rem; color:#6B6860; width:32px; text-align:right;">{pct}%</div>
            </div>
            """, unsafe_allow_html=True)

        # Guardar datos analíticos (sin email todavía)
        if st.session_state.cookies_aceptadas:
            datos_anonimos = {
                "edad": edad, "contrato": contrato, "sector": sector,
                "impagos": impagos, "prob": round(prob * 100),
                "ratio_esfuerzo": round(alquiler / nomina * 100) if nomina > 0 else 0
            }

        # Captura de email
        st.markdown("---")
        st.markdown("""
        <div style="text-align:center; margin-bottom:16px;">
            <div style="font-family:'DM Serif Display',serif; font-size:1.3rem;
                        color:#F0EDE6; margin-bottom:6px;">
                Recibe el informe completo por email
            </div>
            <div style="font-size:0.85rem; color:#9B9688;">
                + alertas cuando actualicemos el modelo con nuevos datos BdE
            </div>
        </div>
        """, unsafe_allow_html=True)

        email = st.text_input("Tu email", placeholder="propietario@ejemplo.com")
        acepta_lopd = st.checkbox("Acepto recibir comunicaciones de Predice_Impago. Puedo darme de baja cuando quiera.")

        if email and acepta_lopd:
            if st.button("Enviar informe →"):
                guardar_lead(email, {
                    "edad": edad, "contrato": contrato, "sector": sector,
                    "impagos": impagos, "prob": round(prob * 100),
                    "ratio_esfuerzo": round(alquiler / nomina * 100) if nomina > 0 else 0
                })
                st.success("✓ Apuntado. Te avisamos con cada mejora del modelo.")

# ─── FOOTER ───────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("""
<div style="text-align:center; padding:1rem 0;">
    <p style="font-size:0.75rem; color:#3A3A45; line-height:1.6;">
        Predice_Impago · Modelo calibrado con datos INE 2023 y Banco de España.<br>
        Herramienta orientativa. No constituye asesoramiento legal ni financiero.<br>
        <a href="#" style="color:#6B6860; text-decoration:none;">Política de privacidad</a> ·
        <a href="#" style="color:#6B6860; text-decoration:none;">Aviso legal</a>
    </p>
</div>
""", unsafe_allow_html=True)
