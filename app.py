import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, storage
import pandas as pd
from datetime import datetime, timedelta
import time
import pytz

# ==========================================
# 0. CONFIGURACIÓN DE ZONA HORARIA
# ==========================================
# Definir la zona horaria a utilizar
ZONA_VNZ = pytz.timezone('America/Caracas')

def obtener_hora_actual():
    """Retorna la fecha y hora exacta localizada"""
    return datetime.now(ZONA_VNZ)

# ==========================================
# 1. CONFIGURACIÓN DE LA PÁGINA 
# ==========================================
st.set_page_config(page_title="Recepción Almacén", page_icon="📦", layout="wide")

# Ocultar la barra de guardado por defecto de Streamlit e inyectar bordes oscuros en componentes
st.markdown("""
    <style>
    button[data-testid="stFormSubmitButton"] {
        box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.1);
    }
    /* Remarcar el contenedor del buscador y selectores con bordes más oscuros */
    input, select, textarea {
        border: 1px solid #111111 !important;
    }
    /* Borde negro exterior acentuado para resaltar firmemente el contenedor de la tabla */
    [data-testid="stDataFrame"] {
        border: 2px solid #000000 !important;
        border-radius: 6px;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. CONEXIÓN A FIREBASE Y BUCKET DE LOGO
# ==========================================
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        # Extraemos las credenciales de los secretos de Streamlit
        firebase_creds = dict(st.secrets["firebase"])
        
        # Streamlit a veces desconfigura los saltos de línea de la clave privada, esto lo repara:
        if "private_key" in firebase_creds:
            firebase_creds["private_key"] = firebase_creds["private_key"].replace("\\n", "\n")

        cred = credentials.Certificate(firebase_creds)
        
        # Conectamos con el bucket oficial de tu Firebase
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'gestor-de-pedidos-52c82.firebasestorage.app'
        })
    return firestore.client(), storage.bucket()

db, bucket = init_firebase()

@st.cache_data(ttl=3600)
def obtener_url_logo():
    """Busca dinámicamente el logo de NY COMPRAS en Firebase Storage"""
    try:
        blob = bucket.blob("LOGO NY-COMPRAS SIN FONDO.png")
        if blob.exists():
            return blob.generate_signed_url(version="v4", expiration=timedelta(days=7))
    except:
        pass
    return "https://cdn-icons-png.flaticon.com/512/859/859272.png"

logo_url = obtener_url_logo()

# ==========================================
# 3. LOGIN INTELIGENTE (Sesión por 7 días)
# ==========================================
if "logged_in" not in st.session_state:
    params = st.query_params
    # Revisamos si hay una sesión guardada y si aún es válida (menos de 7 días)
    if "perfil" in params and "auth" in params and params["auth"] == "true" and "expira" in params:
        try:
            fecha_expira = datetime.strptime(params["expira"], "%Y-%m-%d").date()
            # MODIFICADO: Usar hora localizada
            if obtener_hora_actual().date() <= fecha_expira:
                st.session_state.logged_in = True
                st.session_state.perfil = params["perfil"]
            else:
                st.query_params.clear()
                st.session_state.logged_in = False
        except:
            st.session_state.logged_in = False
    else:
        st.session_state.logged_in = False

if not st.session_state.logged_in:
    # --- LOGO CENTRADO Y MUCHO MÁS GRANDE EN EL INICIO ---
    st.markdown(f"""
        <div style="display: flex; justify-content: center; align-items: center; margin-bottom: 10px; margin-top: 20px;">
            <img src="{logo_url}" width="300">
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("<h2 style='text-align: center; margin-top: 0px;'>🔐 Acceso de Deposito  (NY-COMPRAS)</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #7f8c8d; margin-top: -10px;'>Selecciona la Usuario</p>", unsafe_allow_html=True)
    
    docs = db.collection('perfiles_cloud').stream()
    perfiles = {doc.id: doc.to_dict() for doc in docs}
    
    if not perfiles:
        st.warning("No hay perfiles configurados en la nube.")
        st.stop()
        
    perfil_sel = st.selectbox("🏢 Seleccione (Usuario)", list(perfiles.keys()))
    password = st.text_input("🔑 Contraseña ", type="password")
    
    if st.button("Ingresar al Sistema", use_container_width=True):
        rif_real = perfiles[perfil_sel].get('rif', '').strip()
        if password.strip() == rif_real and rif_real != "":
            st.session_state.logged_in = True
            st.session_state.perfil = perfil_sel
            
            # Guardamos la sesión en el navegador por 7 días
            # MODIFICADO: Usar hora localizada para calcular la expiración
            fecha_limite = (obtener_hora_actual() + timedelta(days=7)).strftime("%Y-%m-%d")
            st.query_params["perfil"] = perfil_sel
            st.query_params["auth"] = "true"
            st.query_params["expira"] = fecha_limite
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
    st.stop()

# ==========================================
# 4. FUNCIONES LOGÍSTICAS
# ==========================================
def calcular_semaforo(fecha_str, estado, dias_conf):
    try:
        fecha_corta = fecha_str.split(" ")[0]
        fecha_pedido = datetime.strptime(fecha_corta, "%d-%m-%Y").date()
        # MODIFICADO: Usar hora localizada para calcular los días transcurridos
        hoy = obtener_hora_actual().date()
        dias_transcurridos = (hoy - fecha_pedido).days
    except:
        dias_transcurridos = 0

    if estado == "COMPLETADO": return "✔️ COMPLETADO", dias_transcurridos
    elif estado == "PARCIAL": return "⚠️ INCOMPLETO", dias_transcurridos

    if dias_conf <= 0: dias_conf = 1
    pct = dias_transcurridos / dias_conf

    if pct < 0.60: return "🟢 VERDE", dias_transcurridos
    elif pct < 0.90: return "🟡 ALERTA", dias_transcurridos
    else: return "🔴 RETRASADO", dias_transcurridos

def color_filas(row):
    # Retornamos los colores de fondo sólidos para mantener un contraste óptimo en el motor de canvas
    if "RETRASADO" in row['STATUS']: return ['background-color: #c0392b; color: white'] * len(row)
    elif "ALERTA" in row['STATUS']: return ['background-color: #f1c40f; color: black'] * len(row)
    elif "VERDE" in row['STATUS']: return ['background-color: #27ae60; color: white'] * len(row)
    elif "INCOMPLETO" in row['STATUS']: return ['background-color: #d35400; color: white'] * len(row)
    elif "COMPLETADO" in row['STATUS']: return ['background-color: #2980b9; color: white'] * len(row)
    return [''] * len(row)

# ==========================================
# 5. VENTANA EMERGENTE DE RECEPCIÓN 
# ==========================================
@st.dialog("📋 PANEL DE RECEPCIÓN")
def abrir_panel_recepcion(pedido_id, doc_data):
    proveedor = doc_data.get('proveedor', 'Desconocido')
    laboratorio = doc_data.get('laboratorio', 'Desconocido')
    
    st.write(f"**ID de Pedido:** {pedido_id}")
    st.write(f"**Proveedor:** {proveedor} | **Laboratorio:** {laboratorio}")
    
    url_pdf = doc_data.get('url_pdf')
    if url_pdf:
        st.markdown(f"**📄 [Descargar Orden de Compra (PDF)]({url_pdf})**")
        
    st.write("---")
    st.info("💡 Consejo: Al cambiar una cantidad, puedes presionar Enter, hacer clic afuera o pasar a la siguiente casilla. Todo se guarda automáticamente en memoria antes de enviar.")
    
    detalles = doc_data.get('detalles', [])
    estado_actual = doc_data.get('estado', 'EN CAMINO')
    
    nuevos_detalles = []
    incompleto = False
    
    for det in detalles:
        cod = det.get('codigo', '')
        desc = det.get('descripcion', '')
        pedida = int(det.get('cant_pedida', 0))
        recibida_db = int(det.get('cant_recibida', 0))
        cant_inicial = pedida if estado_actual == "EN CAMINO" else recibida_db
        
        st.write(f"**{cod}** - {desc[:50]}...")
        cols_art = st.columns([1, 1])
        cols_art[0].metric("Pedida", pedida)
        
        llegada = cols_art[1].number_input(
            f"Llegó ({cod})", 
            min_value=0, 
            max_value=pedida, 
            value=cant_inicial, 
            key=f"val_{pedido_id}_{cod}",
            label_visibility="collapsed"
        )
        st.divider()
        
        if llegada < pedida:
            incompleto = True
            
        nuevos_detalles.append({
            'codigo': cod, 'descripcion': desc,
            'cant_pedida': pedida, 'cant_recibida': llegada
        })
    
    if f"confirmar_{pedido_id}" not in st.session_state:
        st.session_state[f"confirmar_{pedido_id}"] = False

    if not st.session_state[f"confirmar_{pedido_id}"]:
        if st.button("💾 GUARDAR RECEPCIÓN", use_container_width=True, type="primary"):
            st.session_state[f"confirmar_{pedido_id}"] = True
            st.rerun()
    else:
        st.warning(f"⚠️ **¿ESTÁS SEGURO DE RECEPCIONAR?**\n\nVa a procesar el pedido **{pedido_id}** del proveedor **{proveedor}**.")
        
        # --- LÓGICA PARA MARCAR FALTANTES EN ROJO ---
        hay_diferencias = False
        for det in nuevos_detalles:
            if det['cant_recibida'] < det['cant_pedida']:
                falta = det['cant_pedida'] - det['cant_recibida']
                st.markdown(f"<div style='color: #ff4b4b; font-weight: bold; margin-bottom: 5px;'>❌ FALTAN {falta} unds de: {det['codigo']} - {det['descripcion'][:40]}...</div>", unsafe_allow_html=True)
                hay_diferencias = True
        
        if hay_diferencias:
            st.write("---") # Línea divisora si hubo errores
        # --------------------------------------------
        
        cols_conf = st.columns([1, 1])
        
        if cols_conf[0].button("❌ Cancelar", use_container_width=True):
            st.session_state[f"confirmar_{pedido_id}"] = False
            st.rerun()
            
        if cols_conf[1].button("✔️ Sí, Confirmar Recepción", use_container_width=True, type="primary"):
            nuevo_estado = "PARCIAL" if incompleto else "COMPLETADO"
            db.collection('pedidos_track').document(pedido_id).update({
                'estado': nuevo_estado,
                'detalles': nuevos_detalles
            })
            st.success(f"¡Pedido {pedido_id} guardado con éxito como {nuevo_estado}!")
            st.session_state[f"confirmar_{pedido_id}"] = False
            time.sleep(1)
            st.rerun()

# ==========================================
# 6. PANEL PRINCIPAL 
# ==========================================
cols_header = st.columns([3, 1])

with cols_header[0]:
    # --- LOGO ALINEADO AL LADO DEL PERFIL EN EL PANEL ---
    st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 10px;">
            <img src="{logo_url}" width="75">
            <h1 style="margin: 0; padding: 0;">📦 Recepción - {st.session_state.perfil}</h1>
        </div>
    """, unsafe_allow_html=True)

if cols_header[1].button("Cerrar Sesión", use_container_width=True):
    st.session_state.logged_in = False
    st.query_params.clear() 
    st.rerun()

st.write("---")

# FILTROS Y BÚSQUEDA 
st.write("🔍 **Buscador de Seguimientos**")
cols_acciones = st.columns([3, 1])
buscador = cols_acciones[0].text_input("Ingresa ID, Laboratorio o Proveedor...", label_visibility="collapsed", placeholder="Escribe aquí para buscar...")
bot_buscar = cols_acciones[1].button("🔍 BUSCAR", use_container_width=True)

st.write(" ")
filtro_estado = st.radio(
    "📌 Filtrar Tabla por Estado:",
    ["EN CAMINO", "PARCIAL", "COMPLETADO", "TODOS"],
    index=0, 
    horizontal=True
)

dias_docs = db.collection('prov_dias').stream()
dict_dias = {d.id: d.to_dict().get('dias_estimados', 3) for d in dias_docs}

if filtro_estado == "TODOS":
    pedidos_docs = db.collection('pedidos_track').where('perfil', '==', st.session_state.perfil).stream()
else:
    pedidos_docs = db.collection('pedidos_track').where('perfil', '==', st.session_state.perfil).where('estado', '==', filtro_estado).stream()

lista_procesada = []
pedidos_raw = {}

for doc in pedidos_docs:
    d = doc.to_dict()
    id_t = d.get('id_tracking')
    prov = d.get('proveedor', '')
    lab = d.get('laboratorio', '')
    est = d.get('estado', '')
    f_str = d.get('fecha_str', '')
    url_pdf = d.get('url_pdf', None)
    
    pedidos_raw[id_t] = d 
    
    dias_conf = dict_dias.get(prov, 3)
    semaforo, dias = calcular_semaforo(f_str, est, dias_conf)
    
    if "RETRASADO" in semaforo: p = 1
    elif "ALERTA" in semaforo: p = 2
    elif "INCOMPLETO" in semaforo: p = 3
    else: p = 4
    
    lista_procesada.append({
        'Prioridad': p, 'STATUS': semaforo, 'ID': id_t, 
        'DÍAS': dias, 'FECHA': f_str, 'LABORATORIO': lab, 'PROVEEDOR': prov,
        'ORDEN (PDF)': url_pdf
    })

st.write("👆 **Toca o haz clic sobre cualquier fila para abrir la recepción**")

if lista_procesada:
    df = pd.DataFrame(lista_procesada)
    df = df.sort_values(by=['Prioridad', 'ID'])
    
    if buscador:
        df = df[df.astype(str).apply(lambda x: x.str.contains(buscador, case=False, na=False)).any(axis=1)]
    
    if not df.empty:
        df = df.drop(columns=['Prioridad'])
        df_styled = df.style.apply(color_filas, axis=1)
        
        # --- SOLUCIÓN DE CENTRADO NATIVO ESTRICTO ---
        # Configuramos la alineación directamente en las especificaciones de la tabla
        column_config = {
            "STATUS": st.column_config.Column(alignment="center"),
            "DÍAS": st.column_config.Column(alignment="center"),
            "LABORATORIO": st.column_config.Column(alignment="center"),
            "FECHA": st.column_config.Column(alignment="center"),
            "ORDEN (PDF)": st.column_config.LinkColumn(
                "📄 PDF",
                display_text="📥 Descargar"
            )
        }
        
        event = st.dataframe(
            df_styled, 
            use_container_width=True, 
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config=column_config
        )
        
        if event and len(event.selection.rows) > 0:
            row_idx = event.selection.rows[0]
            id_seleccionado = df.iloc[row_idx]['ID']
            abrir_panel_recepcion(id_seleccionado, pedidos_raw[id_seleccionado])
    else:
        st.warning("No se encontraron resultados en la búsqueda.")
else:
    st.success(f"No hay pedidos con el estado '{filtro_estado}'.")
