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
ZONA_VNZ = pytz.timezone('America/Caracas')

def obtener_hora_actual():
    return datetime.now(ZONA_VNZ)

# ==========================================
# 1. CONFIGURACIÓN DE LA PÁGINA 
# ==========================================
st.set_page_config(page_title="Recepción Almacén", page_icon="📦", layout="wide")

st.markdown("""
    <style>
    /* 1. Ocultar el menú superior (GitHub y opciones de Streamlit) */
    [data-testid="stToolbar"] {
        visibility: hidden !important;
    }
    
    /* 2. Ocultar la marca de agua inferior (Made with Streamlit) */
    footer {
        visibility: hidden !important;
    }

    /* 3. Tus estilos originales intactos */
    button[data-testid="stFormSubmitButton"] {
        box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.1);
    }
    input, select, textarea {
        border: 1px solid #111111 !important;
    }
    [data-testid="stDataFrame"] {
        border: 2px solid #000000 !important;
        border-radius: 6px;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. CONEXIÓN A FIREBASE Y BUCKET DE LOGO/FONDO
# ==========================================
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        firebase_creds = dict(st.secrets["firebase"])
        if "private_key" in firebase_creds:
            firebase_creds["private_key"] = firebase_creds["private_key"].replace("\\n", "\n")

        cred = credentials.Certificate(firebase_creds)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'gestor-de-pedidos-52c82.firebasestorage.app'
        })
    return firestore.client(), storage.bucket()

db, bucket = init_firebase()

@st.cache_data(ttl=3600)
def obtener_url_logo():
    try:
        blob = bucket.blob("LOGO NY-COMPRAS SIN FONDO.png")
        if blob.exists():
            return blob.generate_signed_url(version="v4", expiration=timedelta(days=7))
    except:
        pass
    return "https://cdn-icons-png.flaticon.com/512/859/859272.png"

logo_url = obtener_url_logo()

# Función para extraer el fondo desde Firebase
@st.cache_data(ttl=3600)
def obtener_url_fondo():
    try:
        # ¡Aquí está el cambio clave! De .jpg a .png
        blob = bucket.blob("FONDO WEB ALMACEN.png") 
        if blob.exists():
            return blob.generate_signed_url(version="v4", expiration=timedelta(days=7))
    except:
        pass
    return ""

fondo_url = obtener_url_fondo()

# ==========================================
# 3. LOGIN INTELIGENTE
# ==========================================
if "logged_in" not in st.session_state:
    params = st.query_params
    if "perfil" in params and "auth" in params and params["auth"] == "true" and "expira" in params:
        try:
            fecha_expira = datetime.strptime(params["expira"], "%Y-%m-%d").date()
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
    
    # CSS inyectado SOLO en el login con transparencia uniforme
    if fondo_url:
        st.markdown(f"""
            <style>
            /* Capa uniforme semi-transparente (0.65) sobre la imagen */
            .stApp {{
                background-image: linear-gradient(rgba(255, 255, 255, 0.65), rgba(255, 255, 255, 0.65)), url("{fondo_url}");
                background-size: cover;
                background-position: center;
                background-repeat: no-repeat;
                background-attachment: fixed;
            }}
            
            /* Inputs de color blanco sólido para que resalten sobre la foto */
            div[data-baseweb="select"] > div, div.stTextInput > div > div {{
                background-color: #ffffff !important;
                border: 1px solid #cccccc !important;
            }}
            </style>
        """, unsafe_allow_html=True)

    st.markdown(f"""
        <div style="display: flex; justify-content: center; align-items: center; margin-bottom: 10px; margin-top: 20px;">
            <img src="{logo_url}" width="300">
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("<h2 style='text-align: center; margin-top: 0px;'>🔐 Acceso de Deposito (NY-COMPRAS)</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #555555; margin-top: -10px; font-weight: bold;'>Selecciona la Usuario</p>", unsafe_allow_html=True)
    
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

def calcular_dias_habiles(fecha_inicio, fecha_fin):
    """Calcula los días transcurridos omitiendo Sábado (5) y Domingo (6)"""
    dias_habiles = 0
    dia_actual = fecha_inicio
    while dia_actual < fecha_fin:
        dia_actual += timedelta(days=1)
        if dia_actual.weekday() < 5: 
            dias_habiles += 1
    return dias_habiles

def calcular_semaforo(fecha_str, estado, dias_conf):
    try:
        fecha_corta = fecha_str.split(" ")[0]
        fecha_pedido = datetime.strptime(fecha_corta, "%d-%m-%Y").date()
        hoy = obtener_hora_actual().date()
        
        # AQUÍ APLICAMOS LA NUEVA LÓGICA DE DÍAS HÁBILES
        dias_transcurridos = calcular_dias_habiles(fecha_pedido, hoy)
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
    st.info("💡 Consejo: Escribe el símbolo de PUNTO ( . ) para marcar el producto como devuelto por FECHA PRÓXIMA.")
    
    detalles = doc_data.get('detalles', [])
    estado_actual = doc_data.get('estado', 'EN CAMINO')
    
    nuevos_detalles = []
    incompleto = False
    
    for det in detalles:
        cod = det.get('codigo', '')
        desc = det.get('descripcion', '')
        pedida = int(det.get('cant_pedida', 0))
        recibida_db = int(det.get('cant_recibida', 0))
        nota_db = det.get('nota', '')
        
        cant_inicial = pedida if estado_actual == "EN CAMINO" else recibida_db
        val_inicial = "." if nota_db == "fecha_proxima" else str(cant_inicial)
        
        st.write(f"**{cod}** - {desc[:50]}...")
        cols_art = st.columns([1, 1])
        cols_art[0].metric("Pedida", pedida)
        
        llegada_str = cols_art[1].text_input(
            f"Llegó ({cod})", 
            value=val_inicial, 
            key=f"val_{pedido_id}_{cod}",
            label_visibility="collapsed"
        )
        st.divider()
        
        llegada_str = llegada_str.strip()
        nota_actual = ""
        
        if llegada_str == ".":
            llegada = 0
            incompleto = True
            nota_actual = "fecha_proxima"
        else:
            try:
                llegada = int(llegada_str)
            except:
                llegada = 0
            if llegada < pedida:
                incompleto = True
            
        nuevos_detalles.append({
            'codigo': cod, 'descripcion': desc,
            'cant_pedida': pedida, 'cant_recibida': llegada,
            'nota': nota_actual
        })
    
    if f"confirmar_{pedido_id}" not in st.session_state:
        st.session_state[f"confirmar_{pedido_id}"] = False

    if not st.session_state[f"confirmar_{pedido_id}"]:
        if st.button("💾 GUARDAR RECEPCIÓN", use_container_width=True, type="primary"):
            st.session_state[f"confirmar_{pedido_id}"] = True
            st.rerun()
    else:
        st.warning(f"⚠️ **¿ESTÁS SEGURO DE RECEPCIONAR?**\n\nVa a procesar el pedido **{pedido_id}** del proveedor **{proveedor}**.")
        
        hay_diferencias = False
        for det in nuevos_detalles:
            if det.get('nota') == "fecha_proxima":
                st.markdown(f"<div style='color: #e67e22; font-weight: bold; margin-bottom: 5px;'>📅 DEVUELTO (FECHA PRÓXIMA): {det['codigo']} - {det['descripcion'][:40]}...</div>", unsafe_allow_html=True)
                hay_diferencias = True
            elif det['cant_recibida'] < det['cant_pedida']:
                falta = det['cant_pedida'] - det['cant_recibida']
                st.markdown(f"<div style='color: #ff4b4b; font-weight: bold; margin-bottom: 5px;'>❌ FALTAN {falta} unds de: {det['codigo']} - {det['descripcion'][:40]}...</div>", unsafe_allow_html=True)
                hay_diferencias = True
        
        if hay_diferencias:
            st.write("---") 

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
            st.success(f"¡Pedido {pedido_id} guardado con éxito!")
            st.session_state[f"confirmar_{pedido_id}"] = False
            time.sleep(1)
            
            # REEMPLAZO QUIRÚRGICO: Solo borra la caché de pedidos activos de esta sede.
            # Deja intactos los logos, estilos y la lista de días de proveedores.
            obtener_pedidos_activos.clear()
            obtener_pedidos_completados.clear()
            
            st.rerun()

# ==========================================
# 6. PANEL PRINCIPAL 
# ==========================================
cols_header = st.columns([3, 1])

with cols_header[0]:
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

# =========================================================================
# COMPORTAMIENTO ULTRA-ESCALABLE (FILTRADO EN SERVIDOR)
# =========================================================================

@st.cache_data(ttl=120)
def obtener_pedidos_activos(perfil_usuario):
    """Descarga EXCLUSIVAMENTE lo pendiente. Si hay 10,000 completados, Firebase los ignora."""
    # NOTA: Esta consulta requiere un índice compuesto en la consola de Firebase.
    docs = db.collection('pedidos_track')\
             .where('perfil', '==', perfil_usuario)\
             .where('estado', 'in', ['EN CAMINO', 'PARCIAL'])\
             .stream()
    return [doc.to_dict() for doc in docs]

@st.cache_data(ttl=300)
def obtener_pedidos_completados(perfil_usuario, limite=50):
    """Solo descarga el historial viejo si el usuario lo solicita, limitado a los últimos registros."""
    docs = db.collection('pedidos_track')\
             .where('perfil', '==', perfil_usuario)\
             .where('estado', '==', 'COMPLETADO')\
             .limit(limite)\
             .stream()
    return [doc.to_dict() for doc in docs]

@st.cache_data(ttl=600)
def obtener_dias_proveedores():
    """Esta caché ya no se destruirá cuando se reciba un pedido"""
    dias_docs = db.collection('prov_dias').stream()
    return {d.id: d.to_dict().get('dias_estimados', 3) for d in dias_docs}


# --- INTERFAZ DE FILTROS ---
# 1. Cargamos el paquete de pedidos activos a la memoria de la web
pedidos_activos_memoria = obtener_pedidos_activos(st.session_state.perfil)
dict_dias = obtener_dias_proveedores()

# 2. Contamos usando Python (Costo Firebase $0)
contador_camino = sum(1 for p in pedidos_activos_memoria if p.get('estado') == 'EN CAMINO')
opcion_camino = f"EN CAMINO ({contador_camino})"

filtro_seleccionado = st.radio(
    "📌 Filtrar Tabla por Estado:",
    [opcion_camino, "PARCIAL", "COMPLETADO (Historial)"],
    index=0, 
    horizontal=True
)

# 3. Lógica de separación ultra-eficiente
if filtro_seleccionado == opcion_camino:
    # Filtramos la memoria local (Costo $0)
    pedidos_filtrados = [p for p in pedidos_activos_memoria if p.get('estado') == 'EN CAMINO']
    
elif filtro_seleccionado == "PARCIAL":
    # Filtramos la memoria local (Costo $0)
    pedidos_filtrados = [p for p in pedidos_activos_memoria if p.get('estado') == 'PARCIAL']
    
else:
    # Solo descarga el historial si hacen clic explícitamente en "COMPLETADO"
    pedidos_filtrados = obtener_pedidos_completados(st.session_state.perfil, limite=50)

lista_procesada = []
pedidos_raw = {}
dias_semana = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]

