from flask import Flask, redirect, render_template_string, request, url_for
import oracledb
import os

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
INDEX_PATH = os.path.join(BASE_DIR, "index.html")

with open(INDEX_PATH, encoding="utf-8") as template_file:
    HTML = template_file.read()


def get_conn():
    return oracledb.connect(
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dsn=os.environ["DB_DSN"],
    )


def fetch_dashboard_data():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            COUNT(*) AS total_inscricoes,
            SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) AS pendentes,
            SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END) AS canceladas,
            SUM(CASE WHEN status = 'CONFIRMED' THEN 1 ELSE 0 END) AS confirmadas
        FROM INSCRICOES
        """
    )
    stats_row = cur.fetchone()
    stats = {
        "total": stats_row[0] or 0,
        "pendentes": stats_row[1] or 0,
        "canceladas": stats_row[2] or 0,
        "confirmadas": stats_row[3] or 0,
    }

    cur.execute(
        """
        SELECT
            i.id,
            u.nome,
            u.email,
            u.prioridade,
            u.trust_score,
            i.status,
            i.valor_pago,
            i.tipo
        FROM INSCRICOES i
        JOIN USUARIOS u ON u.id = i.usuario_id
        ORDER BY i.id
        """
    )
    inscricoes = cur.fetchall()

    cur.execute(
        """
        SELECT id, inscricao_id, motivo, TO_CHAR(data, 'DD/MM/YYYY HH24:MI:SS')
        FROM LOG_AUDITORIA
        ORDER BY id DESC
        """
    )
    logs = cur.fetchall()

    conn.close()
    return stats, inscricoes, logs


@app.route("/")
def index():
    status_message = request.args.get("status_message", "")
    status_type = request.args.get("status_type", "")
    stats, inscricoes, logs = fetch_dashboard_data()

    return render_template_string(
        HTML,
        stats=stats,
        inscricoes=inscricoes,
        logs=logs,
        status_message=status_message,
        status_type=status_type,
    )


@app.route("/processar", methods=["POST"])
def processar():
    conn = get_conn()
    cur = conn.cursor()

    cancelled_var = cur.var(oracledb.NUMBER)
    penalized_var = cur.var(oracledb.NUMBER)
    logs_var = cur.var(oracledb.NUMBER)

    try:
        cur.execute(
            """
            DECLARE
                CURSOR c_inscricoes IS
                    SELECT i.id, i.usuario_id, u.email
                    FROM INSCRICOES i
                    JOIN USUARIOS u ON u.id = i.usuario_id
                    WHERE i.status = 'PENDING'
                    FOR UPDATE OF i.status;

                v_id_inscricao INSCRICOES.ID%TYPE;
                v_usuario_id USUARIOS.ID%TYPE;
                v_email USUARIOS.EMAIL%TYPE;
                v_canceladas NUMBER := 0;
                v_penalizados NUMBER := 0;
                v_logs NUMBER := 0;
            BEGIN
                OPEN c_inscricoes;

                LOOP
                    FETCH c_inscricoes INTO v_id_inscricao, v_usuario_id, v_email;
                    EXIT WHEN c_inscricoes%NOTFOUND;

                    IF v_email LIKE '%@fake.com'
                       OR v_email LIKE '%@temp-mail%'
                       OR NOT REGEXP_LIKE(
                           v_email,
                           '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$'
                       )
                    THEN
                        UPDATE INSCRICOES
                        SET STATUS = 'CANCELLED'
                        WHERE CURRENT OF c_inscricoes;

                        UPDATE USUARIOS
                        SET TRUST_SCORE = GREATEST(TRUST_SCORE - 15, 0)
                        WHERE ID = v_usuario_id;

                        INSERT INTO LOG_AUDITORIA (ID, INSCRICAO_ID, MOTIVO, DATA)
                        VALUES (
                            LOG_AUDITORIA_SEQ.NEXTVAL,
                            v_id_inscricao,
                            'Inscricao cancelada por email suspeito: ' || v_email,
                            SYSDATE
                        );

                        v_canceladas := v_canceladas + 1;
                        v_penalizados := v_penalizados + 1;
                        v_logs := v_logs + 1;
                    END IF;
                END LOOP;

                CLOSE c_inscricoes;

                :canceladas := v_canceladas;
                :penalizados := v_penalizados;
                :logs := v_logs;
            EXCEPTION
                WHEN OTHERS THEN
                    IF c_inscricoes%ISOPEN THEN
                        CLOSE c_inscricoes;
                    END IF;
                    RAISE;
            END;
            """,
            canceladas=cancelled_var,
            penalizados=penalized_var,
            logs=logs_var,
        )
        conn.commit()

        message = (
            f"Varredura concluida: {int(cancelled_var.getvalue())} inscricoes canceladas, "
            f"{int(penalized_var.getvalue())} usuarios penalizados e "
            f"{int(logs_var.getvalue())} logs gerados."
        )
        status_type = "success"
    except oracledb.DatabaseError as exc:
        conn.rollback()
        error, = exc.args
        message = f"Erro Oracle {error.code}: {error.message}"
        status_type = "error"
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("index", status_message=message, status_type=status_type))


@app.route("/resetar", methods=["POST"])
def resetar():
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            BEGIN
                DELETE FROM LOG_AUDITORIA;

                UPDATE USUARIOS
                SET TRUST_SCORE = 100;

                UPDATE INSCRICOES i
                SET STATUS = CASE
                    WHEN i.status = 'CONFIRMED' THEN 'CONFIRMED'
                    ELSE 'PENDING'
                END;
            END;
            """
        )
        conn.commit()
        message = "Base restaurada para um estado simples de demonstracao."
        status_type = "success"
    except oracledb.DatabaseError as exc:
        conn.rollback()
        error, = exc.args
        message = f"Erro Oracle {error.code}: {error.message}"
        status_type = "error"
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("index", status_message=message, status_type=status_type))


app = app
