# neptuno.py
#!/usr/bin/env python3
"""neptuno.py — Flask backend con manejo de CSV delimiter, selección de carpeta, SID generator y DB config."""
from __future__ import annotations
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime
import csv

import logging
from subprocess import CalledProcessError
import hashlib, random, time, struct
import xml.etree.ElementTree as ET

from flask import Flask, jsonify, render_template, request
import oracledb

_ONE_E18 = 1_000_000_000_000_000_000

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.json"

app = Flask(__name__)



# --- Autodetección de Oracle Instant Client ---
def find_oracle_client_dir() -> str | None:
    env = os.environ.get("ORACLE_CLIENT_DIR")
    if env and Path(env).exists():
        return env
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if (Path(p) / "oci.dll").exists():
            return p
    return None

lib_dir = find_oracle_client_dir()
if not lib_dir:
    raise RuntimeError("No se encontró Oracle Instant Client (oci.dll).")
oracledb.init_oracle_client(lib_dir=lib_dir)



DEFAULT_SID_CFG: Dict[str, str] = {"item_sid_mode": "upc", "style_sid_mode": "desc1"}


# --- Utilidades JSON para archivo unificado ---
def _read_config() -> dict:
    """Leer config.json ignorando lineas de comentario"""
    try:
        text = CONFIG_FILE.read_text("utf-8")
    except FileNotFoundError:
        return {}

    cleaned_lines = []
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("/*"):
            in_block = True
            continue
        if stripped.endswith("*/"):
            in_block = False
            continue
        if in_block or stripped.startswith("//") or stripped.startswith("#"):
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    return json.loads(cleaned)

def _write_config(data: dict):
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def _load_section(keys: list[str], default):
    data = _read_config()
    cur = data
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    if keys[-1] not in cur:
        cur[keys[-1]] = default
        _write_config(data)
        return default
    return cur[keys[-1]]

def _save_section(keys: list[str], value):
    data = _read_config()
    cur = data
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value
    _write_config(data)

# --- Configuraciones ---
def load_csv_cfg() -> Dict[str, Any]:
    return _load_section(["csv"], {"ruta": str(BASE / "Salida"), "delimiter": ","})

def save_csv_cfg(cfg: Dict[str, Any]):
    _save_section(["csv"], cfg)

def load_sid_cfg() -> Dict[str, str]:
    return _load_section(["sid_generator"], DEFAULT_SID_CFG)


def save_sid_cfg(cfg: Dict[str, str]):
    """Persistir configuracion del generador de SID."""
    _save_section(["sid_generator"], cfg)


def db_cfg() -> Dict[str, Any]:
    return _load_section(["database"], {})


def maestros() -> List[Dict[str, Any]]:
    return _load_section(["inventory", "campos_maestros"], [])



def plantilla() -> List[Dict[str, Any]]:
    data = _load_section(["inventory", "configuracion"], [])
    for i, d in enumerate(data):
        if isinstance(d, dict):
            d.setdefault("pos", i)
            d.setdefault("visual", d.get("visual", d.get("rpro")))
    return sorted(data, key=lambda x: x["pos"])

def ruta_desc() -> str:
    return load_csv_cfg().get("ruta", str(BASE / "Salida"))

def load_campos_maestros_to() -> list[dict]:
    """Devuelve el catálogo de campos para Transfer Orders."""
    return _load_section(["transfer_orders", "campos_maestros"], [])

def load_plantilla_to() -> dict:
    """Obtiene la configuración actual de Transfer Orders con objetos completos."""
    cfg = _load_section(["transfer_orders", "configuracion"], {"header": [], "detail": []})
    maestros = load_campos_maestros_to()

    header = []
    for idx, r in enumerate(cfg.get('header', [])):
        m = next((c for c in maestros if c['rpro'] == r), None)
        if m:
            header.append({
                'rpro':    m['rpro'],
                'visual':  m['visual'],
                'section': m['section'],
                'pos':     idx
            })

    detail = []
    for idx, r in enumerate(cfg.get('detail', [])):
        m = next((c for c in maestros if c['rpro'] == r), None)
        if m:
            detail.append({
                'rpro':    m['rpro'],
                'visual':  m['visual'],
                'section': m['section'],
                'pos':     idx
            })

    return {'header': header, 'detail': detail}


