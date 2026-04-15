from contextlib import contextmanager
from pathlib import Path
from typing import Any

import oracledb
from flask import Flask, flash, redirect, render_template, url_for


BASE_DIR = Path(__file__).resolve().parent
TEST_SQL_PATH = BASE_DIR / "teste.sql"
PLSQL_PATH = BASE_DIR / "CyberSummit.sql"

app = Flask(__name__)
app.secret_key = "global-cyber-summit"


def oracle_config() -> dict[str, str]:
    return {
        "user": "rm566516",
        "password": "210806",
        "dsn": oracledb.makedsn("oracle.fiap.com.br", 1521, sid="orcl"),
    }


@contextmanager
def get_connection():
    connection = oracledb.connect(**oracle_config())
    try:
        yield connection
    finally:
        connection.close()


def split_sql_statements(content: str) -> list[str]:
    statements = []
    current = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "/":
            if current:
                statements.append("\n".join(current).strip())
                current = []
            continue

        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current).strip().rstrip(";"))
            current = []

    if current:
        statements.append("\n".join(current).strip())

    return [statement for statement in statements if statement]


def read_plsql_block(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    cleaned_lines = [line for line in lines if line.strip() != "/"]
    return "\n".join(cleaned_lines).strip()


def fetch_rows(cursor: oracledb.Cursor) -> list[dict[str, Any]]:
    columns = [item[0].lower() for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def load_dashboard_data() -> dict[str, Any]:
    select_participants, select_logs = split_sql_statements(
        TEST_SQL_PATH.read_text(encoding="utf-8")
    )

    with get_connection() as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(select_participants)
                participants = fetch_rows(cursor)

                cursor.execute(select_logs)
                audit_logs = fetch_rows(cursor)
            except oracledb.DatabaseError as exc:
                error, = exc.args
                raise RuntimeError(
                    f"Erro Oracle ao carregar dashboard: {error.code} - {error.message}"
                ) from exc

    pending = [row for row in participants if row["status"] == "PENDING"]
    cancelled = [row for row in participants if row["status"] == "CANCELLED"]
    for row in audit_logs:
        if "data" in row and row["data"] is not None:
            row["data_evento"] = row["data"].strftime("%d/%m/%Y %H:%M:%S")
        else:
            row["data_evento"] = ""

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
    plsql_block = read_plsql_block(PLSQL_PATH)

    before = load_dashboard_data()
    cancelled_before = before["stats"]["cancelled_count"]

    with get_connection() as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(plsql_block)
                connection.commit()
            except oracledb.DatabaseError as exc:
                connection.rollback()
                error, = exc.args
                raise RuntimeError(
                    f"Erro Oracle: {error.code} - {error.message}"
                ) from exc

    after = load_dashboard_data()
    cancelled_after = after["stats"]["cancelled_count"]
    processed = max(cancelled_after - cancelled_before, 0)
    return processed, f"Varredura executada com sucesso usando {PLSQL_PATH.name}."


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
    return render_template("index.html", **dashboard)


@app.route("/scan", methods=["POST"])
def scan():
    try:
        processed_count, message = run_fraud_scan()
        flash(f"{message} Cancelamentos detectados nesta execucao: {processed_count}.", "success")
    except RuntimeError as exc:
        flash(str(exc), "error")
    except Exception as exc:  # pragma: no cover
        flash(f"Erro inesperado na aplicacao: {exc}", "error")

    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
