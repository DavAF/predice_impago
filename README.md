# Predice_Impago 🏠

Herramienta de scoring de inquilinos calibrada con datos INE y Banco de España.

## Deploy en Streamlit Cloud (5 minutos)

1. Sube esta carpeta a un repo de GitHub (ej: `DavAF/predice_impago`)
2. Ve a [share.streamlit.io](https://share.streamlit.io)
3. Conecta el repo → selecciona `app.py` → Deploy

## Estructura
```
predice_impago/
├── app.py            # App principal
├── requirements.txt  # Solo streamlit
└── leads.csv         # Se genera automáticamente con cada email capturado
```

## Datos que capturamos (con consentimiento)
- Email del propietario
- Perfil anónimo del análisis (edad, sector, contrato, resultado)
- Timestamp

## Modelo
Scoring aditivo ponderado calibrado con:
- INE: tasa de paro por sector y franja de edad (2023)
- Banco de España: morosidad por segmento de crédito
- Regla bancaria estándar: ratio esfuerzo alquiler/ingresos

## Roadmap
- [ ] Integración Stripe (€4.99/análisis)
- [ ] Panel propietario con historial
- [ ] API para aseguradoras
- [ ] Modelo ML cuando tengamos 500+ casos reales