def load_config_to() -> dict[str, list]:
    """Carga la configuración de Transfer Orders (solo listas)."""
    return _load_section(["transfer_orders", "configuracion"], {"header": [], "detail": []})


# --- Nuevo Calculo Item_Sid & Style_Sid ---

def _fix_sid_f8(value: int) -> int:
    b = bytearray(struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF))
    tmp = b[0] & 0x07
    b[0] &= 0xF8
    b[7] &= 0x03
    value = struct.unpack("<Q", b)[0] * 0x20
    b = bytearray(struct.pack("<Q", value))
    b[0] = (b[0] & 0xF8) | tmp
    return struct.unpack("<q", b)[0]          # signed 64‑bit

def sid_from_upc(upc: str) -> str:
    return str(_fix_sid_f8(int(upc)))

def sid_random() -> str:
    ts   = int(time.time() * 1000) % 1_000_000_000_000
    cnt  = random.randint(0, 9_999)
    base = int(f"{ts:012d}{cnt:04d}")
    return str(_fix_sid_f8(base))

def sid_from_desc(desc: str) -> str:
    desc = desc[:19]
    h    = hashlib.sha256(desc.encode("utf-8")).digest()[:8]
    temp = struct.unpack("<q", h)[0] % _ONE_E18   # se preserva el signo
    return str(_fix_sid_f8(temp))

def sid_from_both(d1: str, d2: str) -> str:
    return sid_from_desc((d1 + d2)[:19])

# ---------- ALIAS para que el código principal los use ----------
sid_gen_from_upc = sid_from_upc      # genera item_sid por UPC
sid_gen_random   = sid_random        # genera item_sid aleatorio

sid_style_desc1  = sid_from_desc
sid_style_both   = sid_from_both
sid_style_random = sid_random


# --- XML Helpers ---

def _indent(el: ET.Element, lvl: int = 0):
    """
    Aplica indentación correcta al elemento XML y sus hijos.
    El formato resultante será:
    
    <tag>
      <child>text</child>
      <child>
        <grandchild />
        <grandchild>text</grandchild>
      </child>
    </tag>
    
    Args:
        el: Elemento XML a indentar
        lvl: Nivel de indentación actual
    """
    i = "\n" + lvl * "  "
    if len(el):
        if not el.text or not el.text.strip():
            el.text = i + "  "
        for idx, e in enumerate(el):
            _indent(e, lvl+1)
            if not e.tail or not e.tail.strip():
                if idx == len(el) - 1:  # último elemento
                    e.tail = i
                else:
                    e.tail = i + "  "
        if not el.tail or not el.tail.strip():
            el.tail = i
    else:
        if lvl and (not el.tail or not el.tail.strip()):
            el.tail = i

