import streamlit as st
import csv
import os
import json
from datetime import datetime, timedelta
from collections import Counter

st.set_page_config(
    page_title="Predice_Impago · Admin",
    page_icon="🔒", layout="wide", initial_sidebar_state="collapsed"
)

# ─── CONTRASEÑA ───────────────────────────────────────────────────────────────
ADMIN_PASSWORD = "predice2026admin"  # ← cámbiala por la tuya

if "admin_ok" not in st.session_state:
    st.session_state.admin_ok = False

if not st.session_state.admin_ok:
    st.markdown("""
    <div style="max-width:360px;margin:15vh auto;text-align:center;">
        <div style="font-size:2rem;margin-bottom:8px;">🔒</div>
        <h2 style="font-family:serif;color:#0f172a;margin-bottom:24px;">Panel de administración</h2>
    </div>
    """, unsafe_allow_html=True)
    pwd = st.text_input("Contraseña", type="password", placeholder="••••••••")
    if st.button("Acceder"):
        if pwd == ADMIN_PASSWORD:
            st.session_state.admin_ok = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
    st.stop()

# ─── FICHEROS ─────────────────────────────────────────────────────────────────
TRACKER_FILE = "tracker.csv"
LEADS_FILE   = "leads.csv"

def leer_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

tracker = leer_csv(TRACKER_FILE)
leads   = leer_csv(LEADS_FILE)

# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif;}
.stApp{background:#F8FAFC;color:#1e293b;}
#MainMenu,footer,header{visibility:hidden;}
h1,h2,h3{font-family:'DM Serif Display',serif!important;color:#0f172a!important;}
hr{border-color:#E2E8F0!important;}
</style>
""", unsafe_allow_html=True)

# ─── HEADER ───────────────────────────────────────────────────────────────────
st.markdown("""
<div style="padding:1.5rem 0 1rem 0;border-bottom:1px solid #E2E8F0;margin-bottom:24px;">
    <span style="font-size:11px;font-weight:600;letter-spacing:0.15em;text-transform:uppercase;
                 color:#00C896;background:#f0fdf9;padding:4px 12px;border-radius:100px;">
        Panel privado
    </span>
    <h1 style="font-size:1.8rem;margin:8px 0 4px 0;">Predice_Impago · Analytics</h1>
    <p style="color:#94a3b8;font-size:0.85rem;">
        Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}
    </p>
</div>
""".format(datetime=datetime), unsafe_allow_html=True)

# ─── MÉTRICAS PRINCIPALES ─────────────────────────────────────────────────────
total_analisis  = len(tracker)
total_leads     = len(leads)
conversion      = round(total_leads / total_analisis * 100, 1) if total_analisis > 0 else 0
acepta_socios   = sum(1 for l in leads if str(l.get("acepta_socios","")).lower() == "true")

# Últimas 24h
ahora = datetime.now()
ayer  = ahora - timedelta(hours=24)
analisis_24h = sum(1 for t in tracker if t.get("timestamp","") > ayer.isoformat())
leads_24h    = sum(1 for l in leads   if l.get("timestamp","")  > ayer.isoformat())

c1,c2,c3,c4,c5,c6 = st.columns(6)
for col, val, lbl, color in [
    (c1, total_analisis,  "Análisis totales",    "#0f172a"),
    (c2, total_leads,     "Emails captados",     "#00C896"),
    (c3, f"{conversion}%","Conversión",          "#d97706"),
    (c4, acepta_socios,   "Acepta socios",       "#7c3aed"),
    (c5, analisis_24h,    "Análisis 24h",        "#0ea5e9"),
    (c6, leads_24h,       "Leads 24h",           "#16a34a"),
]:
    col.markdown(f"""
    <div style="background:white;border:1px solid #E2E8F0;border-radius:10px;padding:16px;
                box-shadow:0 1px 4px rgba(0,0,0,0.05);text-align:center;">
        <div style="font-family:'DM Serif Display',serif;font-size:1.8rem;
                    color:{color};font-weight:700;">{val}</div>
        <div style="font-size:0.72rem;color:#94a3b8;margin-top:4px;">{lbl}</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ─── GRÁFICOS ─────────────────────────────────────────────────────────────────
col_l, col_r = st.columns(2)

with col_l:
    st.markdown("#### Distribución de resultados")
    if tracker:
        resultados = Counter(t.get("resultado","") for t in tracker if t.get("resultado"))
        total_r = sum(resultados.values())
        colores_r = {
            "Riesgo Bajo": "#16a34a",
            "Riesgo Moderado": "#d97706",
            "Riesgo Elevado": "#ea580c",
            "Riesgo Muy Alto": "#dc2626"
        }
        for nivel in ["Riesgo Bajo","Riesgo Moderado","Riesgo Elevado","Riesgo Muy Alto"]:
            n = resultados.get(nivel, 0)
            pct = round(n/total_r*100) if total_r > 0 else 0
            col = colores_r[nivel]
            st.markdown(f"""
            <div style="margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                    <span style="font-size:0.82rem;color:#475569;">{nivel}</span>
                    <span style="font-size:0.82rem;color:{col};font-weight:600;">{n} ({pct}%)</span>
                </div>
                <div style="height:6px;background:#E2E8F0;border-radius:100px;">
                    <div style="width:{pct}%;height:100%;background:{col};border-radius:100px;"></div>
                </div>
            </div>""", unsafe_allow_html=True)
    else:
        st.info("Sin datos aún.")

with col_r:
    st.markdown("#### Top CCAA analizadas")
    if tracker:
        ccaas = Counter(t.get("ccaa","") for t in tracker if t.get("ccaa"))
        top_ccaa = ccaas.most_common(8)
        max_n = top_ccaa[0][1] if top_ccaa else 1
        for ccaa, n in top_ccaa:
            pct = round(n/max_n*100)
            st.markdown(f"""
            <div style="margin-bottom:8px;">
                <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                    <span style="font-size:0.82rem;color:#475569;">{ccaa}</span>
                    <span style="font-size:0.82rem;color:#0ea5e9;font-weight:600;">{n}</span>
                </div>
                <div style="height:5px;background:#E2E8F0;border-radius:100px;">
                    <div style="width:{pct}%;height:100%;background:#0ea5e9;border-radius:100px;"></div>
                </div>
            </div>""", unsafe_allow_html=True)
    else:
        st.info("Sin datos aún.")

st.markdown("<br>", unsafe_allow_html=True)
col_l2, col_r2 = st.columns(2)

with col_l2:
    st.markdown("#### Sectores laborales más analizados")
    if tracker:
        sectores = Counter(t.get("sector","") for t in tracker if t.get("sector"))
        top_s = sectores.most_common(6)
        max_s = top_s[0][1] if top_s else 1
        for sec, n in top_s:
            pct = round(n/max_s*100)
            st.markdown(f"""
            <div style="margin-bottom:8px;">
                <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                    <span style="font-size:0.82rem;color:#475569;">{sec}</span>
                    <span style="font-size:0.82rem;color:#7c3aed;font-weight:600;">{n}</span>
                </div>
                <div style="height:5px;background:#E2E8F0;border-radius:100px;">
                    <div style="width:{pct}%;height:100%;background:#7c3aed;border-radius:100px;"></div>
                </div>
            </div>""", unsafe_allow_html=True)
    else:
        st.info("Sin datos aún.")

with col_r2:
    st.markdown("#### Distribución ratio esfuerzo")
    if tracker:
        ratios = [int(t.get("ratio", 0)) for t in tracker if t.get("ratio")]
        buckets = {"≤25%": 0, "26-30%": 0, "31-35%": 0, "36-40%": 0, "41-50%": 0, ">50%": 0}
        for rv in ratios:
            if rv <= 25:   buckets["≤25%"] += 1
            elif rv <= 30: buckets["26-30%"] += 1
            elif rv <= 35: buckets["31-35%"] += 1
            elif rv <= 40: buckets["36-40%"] += 1
            elif rv <= 50: buckets["41-50%"] += 1
            else:          buckets[">50%"] += 1
        max_b = max(buckets.values()) if buckets else 1
        colores_b = {"≤25%":"#16a34a","26-30%":"#16a34a","31-35%":"#d97706",
                     "36-40%":"#ea580c","41-50%":"#dc2626",">50%":"#dc2626"}
        for rng, n in buckets.items():
            pct = round(n/max_b*100) if max_b > 0 else 0
            st.markdown(f"""
            <div style="margin-bottom:8px;">
                <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                    <span style="font-size:0.82rem;color:#475569;">{rng}</span>
                    <span style="font-size:0.82rem;color:{colores_b[rng]};font-weight:600;">{n}</span>
                </div>
                <div style="height:5px;background:#E2E8F0;border-radius:100px;">
                    <div style="width:{pct}%;height:100%;background:{colores_b[rng]};border-radius:100px;"></div>
                </div>
            </div>""", unsafe_allow_html=True)
    else:
        st.info("Sin datos aún.")

# ─── ACTIVIDAD RECIENTE ───────────────────────────────────────────────────────
st.markdown("---")
st.markdown("#### Últimos 20 análisis")
if tracker:
    recientes = sorted(tracker, key=lambda x: x.get("timestamp",""), reverse=True)[:20]
    for t in recientes:
        ts = t.get("timestamp","")[:16].replace("T"," ")
        res = t.get("resultado","—")
        ccaa = t.get("ccaa","—")
        ratio = t.get("ratio","—")
        sector = t.get("sector","—")
        prob = t.get("prob","—")
        col_res = {"Riesgo Bajo":"#16a34a","Riesgo Moderado":"#d97706",
                   "Riesgo Elevado":"#ea580c","Riesgo Muy Alto":"#dc2626"}.get(res,"#94a3b8")
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:12px;padding:8px 12px;
                    background:white;border:1px solid #E2E8F0;border-radius:8px;margin-bottom:6px;
                    font-size:0.8rem;">
            <span style="color:#94a3b8;min-width:110px;">{ts}</span>
            <span style="color:{col_res};font-weight:600;min-width:120px;">{res}</span>
            <span style="color:#0f172a;font-weight:700;min-width:40px;">{prob}%</span>
            <span style="color:#64748b;min-width:80px;">ratio {ratio}%</span>
            <span style="color:#64748b;min-width:160px;">{ccaa}</span>
            <span style="color:#94a3b8;">{sector}</span>
        </div>""", unsafe_allow_html=True)
else:
    st.info("Sin análisis registrados aún. Los datos aparecerán cuando alguien use la app.")

# ─── LEADS ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("#### Leads captados")
if leads:
    recientes_l = sorted(leads, key=lambda x: x.get("timestamp",""), reverse=True)[:30]
    for l in recientes_l:
        ts = l.get("timestamp","")[:16].replace("T"," ")
        email = l.get("email","—")
        prob  = l.get("prob","—")
        ccaa  = l.get("ccaa","—")
        socios = "✓ socios" if str(l.get("acepta_socios","")).lower()=="true" else ""
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:12px;padding:8px 12px;
                    background:white;border:1px solid #E2E8F0;border-radius:8px;margin-bottom:6px;
                    font-size:0.8rem;">
            <span style="color:#94a3b8;min-width:110px;">{ts}</span>
            <span style="color:#0f172a;font-weight:600;min-width:200px;">{email}</span>
            <span style="color:#64748b;min-width:50px;">{prob}%</span>
            <span style="color:#64748b;min-width:140px;">{ccaa}</span>
            <span style="color:#7c3aed;font-size:0.75rem;">{socios}</span>
        </div>""", unsafe_allow_html=True)
else:
    st.info("Sin leads aún.")

# ─── LOGOUT ───────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
if st.button("Cerrar sesión"):
    st.session_state.admin_ok = False
    st.rerun()
