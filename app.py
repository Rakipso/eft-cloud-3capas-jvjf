import os
import requests
import pymysql
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "clave-sesion-eft-cloud")

# Configuración desde variables de entorno (inyectadas por User Data en EC2)
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", 3306))
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "cloud_app")
S3_BASE_URL = os.environ.get("S3_BASE_URL", "")


def obtener_metadatos_ec2():
    """Consulta Instance ID y Availability Zone mediante IMDSv2."""
    try:
        token_resp = requests.put(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            timeout=0.5,
        )
        headers = {"X-aws-ec2-metadata-token": token_resp.text}
        instance_id = requests.get(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers=headers,
            timeout=0.5,
        ).text
        az = requests.get(
            "http://169.254.169.254/latest/meta-data/placement/availability-zone",
            headers=headers,
            timeout=0.5,
        ).text
        return instance_id, az
    except Exception:
        return "Entorno Local", "N/A"


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


def inicializar_bd():
    """Crea la tabla de inventario/solicitudes si no existe."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS recursos_cloud (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nombre VARCHAR(100) NOT NULL,
                    categoria VARCHAR(50) NOT NULL,
                    descripcion VARCHAR(255) NOT NULL,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


@app.route("/health")
def health():
    """Endpoint para el Target Group Health Check del ALB."""
    return {"status": "healthy"}, 200


@app.route("/", methods=["GET"])
def index():
    instance_id, az = obtener_metadatos_ec2()
    registros = []
    db_estado = "Conectado a RDS MySQL"

    try:
        inicializar_bd()
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM recursos_cloud ORDER BY id DESC")
            registros = cursor.fetchall()
        conn.close()
    except Exception as e:
        db_estado = f"Error de conexión a RDS: {e}"

    return render_template(
        "index.html",
        instance_id=instance_id,
        az=az,
        db_host=DB_HOST,
        db_estado=db_estado,
        s3_base_url=S3_BASE_URL.rstrip("/"),
        registros=registros,
    )


@app.route("/agregar", methods=["POST"])
def agregar():
    nombre = request.form.get("nombre", "").strip()
    categoria = request.form.get("categoria", "").strip()
    descripcion = request.form.get("descripcion", "").strip()

    if not nombre or not categoria or not descripcion:
        flash("Todos los campos son obligatorios.", "error")
        return redirect(url_for("index"))

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO recursos_cloud (nombre, categoria, descripcion) VALUES (%s, %s, %s)",
                (nombre, categoria, descripcion),
            )
        conn.commit()
        conn.close()
        flash("Registro guardado correctamente en Amazon RDS.", "ok")
    except Exception as e:
        flash(f"No se pudo guardar en RDS: {e}", "error")

    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)