# ── Crear XML con sección dinámica (Función actualmente no utilizada) ────────────────
'''
def crear_xml(df: pd.DataFrame, plan: List[Dict[str, Any]]) -> ET.Element:
    from datetime import datetime

    doc = ET.Element("DOCUMENT")
    invs = ET.SubElement(doc, "INVENTORYS")

    static_attrs = {
        "sbs_no": "001",
        "modified_date": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "currency_id": "1",
        "currency_name": "DOLLARS",
        "flag": "0",
        "kit_type": "0",
        "max_disc_perc1": "100",
        "max_disc_perc2": "100",
        "print_tag": "1",
        "active": "1",
        "cms": "0",
    }

    cfg = db_cfg()
    dsn_str = (
        f"(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={cfg['servidor']})"
        f"(PORT={cfg['puerto']}))(CONNECT_DATA=(SERVICE_NAME={cfg['base_datos']})))"
    )
    conn = oracledb.connect(user=cfg["usuario"], password=cfg["password"], dsn=dsn_str)
    cursor = conn.cursor()

    for _, row in df.iterrows():
        inv = ET.SubElement(invs, "INVENTORY")
        ET.SubElement(inv, "INVN_STYLE", {"style_sid": "STYLE_SID_AUTOGEN"})

        upc_val = str(row.get("local_upc", "") or "")
        style_sid, item_sid = "STYLE_SID_AUTOGEN", "ITEM_SID_AUTOGEN"
        try:
            cursor.execute(
                "SELECT style_sid, item_sid FROM cms.INVN_SBS WHERE sbs_no=:sbs AND local_upc=:upc",
                sbs="001", upc=upc_val
            )
            dbrow = cursor.fetchone()
            if dbrow:
                style_sid, item_sid = dbrow[0], dbrow[1]
        except:
            pass

        invn = ET.SubElement(inv, "INVN", {"item_sid": item_sid, "upc": upc_val})
        invn_sbs = ET.SubElement(inv, "INVN_SBS", dict(static_attrs))
        suplis = ET.SubElement(invn_sbs, "INVN_SBS_SUPPLS")

        for fld in plan:
            pos = fld["pos"]
            rpro = fld["rpro"]
            section = fld.get("section", "INVN_SBS")
            raw = row[pos]
            val = "" if pd.isna(raw) else str(raw)

            if section == "INVN_SBS":
                invn_sbs.set(rpro, val)
            elif section == "INVN_SBS_SUPPL":
                parts = rpro.split("_", 1)
                if len(parts) == 2 and parts[1] != "2":
                    ET.SubElement(suplis, "INVN_SBS_SUPPL", {"udf_no": parts[1], "udf_value": val})
                else:
                    ET.SubElement(suplis, "INVN_SBS_SUPPL", {"udf_value": val})

    cursor.close()
    conn.close()

    _indent(doc)
    return doc
'''
# ─────────────────────────────────────────────────────────────────────────────

# --- Endpoints Flask ---
@app.route("/")
def home():
    return render_template(
        "home.html",
        csv_cfg=load_csv_cfg(),
        db_cfg=db_cfg(),
        sid_cfg=load_sid_cfg(),
        maestros_to=load_campos_maestros_to(),
        plantilla_to=load_config_to(),
        maestros=maestros(),
        plantilla=plantilla()
    )

