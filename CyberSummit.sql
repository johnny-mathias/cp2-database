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

    DBMS_OUTPUT.PUT_LINE('Total de inscrições canceladas: ' || v_count);

EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        DBMS_OUTPUT.PUT_LINE('Erro: ' || SQLERRM);
END;
/
