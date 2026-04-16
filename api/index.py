import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import oracledb
from flask import Flask, flash, redirect, render_template, url_for


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

SELECT_PARTICIPANTS_SQL = """
SELECT
    u.nome,
    u.email,
    u.trust_score,
    i.status
FROM USUARIOS u
JOIN INSCRICOES i ON u.id = i.usuario_id
ORDER BY u.id, i.id
"""

SELECT_AUDIT_LOGS_SQL = """
SELECT
    id,
    inscricao_id,
    motivo,
    data
FROM LOG_AUDITORIA
ORDER BY data DESC, id DESC
"""

FRAUD_SCAN_PLSQL = r"""
DECLARE
    CURSOR c_inscricoes IS
        SELECT i.id, i.usuario_id, u.email
        FROM INSCRICOES i
        JOIN USUARIOS u ON u.id = i.usuario_id
        WHERE i.status = 'PENDING';

    v_id_inscricao INSCRICOES.ID%TYPE;
    v_usuario_id   USUARIOS.ID%TYPE;
    v_email        USUARIOS.EMAIL%TYPE;
    v_count NUMBER := 0;
BEGIN
    OPEN c_inscricoes;

    LOOP
        FETCH c_inscricoes INTO v_id_inscricao, v_usuario_id, v_email;
        EXIT WHEN c_inscricoes%NOTFOUND;

        IF v_email LIKE '%@fake.com'
           OR v_email LIKE '%@temp-mail%'
           OR NOT REGEXP_LIKE(v_email, '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
        THEN
            UPDATE INSCRICOES
            SET STATUS = 'CANCELLED'
            WHERE ID = v_id_inscricao;

            UPDATE USUARIOS
            SET TRUST_SCORE = TRUST_SCORE - 15
            WHERE ID = v_usuario_id;

            INSERT INTO LOG_AUDITORIA (ID, INSCRICAO_ID, MOTIVO, DATA)
            VALUES (
                LOG_AUDITORIA_SEQ.NEXTVAL,
                v_id_inscricao,
                'Bot detectado - Email suspeito: ' || v_email,
                SYSDATE
            );

            v_count := v_count + 1;
        END IF;
    END LOOP;

    CLOSE c_inscricoes;
    COMMIT;

    DBMS_OUTPUT.PUT_LINE('Total de inscricoes canceladas: ' || v_count);
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        DBMS_OUTPUT.PUT_LINE('Erro: ' || SQLERRM);
END;
"""

app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR),
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "global-cyber-summit")


def oracle_config() -> dict[str, Any]:
    user = os.getenv("DB_USER") or os.getenv("ORACLE_USER")
    password = os.getenv("DB_PASSWORD") or os.getenv("ORACLE_PASSWORD")
    dsn = os.getenv("DB_DSN") or os.getenv("ORACLE_DSN")

    if dsn:
        if not user or not password:
            raise RuntimeError(
                "Defina DB_USER/DB_PASSWORD com DB_DSN para conectar ao Oracle."
            )
        return {"user": user, "password": password, "dsn": dsn}

    host = os.getenv("ORACLE_HOST")
    port = os.getenv("ORACLE_PORT", "1521")
    sid = os.getenv("ORACLE_SID")
    service_name = os.getenv("ORACLE_SERVICE_NAME")

    if user and password and host and (sid or service_name):
        connect_data: dict[str, Any] = {"host": host, "port": int(port)}
        if service_name:
            connect_data["service_name"] = service_name
        else:
            connect_data["sid"] = sid

        return {
            "user": user,
            "password": password,
            "dsn": oracledb.makedsn(**connect_data),
        }

    raise RuntimeError(
        "Configuracao Oracle ausente. Use DB_USER, DB_PASSWORD e DB_DSN "
        "ou ORACLE_USER, ORACLE_PASSWORD, ORACLE_HOST, ORACLE_PORT e "
        "ORACLE_SERVICE_NAME/ORACLE_SID."
    )


@contextmanager
def get_connection():
    connection = oracledb.connect(**oracle_config())
    try:
        yield connection
    finally:
        connection.close()


def fetch_rows(cursor: oracledb.Cursor) -> list[dict[str, Any]]:
    columns = [item[0].lower() for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def load_dashboard_data() -> dict[str, Any]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(SELECT_PARTICIPANTS_SQL)
                participants = fetch_rows(cursor)

                cursor.execute(SELECT_AUDIT_LOGS_SQL)
                audit_logs = fetch_rows(cursor)
            except oracledb.DatabaseError as exc:
                error, = exc.args
                raise RuntimeError(
                    f"Erro Oracle ao carregar dashboard: {error.code} - {error.message}"
                ) from exc

    pending = [row for row in participants if row["status"] == "PENDING"]
    cancelled = [row for row in participants if row["status"] == "CANCELLED"]
    for row in audit_logs:
        event_date = row.get("data")
        row["data_evento"] = (
            event_date.strftime("%d/%m/%Y %H:%M:%S") if event_date else ""
        )

    return {
        "participants": participants,
        "pending": pending,
        "audit_logs": audit_logs,
        "load_error": None,
        "stats": {
            "total_participants": len(participants),
            "total_pending": len(pending),
            "cancelled_count": len(cancelled),
            "audit_count": len(audit_logs),
        },
    }


def run_fraud_scan() -> tuple[int, str]:
    before = load_dashboard_data()
    cancelled_before = before["stats"]["cancelled_count"]

    with get_connection() as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(FRAUD_SCAN_PLSQL)
                connection.commit()
            except oracledb.DatabaseError as exc:
                connection.rollback()
                error, = exc.args
                raise RuntimeError(
                    f"Erro Oracle ao executar a varredura: {error.code} - {error.message}"
                ) from exc

    after = load_dashboard_data()
    cancelled_after = after["stats"]["cancelled_count"]
    processed = max(cancelled_after - cancelled_before, 0)
    return processed, "Varredura executada com sucesso usando PL/SQL embutido no Python."


@app.route("/", methods=["GET"])
def index():
    try:
        dashboard = load_dashboard_data()
    except RuntimeError as exc:
        flash(str(exc), "error")
        dashboard = {
            "participants": [],
            "pending": [],
            "audit_logs": [],
            "load_error": str(exc),
            "stats": {
                "total_participants": "-",
                "total_pending": "-",
                "cancelled_count": "-",
                "audit_count": "-",
            },
        }

    return render_template("dashboard.html", **dashboard)


@app.route("/scan", methods=["POST"])
def scan():
    try:
        processed_count, message = run_fraud_scan()
        flash(
            f"{message} Cancelamentos detectados nesta execucao: {processed_count}.",
            "success",
        )
    except RuntimeError as exc:
        flash(str(exc), "error")
    except Exception as exc:  # pragma: no cover
        flash(f"Erro inesperado na aplicacao: {exc}", "error")

    return redirect(url_for("index"))


app = app