@app.route("/generar_to", methods=["POST"])
def generar_to():
    # 1) Validación de archivo subido
    if 'archivo' not in request.files:
        return jsonify(error="No se ha subido ningún archivo"), 400
    f = request.files['archivo']
    if f.filename == '':
        return jsonify(error="No se ha seleccionado ningún archivo"), 400

    # 2) Cargo config CSV y delimitador
    csv_cfg = load_csv_cfg()
    delim   = csv_cfg.get("delimiter", ",")

    # 3) Cargo plantilla TO (solo rpro strings) y maestro de campos
    raw_tpl   = load_plantilla_to()            # {'header': [...], 'detail': [...]}
    maestros  = load_campos_maestros_to()       # lista de {rpro,visual,section,len}
    raw_h     = raw_tpl.get('header', [])
    raw_i     = raw_tpl.get('detail', [])

    # 4) Si no hay mapping, abortamos ya que no sabemos qué columnas leer
    if not raw_h or not raw_i:
        return jsonify(error="No hay mapping de Header o Detail. Por favor configure ambos y vuelva a intentar."), 400

    # 5) Reconstruyo header_tpl y detail_tpl como listas de objetos completos
    header_tpl = []
    for pos, r in enumerate(raw_h):
        m = next((x for x in maestros if x['rpro'] == r), None)
        header_tpl.append({
            'rpro':    r,
            'visual':  m['visual'] if m else r,
            'section': m['section'] if m else 'TO',
            'pos':     pos
        })
    detail_tpl = []
    for pos, r in enumerate(raw_i):
        m = next((x for x in maestros if x['rpro'] == r), None)
        detail_tpl.append({
            'rpro':    r,
            'visual':  m['visual'] if m else r,
            'section': m['section'] if m else 'INVN_BASE_ITEM',
            'pos':     pos
        })

    # 6) Aplano ambos para validar número y longitudes
    all_tpl        = header_tpl + detail_tpl
    campos_rpros   = [c['rpro'] for c in all_tpl]
    total_expected = len(campos_rpros)

    campos_meta = {c['rpro']: c.get('len') for c in maestros}

    # 7) Leo todo el CSV/TXT en memoria
    raw = f.stream.read().decode('latin-1').splitlines()

    # 8) Validación de número de columnas y longitudes
    for num, line in enumerate(raw, start=1):
        parts = line.split(delim)
        if len(parts) != total_expected:
            return jsonify(
                error=(
                    f"Línea {num}: se esperaban {total_expected} campos "
                    f"pero se encontraron {len(parts)}."
                )
            ), 400
        for idx, val in enumerate(parts, start=1):
            rpro    = campos_rpros[idx-1]
            max_len = campos_meta.get(rpro)
            if max_len is not None and len(val) > max_len:
                return jsonify(
                    error=(
                        f"Línea {num}, campo #{idx} ({rpro}): "
                        f"longitud {len(val)} supera máximo {max_len}."
                    )
                ), 400

    # 9) Directorio y nombre de salida
    out_dir = Path(csv_cfg.get("ruta", str(BASE / "Salida")))
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("TO*.xml"))
    num = int(existing[-1].stem[2:]) + 1 if existing else 1
    salida = out_dir / f"TO{num:03d}.xml"

    # 10) Reconvierto a BytesIO para reutilizar
    csv_stream = io.BytesIO("\n".join(raw).encode("latin-1"))

    # 11) Conexión Oracle
    cfg    = db_cfg()
    dsn    = (
        f"(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={cfg['servidor']})"
        f"(PORT={cfg['puerto']}))(CONNECT_DATA=(SERVICE_NAME={cfg['base_datos']})))"
    )
    conn   = oracledb.connect(user=cfg['usuario'], password=cfg['password'], dsn=dsn)
    cursor = conn.cursor()

    # 12) Build XML
    root    = ET.Element("DOCUMENT")
    to_node = ET.SubElement(root, "TO")

    # — Header (línea H) —
    header_line = raw[0]
    if not header_line.startswith("H,"):
        cursor.close(); conn.close()
        return jsonify(error="Formato inválido: primera línea debe empezar con 'H,'"), 400
    vals_hdr = header_line.split(delim)[1:]
    hdr_attrs = {
        "to_sid":        sid_random(),
        "to_type":       "0",
        "modified_date": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "cms":           "1", "held": "1", "active": "1"
    }
    for campo, val in zip(header_tpl, vals_hdr):
        hdr_attrs[campo['rpro']] = val.strip()
    ET.SubElement(to_node, "TO_HDR", **hdr_attrs)

    items_node = ET.SubElement(to_node, "TO_ITEMS")

    # — Detalle (líneas I) —
    for idx, line in enumerate(raw[1:], start=1):
        parts = line.split(delim)
        tipo  = parts[0]
        if tipo == "S":
            break
        if tipo != "I":
            continue

        cols    = parts[1:]
        upc     = cols[0].strip()
        ord_qty = cols[1].strip()
        price   = cols[2].strip() if len(cols) > 2 else ""

        cursor.execute(
            """
            SELECT style_sid, item_sid, cost, tax_code, dcs_code, vend_code
              FROM cms.INVN_SBS
             WHERE sbs_no    = :1
               AND local_upc = :2
            """,
            (hdr_attrs["sbs_no"], upc)
        )
        row = cursor.fetchone()
        if not row:
            cursor.close(); conn.close()
            return jsonify(error=f"Línea detalle {idx}: UPC «{upc}» no existe"), 400

        style_sid, item_sid, cost_db, tax_code_db, dcs_code, vend_code = row

        ti = ET.SubElement(
            items_node, "TO_ITEM",
            item_pos=str(idx),
            item_sid=str(item_sid),
            price=price,
            cost=str(cost_db),
            tax_code=str(tax_code_db)
        )
        ET.SubElement(
            ti, "INVN_BASE_ITEM",
            item_sid=str(item_sid),
            upc=upc,
            style_sid=str(style_sid),
            dcs_code=str(dcs_code),
            vend_code=str(vend_code),
            use_qty_decimals="0",
            cost=str(cost_db),
            tax_code=str(tax_code_db)
        )
        q = ET.SubElement(ti, "TO_QTYS")
        ET.SubElement(
            q, "TO_QTY",
            store_no=hdr_attrs["sbs_no"],
            ord_qty=ord_qty,
            rcvd_qty="0"
        )

    cursor.close()
    conn.close()

    # 13) Escritura final
    _indent(root)
    ET.ElementTree(root).write(str(salida), encoding="utf-8", xml_declaration=True)

    return jsonify(status="success", message="XML TO generado correctamente", path=str(salida))




