SELECT u.nome, u.email, u.trust_score, i.status
FROM USUARIOS u
JOIN INSCRICOES i ON u.id = i.usuario_id;

SELECT * FROM LOG_AUDITORIA;