# 3. Procesamos los datos en memoria (Ahora el universo de datos es diminuto)
for d in pedidos_filtrados:
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
    
    try:
        dt = datetime.strptime(f_str, "%d-%m-%Y %I:%M %p")
        fecha_formateada = f"{dt.strftime('%d-%m')}   {dt.strftime('%I:%M %p')}  ({dias_semana[dt.weekday()]})"
    except: 
        fecha_formateada = f_str
        
    lista_procesada.append({
        'Prioridad': p, 'STATUS': semaforo, 'ID': id_t, 
        'DÍAS': dias, 'FECHA': fecha_formateada, 'LABORATORIO': lab, 'PROVEEDOR': prov,
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
        
        # Proteger PDFs nulos para que no den error
        df['ORDEN (PDF)'] = df['ORDEN (PDF)'].apply(lambda x: x if pd.notna(x) and str(x).startswith("http") else None)
        
        # 🎨 RESTAURAMOS TUS COLORES DE SEMÁFORO
        df_styled = df.style.apply(color_filas, axis=1)
        
        column_config = {
            "STATUS": st.column_config.Column(alignment="center"),
            "DÍAS": st.column_config.Column(alignment="center"),
            "LABORATORIO": st.column_config.Column(alignment="center"),
            "FECHA": st.column_config.Column(alignment="center"),
            "PROVEEDOR": st.column_config.Column(alignment="center"),
            "ORDEN (PDF)": st.column_config.LinkColumn(
                "📄 PDF",
                display_text="📥 Descargar"
            )
        }
        
        # PASAMOS df_styled EN LUGAR DE df
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
    st.success(f"No hay pedidos en la categoría '{filtro_seleccionado}'.")