@app.route("/guardar_config_to", methods=["POST"])
def guardar_config_to():
    # 1) Obtengo las listas de rpro en orden
    headers_rpros = request.form.getlist("header[]")
    details_rpros = request.form.getlist("detail[]")

    # 2) Cargo la definición de todos los campos maestros TO
    maestros = load_campos_maestros_to()  # lista de dicts con 'rpro','visual',...

    # 3) Armo la lista de objetos para header
    header_list = []
    for idx, rpro in enumerate(headers_rpros):
        m = next((m for m in maestros if m["rpro"] == rpro), None)
        visual = m["visual"] if m else rpro
        header_list.append({
            "rpro": rpro,
            "visual": visual,
            "pos": idx
        })

    # 4) Mismo para detail
    detail_list = []
    for idx, rpro in enumerate(details_rpros):
        m = next((m for m in maestros if m["rpro"] == rpro), None)
        visual = m["visual"] if m else rpro
        detail_list.append({
            "rpro": rpro,
            "visual": visual,
            "pos": idx
        })

    # 5) Guardo la configuración completa
    config = {"header": header_list, "detail": detail_list}
    _save_section(["transfer_orders", "configuracion"], config)

    return jsonify(ok=True)



@app.route("/csv-config", methods=["GET"])
def csv_config_get():
    return jsonify(load_csv_cfg())

@app.route("/save_csv_config", methods=["POST"])
def save_csv_config():
    data  = request.get_json()
    delim = data.get("delimiter")
    ruta  = data.get("ruta")
    if delim not in (",", ";", "|"):
        return jsonify(error="Delimiter inválido"), 400
    cfg = load_csv_cfg()
    cfg["delimiter"] = delim
    if ruta:
        cfg["ruta"] = ruta
    save_csv_cfg(cfg)
    return "", 204

@app.route("/select_folder", methods=["POST"])
def select_folder():

    except Exception as exc:
        return jsonify(error=f"No se pudo abrir el diálogo: {exc}"), 500

    if not carpeta:
        return jsonify(error="No se seleccionó carpeta"), 400

    try:
        Path(carpeta).mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return jsonify(error=f"No se pudo crear la carpeta: {exc}"), 400

    cfg = load_csv_cfg()
    cfg["ruta"] = carpeta
    save_csv_cfg(cfg)
    return jsonify(ruta=carpeta)

@app.route("/seleccionar_carpeta", methods=["POST"])
def seleccionar_carpeta():
    # Alias en español para el mismo handler
    return select_folder()

