from flask import Flask, jsonify, redirect, render_template, request, url_for
import oracledb
import os


app = Flask(__name__)

HTML = """ 
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <title>Global Cyber Summit</title>

  <style>
    body { font-family: Arial; background: #f4f7fb; }
    .container { max-width: 1000px; margin: auto; padding: 20px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 10px; border-bottom: 1px solid #ccc; }
    .btn { padding: 10px 15px; border: none; cursor: pointer; }
    .primary { background: #0d6efd; color: white; }
    .danger { background: #cf2f4a; color: white; }
    .status { margin: 10px 0; font-weight: bold; }
  </style>
</head>

<body>
<div class="container">
  <h1>Global Cyber Summit</h1>

  <form action="/processar" method="post">
    <button class="btn primary">Executar varredura</button>
  </form>

  <form action="/resetar" method="post">
    <button class="btn danger">Resetar</button>
  </form>

  {% if status_message %}
    <div class="status">{{ status_message }}</div>
  {% endif %}

  <h2>Estatisticas</h2>
  <p>Total: {{ data.stats.total }}</p>
  <p>Pendentes: {{ data.stats.pendentes }}</p>
  <p>Canceladas: {{ data.stats.canceladas }}</p>
  <p>Confirmadas: {{ data.stats.confirmadas }}</p>

  <h2>Inscricoes</h2>
  <table>
    <tr>
      <th>ID</th><th>Nome</th><th>Email</th>
      <th>Trust</th><th>Status</th>
    </tr>
    {% for i in data.inscricoes %}
    <tr>
      <td>{{ i.id }}</td>
      <td>{{ i.nome }}</td>
      <td>{{ i.email }}</td>
      <td>{{ i.trust_score }}</td>
      <td>{{ i.status }}</td>
    </tr>
    {% endfor %}
  </table>

  <h2>Logs</h2>
  {% for log in data.logs %}
    <p>#{{ log.inscricao_id }} - {{ log.motivo }}</p>
  {% endfor %}

</div>
</body>
</html>
"""


def get_conn():
    print("[DEBUG] Abrindo conexao Oracle...")
    conn = oracledb.connect(
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dsn=os.environ["DB_DSN"],
    )
    print("[DEBUG] Conexao Oracle aberta com sucesso.")
    return conn


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
    print(f"[DEBUG] stats_row: {stats_row}")
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
    print(f"[DEBUG] Total de inscricoes carregadas: {len(inscricoes)}")
    if inscricoes:
        print(f"[DEBUG] Primeira inscricao: {inscricoes[0]}")
    else:
        print("[DEBUG] Nenhuma inscricao retornada pela query.")

    cur.execute(
        """
        SELECT id, inscricao_id, motivo, TO_CHAR(data, 'DD/MM/YYYY HH24:MI:SS')
        FROM LOG_AUDITORIA
        ORDER BY id DESC
        """
    )
    logs = cur.fetchall()
    print(f"[DEBUG] Total de logs carregados: {len(logs)}")
    if logs:
        print(f"[DEBUG] Primeiro log: {logs[0]}")
    else:
        print("[DEBUG] Nenhum log retornado pela query.")

    cur.close()
    conn.close()
    return stats, inscricoes, logs


def serialize_dashboard_data(stats, inscricoes, logs):
    return {
        "stats": stats,
        "inscricoes": [
            {
                "id": item[0],
                "nome": item[1],
                "email": item[2],
                "prioridade": item[3],
                "trust_score": item[4],
                "status": item[5],
                "valor_pago": float(item[6]) if item[6] is not None else 0.0,
                "tipo": item[7],
            }
            for item in inscricoes
        ],
        "logs": [
            {
                "id": log[0],
                "inscricao_id": log[1],
                "motivo": log[2],
                "data": log[3],
            }
            for log in logs
        ],
    }


@app.route("/")
def index():
    status_message = request.args.get("status_message", "")
    status_type = request.args.get("status_type", "")
    print("[DEBUG] Rota '/' acionada.")
    stats, inscricoes, logs = fetch_dashboard_data()
    print(
        "[DEBUG] Renderizando template com "
        f"{len(inscricoes)} inscricoes e {len(logs)} logs."
    )

    return render_template_string(
        HTML,
        data=serialize_dashboard_data(stats, inscricoes, logs),
        status_message=status_message,
        status_type=status_type,
)


@app.route("/dados")
def dados():
    print("[DEBUG] Rota '/dados' acionada.")
    stats, inscricoes, logs = fetch_dashboard_data()
    payload = serialize_dashboard_data(stats, inscricoes, logs)
    print(
        "[DEBUG] Retornando JSON com "
        f"{len(payload['inscricoes'])} inscricoes e {len(payload['logs'])} logs."
    )
    return jsonify(payload)


@app.route("/processar", methods=["POST"])
def processar():
    conn = get_conn()
    cur = conn.cursor()

    cancelled = cur.var(oracledb.NUMBER)
    penalized = cur.var(oracledb.NUMBER)
    logs = cur.var(oracledb.NUMBER)

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
            END;
            """,
            canceladas=cancelled,
            penalizados=penalized,
            logs=logs,
        )

        conn.commit()

        message = (
            f"{int(cancelled.getvalue())} canceladas | "
            f"{int(penalized.getvalue())} penalizados | "
            f"{int(logs.getvalue())} logs"
        )
        status_type = "success"

    except oracledb.DatabaseError as e:
        conn.rollback()
        error, = e.args
        message = f"Erro {error.code}"
        status_type = "error"

    finally:
        cur.close()
        conn.close()

    return redirect(url_for("index", status_message=message, status_type=status_type))


@app.route("/resetar", methods=["POST"])
def resetar():
    conn = get_conn()
    cur = conn.cursor()
    print("[DEBUG] Rota '/resetar' acionada.")

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
        print("[DEBUG] Reset da demonstracao executado com sucesso.")
        message = "Base restaurada para um estado simples de demonstracao."
        status_type = "success"
    except oracledb.DatabaseError as exc:
        conn.rollback()
        error, = exc.args
        print(f"[DEBUG] Erro Oracle em /resetar: {error.code} - {error.message}")
        message = f"Erro Oracle {error.code}: {error.message}"
        status_type = "error"
    finally:
        cur.close()
        conn.close()

    return redirect(url_for("index", status_message=message, status_type=status_type))


app = app
