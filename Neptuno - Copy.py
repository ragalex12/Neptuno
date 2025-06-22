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
import xml.etree.ElementTree as ET
from flask import send_file  # si quieres devolver directamente el XML

import pandas as pd
import xml.etree.ElementTree as ET
from flask import Flask, jsonify, render_template, request
import oracledb
from tkinter import Tk, filedialog
import io              
import logging
from subprocess import CalledProcessError
import hashlib, random, time, struct
_ONE_E18 = 1_000_000_000_000_000_000



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

# --- Rutas de configuración ---
BASE            = Path(__file__).resolve().parent
CFG_USR         = BASE / "configuracion.json"
CFG_MAS         = BASE / "campos_maestros.json"
CFG_OUT         = BASE / "ruta_descarga.json"    # {'ruta':..., 'delimiter':...}
CFG_DB          = BASE / "db_config.json"
SID_CFG_FILE    = BASE / "sid_generator.json"
TPL_DIR         = BASE / "Templates"

DEFAULT_SID_CFG: Dict[str, str] = {"item_sid_mode": "upc", "style_sid_mode": "desc1"}

app = Flask(__name__, template_folder=str(TPL_DIR))

# --- Utilidades JSON ---
def _load(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        path.write_text(json.dumps(default, indent=2, ensure_ascii=False), "utf-8")
        return default

def _save(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")

# --- Configuraciones ---
def load_csv_cfg() -> Dict[str, Any]:
    return _load(CFG_OUT, {"ruta": str(BASE / "Salida"), "delimiter": ","})

def save_csv_cfg(cfg: Dict[str, Any]):
    _save(CFG_OUT, cfg)

def load_sid_cfg() -> Dict[str, str]:
    return _load(SID_CFG_FILE, DEFAULT_SID_CFG)

def save_sid_cfg(cfg: Dict[str, str]):
    _save(SID_CFG_FILE, cfg)

def db_cfg() -> Dict[str, Any]:
    return _load(CFG_DB, {})

def maestros() -> List[Dict[str, Any]]:
    return _load(CFG_MAS, [])

def plantilla() -> List[Dict[str, Any]]:
    data = _load(CFG_USR, [])
    for i, d in enumerate(data):
        if isinstance(d, dict):
            d.setdefault("pos", i)
            d.setdefault("visual", d.get("visual", d.get("rpro")))
    return sorted(data, key=lambda x: x["pos"])

def ruta_desc() -> str:
    return load_csv_cfg().get("ruta", str(BASE / "Salida"))


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
def index():
    csv_cfg = load_csv_cfg()
    return render_template(
        "index.html",
        csv_cfg=csv_cfg,
        ruta=csv_cfg["ruta"],
        db_cfg=db_cfg(),
        sid_cfg=load_sid_cfg(),
        maestros=maestros(),
        plantilla=plantilla()
    )

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
    root = Tk()
    root.withdraw()
    carpeta = filedialog.askdirectory(title="Selecciona carpeta de salida")
    root.destroy()
    if carpeta:
        cfg = load_csv_cfg()
        cfg["ruta"] = carpeta
        save_csv_cfg(cfg)
        return jsonify(ruta=carpeta)
    return jsonify(ruta=""), 204

@app.route("/seleccionar_carpeta", methods=["POST"])
def seleccionar_carpeta():
    # Alias en español para el mismo handler
    return select_folder()

@app.route("/save_connection", methods=["POST"])
def save_connection():
    data = request.get_json() or request.form.to_dict()
    required = ["servidor","puerto","base_datos","usuario","password"]
    for field in required:
        if not data.get(field):
            return jsonify(error=f"Campo requerido: {field}"), 400
    data.setdefault("tipo_conexion", "oracle")
    _save(CFG_DB, data)
    return "", 204

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
    cat = {c["rpro"]: c for c in maestros()}
    nueva = []
    for pos, rpro in enumerate(campos):
        m = cat.get(rpro, {"rpro": rpro, "visual": rpro})
        nueva.append({"rpro": m["rpro"], "visual": m["visual"], "pos": pos})
    _save(CFG_USR, nueva)
    return jsonify(ok=True)


# Corrección en función generar_xml() para asignación estricta de nodos
from datetime import datetime

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

    # Metadatos de longitud máxima por campo (campos_maestros.json)
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