@app.route("/save_connection", methods=["POST"])
def save_connection():
    # ① Si vienen como JSON (raro en este form), los parseamos…
    if request.is_json:
        data = request.get_json()
    else:
        # ② …sino tomamos el form-url-encoded
        data = request.form.to_dict()

    # ③ Validamos campos obligatorios
    required = ["servidor","puerto","base_datos","usuario","password"]
    for field in required:
        if not data.get(field):
            return jsonify(ok=False, error=f"Campo requerido: {field}"), 400


    _save_section(["database"], data)

    # ④ Devolvemos 200 y ok=True para que tu JS lo reconozca como éxito
    return jsonify(ok=True)


@app.route("/test_connection", methods=["POST"])
def test_connection():
    config = db_cfg()
    try:
        dsn = f"{config['servidor']}:{config['puerto']}/{config['base_datos']}"
        conn = oracledb.connect(user=config["usuario"], password=config["password"], dsn=dsn)
        conn.close()
        return jsonify(status="success", message="Conexión exitosa")
    except Exception as e:
        return jsonify(status="error", message=f"Error de conexión: {e}"), 500

@app.route("/sid-config", methods=["GET"])
def sid_config_get():
    return jsonify(load_sid_cfg())

@app.route("/sid-config", methods=["POST"])
def sid_config_post():
    data = request.get_json()
    if not data:
        return jsonify(error="Datos inválidos"), 400
    item_mode = data.get("item_sid_mode")
    style_mode= data.get("style_sid_mode")
    if item_mode not in ("upc","alu","random"):
        return jsonify(error="Modo item_sid inválido"), 400
    if style_mode not in ("desc1","both","random"):
        return jsonify(error="Modo style_sid inválido"), 400
    save_sid_cfg({"item_sid_mode": item_mode, "style_sid_mode": style_mode})
    return "", 204

@app.route("/guardar_config", methods=["POST"])
def guardar_config():
    campos = request.form.getlist("campos[]")
    catalogo = {c["rpro"]: c for c in maestros()}
    nueva = []
    for idx, rpro in enumerate(campos):
        m = catalogo.get(rpro, {})
        nueva.append({
            "rpro": rpro,
            "visual": m.get("visual", rpro),
            "pos": idx
        })

    _save_section(["inventory", "configuracion"], nueva)
    return jsonify(ok=True)


# Corrección en función generar_xml() para asignación estricta de nodos

