# Neptuno Reloaded

Esta aplicación es un backend escrito en **Python** con el framework **Flask** y una interfaz web basada en plantillas HTML. Su propósito es facilitar la generación de archivos XML compatibles con Retail Pro a partir de archivos CSV o TXT y proporcionar herramientas para configurar la conexión a la base de datos Oracle, el mapeo de campos y la generación de SID.

## Funcionalidades principales

- **Generación de XML de inventario**: a partir de un CSV se construye un documento `<DOCUMENT>` con nodos `<INVENTORY>` y `<INVN_SBS>` utilizando los campos seleccionados por el usuario.
- **Generación de Transfer Orders**: se aceptan archivos CSV/TXT con formato especial para crear XML de órdenes de transferencia. Se valida la estructura de las líneas tipo *Header* e *Item* y se consultan datos adicionales en Oracle.
- **Configuración de mapeo de campos**: la interfaz permite seleccionar y ordenar los campos disponibles (`campos_maestros.json`) que se emplearán al leer el CSV. Las configuraciones se guardan en `configuracion.json` y `configuracion_to.json`.
- **Selección de carpeta de salida y delimitador**: se guarda en `ruta_descarga.json` la ruta donde se almacenarán los XML generados y el delimitador a usar al leer los CSV.
- **Conexión a Oracle**: los datos de conexión (host, puerto, servicio, usuario y contraseña) se almacenan en `db_config.json`. La aplicación permite probar la conexión antes de guardarla.
- **Generador de SID**: soporta distintos modos para obtener `item_sid` y `style_sid` (por UPC, a partir de las descripciones o aleatorio). La configuración se mantiene en `sid_generator.json`.
- **Configuración general**: el archivo `config.json` se encuentra en el directorio `config/`.
- **Interfaz web**: se accede a la ruta `/` donde se muestran dos pestañas: *Inventory* y *Transfer Orders*. Cada pestaña contiene formularios para cargar el CSV, configurar campos y ejecutar la generación de XML.

## Endpoints relevantes

- `GET /` – Página principal con la interfaz.
- `POST /generar` – Genera el XML de inventario leyendo el CSV con el mapeo configurado.
- `POST /generar_to` – Genera el XML de Transfer Orders.
- `POST /save_csv_config` – Guarda carpeta de descarga y delimitador.
- `POST /select_folder` y `POST /seleccionar_carpeta` – Muestran un cuadro de diálogo para elegir la carpeta de salida.
- `POST /save_connection` – Guarda los datos de conexión a Oracle.
- `POST /test_connection` – Verifica la conexión con la base de datos.
- `GET/POST /sid-config` – Obtiene o guarda los modos de generación de SID.
- `POST /guardar_config` y `POST /guardar_config_to` – Almacenan el mapeo de campos para inventario y Transfer Orders respectivamente.

## Archivos importantes

- **Neptuno.py** – Script principal que define el servidor Flask y toda la lógica de negocio.
- **Templates/** – Contiene las plantillas `index.html` y `home.html` que conforman la interfaz web.
- **campos_maestros.json** y **campos_maestros_to.json** – Catálogos de campos disponibles para inventario y Transfer Orders.
- **configuracion.json** y **configuracion_to.json** – Guardan las selecciones de campos realizadas por el usuario.
- **db_config.json** – Parámetros de conexión a Oracle.
- **sid_generator.json** – Preferencias para el cálculo de SID.
- **ruta_descarga.json** – Carpeta y delimitador predeterminados para los CSV.
- **config/config.json** – Configuración general de la aplicación.

## Requisitos

- Python 3. Se debe contar con Oracle Instant Client disponible para que `oracledb` funcione correctamente.
- Las dependencias se encuentran en el propio script (`Flask`, `pandas`, `oracledb`, etc.).

## Ejecución

```bash
python Neptuno.py
```

El servidor escuchará en `http://localhost:5000/`. Desde el navegador se podrán cargar los archivos CSV, ajustar configuraciones y generar los XML deseados.