def generar_xml(csv_file_stream, output_path, plantilla_cfg, delimiter):
    csv_file_stream.seek(0)
    lines = csv_file_stream.read().decode('latin-1').splitlines()
    reader = csv.DictReader(
        lines,
        delimiter=delimiter,
        fieldnames=[c['visual'] for c in plantilla_cfg]
    )
    rows = list(reader)

    cfg = db_cfg()
    dsn_str = (
        f"(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={cfg.get('servidor')})"
        f"(PORT={cfg.get('puerto')}))(CONNECT_DATA=(SERVICE_NAME={cfg.get('base_datos')})))"
    )
    conn = oracledb.connect(
        user=cfg.get('usuario'), password=cfg.get('password'), dsn=dsn_str
    )
    cursor = conn.cursor()

    root = ET.Element('DOCUMENT')
    inventorys = ET.SubElement(root, 'INVENTORYS')

    campos_seccion = {c['rpro']: c['section'] for c in maestros()}

    # ------------------------------------------------------------------
    # Atributos fijos que siempre van en <INVN_SBS>
    static_attrs = {
        "sbs_no": "001",
        "modified_date": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "currency_id": "1",
        "currency_name": "DOLLARS",
        "flag": "0",
        "kit_type": "0",
        "max_disc_perc1": "100",
        "max_disc_perc2": "100",
        "print_tag": "1",
        "active": "1",
        "cms": "0",
    }

    for idx, row in enumerate(rows, start=1):

        # ❶ Mapeo dinámico de nombres visuales → valores
        map_vis = {c["rpro"]: c["visual"] for c in plantilla_cfg}
        vis_upc = map_vis["local_upc"]            # UPC siempre existe
        upc_val = row.get(vis_upc, "").strip()

                # ❷ Validación DCS_CODE existe en cms.dcs
        dcs_val = row.get(map_vis.get("dcs_code", ""), "").strip()
        cursor.execute(
            "SELECT 1 FROM cms.dcs WHERE sbs_no = '001' AND dcs_code = :1",
            (dcs_val,)
        )
        if not cursor.fetchone():
            raise RuntimeError(f"Línea {idx}: DCS_CODE '{dcs_val}' no existe en la base de datos")

        # ❸ Validación VEND_CODE existe en cms.vendor
        vend_val = row.get(map_vis.get("vend_code", ""), "").strip()
        cursor.execute(
            "SELECT VEND_CODE FROM cms.vendor WHERE sbs_no = '001' AND vend_code = :1",
            (vend_val,)
        )
        if not cursor.fetchone():
            raise RuntimeError(f"Línea {idx}: VEND_CODE '{vend_val}' no existe en la base de datos")

        # ❷ Consulta por UPC
        try:
            cursor.execute(
                "SELECT style_sid, item_sid FROM cms.INVN_SBS "
                "WHERE sbs_no = :1 AND local_upc = :2",
                ("001", upc_val)
            )
            dbrow = cursor.fetchone()
        except Exception as db_err:
            raise RuntimeError(f"Error al consultar Oracle: {db_err}")

        if dbrow:
            style_sid, item_sid = map(str, dbrow)

        else:  # UPC nuevo
            sid_cfg = load_sid_cfg()

            # ---------- ITEM SID ----------
            mode_item = sid_cfg.get("item_sid_mode", "upc").lower()
            if mode_item == "random":
                item_sid = sid_gen_random()
            else:                          # 'upc'
                item_sid = sid_gen_from_upc(upc_val)

            # ---------- STYLE SID ----------
            desc1_val  = row.get(map_vis["description1"], "").strip()
            desc2_val  = row.get(map_vis.get("description2", ""), "").strip()

            # ❶ ¿Existe DESC1 en Oracle?
            cursor.execute(
                "SELECT style_sid FROM cms.INVN_SBS "
                "WHERE sbs_no = :1 AND description1 = :2",
                ("001", desc1_val)
            )
            sty_row = cursor.fetchone()

            if sty_row:                           # DESC1 ya existe → reutilizar
                style_sid = str(sty_row[0])

            else:                                 # DESC1 no existe → generar
                mode_style = sid_cfg.get("style_sid_mode", "desc1").lower()
                if mode_style == "both":
                    style_sid = sid_style_both(desc1_val, desc2_val)
                elif mode_style == "random":
                    style_sid = sid_style_random()
                else:                             # 'desc1'
                    style_sid = sid_style_desc1(desc1_val)

        # --------- CREAR ESTRUCTURA XML FIJA ---------
        inv = ET.SubElement(inventorys, "INVENTORY")
        ET.SubElement(inv, "INVN_STYLE", style_sid=style_sid)
        ET.SubElement(inv, "INVN", item_sid=item_sid, upc=upc_val)

        invn_sbs   = ET.SubElement(inv, "INVN_SBS", dict(static_attrs))
        udf_buffer = {}

        # --------- Rellenar atributos variables ---------
        for fld in plantilla_cfg:
            key      = fld["visual"]
            rpro     = fld["rpro"]
            section  = campos_seccion.get(rpro, "INVN_SBS")
            valor    = row.get(key, "")

            if section == "INVN_SBS":
                invn_sbs.set(rpro, valor)
            elif section == "INVN_SBS_SUPPL":
                udf_no = rpro.split("_", 1)[1] if "_" in rpro else ""
                udf_buffer[udf_no] = valor

        # ——— Auto-lookup de tax_code usando el valor de dcs_code ———
        orig_dcs = row.get(map_vis.get("dcs_code", ""), "").strip()
        if orig_dcs:
            cursor.execute(
                "SELECT tax_code FROM cms.dcs WHERE sbs_no = '001' AND dcs_code = :1",
                (orig_dcs,)
            )
        tax_row = cursor.fetchone()
        if tax_row and tax_row[0] is not None:
            invn_sbs.set("tax_code", str(tax_row[0]))

        if udf_buffer:
            supps = ET.SubElement(invn_sbs, "INVN_SBS_SUPPLS")
            for no, val in udf_buffer.items():
                ET.SubElement(supps, "INVN_SBS_SUPPL",
                              udf_no=no, udf_value=val)

    # --- FIN del for ---

    cursor.close()
    conn.close()

    _indent(root)
    ET.ElementTree(root).write(output_path,
                               encoding="utf-8",
                               xml_declaration=True)




# ------------------------------------------------------------------
#  RUTA: /generar  –  sube CSV/TXT, valida y genera XML
# ------------------------------------------------------------------
@app.route("/generar", methods=["POST"])
def generar():
    # ---------- 1) Comprobaciones básicas de archivo ----------
    if "archivo" not in request.files:
        return jsonify(error="No se ha subido ningún archivo"), 400
    f = request.files["archivo"]
    if f.filename == "":
        return jsonify(error="No se ha seleccionado ningún archivo"), 400

    # ---------- 2) Carga de configuraciones ----------
    csv_cfg      = load_csv_cfg()
    delim        = csv_cfg.get("delimiter", ",")
    plantilla_cfg = plantilla()                      # campos seleccionados
    campos_plant = [c["rpro"] for c in plantilla_cfg]
    total_cols   = len(campos_plant)

    # Metadatos de longitud máxima por campo (catálogo en config/config.json)
    campos_meta = {c["rpro"]: c.get("len") for c in maestros()}

    # ---------- 3) Validaciones línea a línea ----------
    contenido = f.stream.read().decode("latin-1").splitlines()
    for num, linea in enumerate(contenido, start=1):
        valores = linea.split(delim)

        # 3.1  Validar número de columnas
        if len(valores) != total_cols:
            return jsonify(
                error=(
                    f"Línea {num}: se esperaban {total_cols} campos según "
                    f"su plantilla, pero se encontraron {len(valores)}."
                )
            ), 400

        # 3.2  Validar longitud máxima por campo
        for idx, val in enumerate(valores, start=1):
            campo   = campos_plant[idx - 1]
            max_len = campos_meta.get(campo)
            if max_len is not None and len(val) > max_len:
                return jsonify(
                    error=(
                        f"Línea {num}, campo #{idx} ({campo}): longitud "
                        f"{len(val)} supera el máximo de {max_len}."
                    )
                ), 400

    # --- 4) Generación del XML ---
    # ––– Construir nombre incremental Inventory001.xml, 002, 003… –––
    outdir = csv_cfg.get("ruta")
    i = 1
    while True:
        fname = f"Inventory{i:03d}.xml"
        salida = os.path.join(outdir, fname)
        if not os.path.exists(salida):
            break
        i += 1
    # sale con salida = …/Inventory00i.xml

    data_bytes = ("\n".join(contenido)).encode("latin-1")
    csv_stream = io.BytesIO(data_bytes)
    csv_stream.seek(0)

    try:
        generar_xml(
            csv_file_stream=csv_stream,
            output_path=salida,
            plantilla_cfg=plantilla(),
            delimiter=delim
        )
    except Exception as ex:
        # Cualquier fallo (validaciones, Oracle, generación…) llega aquí
        return jsonify(error=f"Error al generar XML: {ex}"), 500   # ← 8 espacios

    # ---------- 5) Éxito ----------
    return jsonify(                                                # ← 4 espacios
        status="success",
        message="XML generado correctamente",
        path=salida
    )

# ---------- 5) Éxito ----------

if __name__ == "__main__":
    app.run(debug=False)
