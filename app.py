from flask import Flask, render_template, request, redirect, url_for
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from datetime import datetime
import sqlite3
import os
import re

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "avaliacoes.db")
PASTA_RELATORIOS = os.path.join(BASE_DIR, "relatorios")
os.makedirs(PASTA_RELATORIOS, exist_ok=True)

empresa_id_atual = None

def conectar_db():
    return sqlite3.connect(DB_NAME)

def criar_tabelas():
    conn = conectar_db()
    c = conn.cursor()
    # =========================
    # CONTROLE DE MIGRAÇÕES
    # =========================
    c.execute("""
        CREATE TABLE IF NOT EXISTS controle (
            chave TEXT PRIMARY KEY
        )
    """)
    # =========================
    # EMPRESA
    # =========================
    c.execute("""
        CREATE TABLE IF NOT EXISTS empresa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            data TEXT
        )
    """)
    # =========================
    # DIMENSÕES (COPSOQ)
    # =========================
    c.execute("""
        CREATE TABLE IF NOT EXISTS dimensao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        )
    """)
    # =========================
    # PARTICIPANTE
    # =========================
    c.execute("""
        CREATE TABLE IF NOT EXISTS participante (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL,
            data TEXT,
            FOREIGN KEY (empresa_id) REFERENCES empresa(id)
        )
    """)
    # =========================
    # PERGUNTAS
    # escala agora carrega o SENTIDO
    # (frequencia_crescente, grau_decrescente, etc.)
    # =========================
    c.execute("""
        CREATE TABLE IF NOT EXISTS pergunta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dimensao_id INTEGER NOT NULL,
            texto TEXT NOT NULL,
            escala TEXT NOT NULL,
            UNIQUE (dimensao_id, texto),
            FOREIGN KEY (dimensao_id) REFERENCES dimensao(id)
        )
    """)
    # =========================
    # RESPOSTAS
    # valor JÁ NORMALIZADO (1–5 ou 1–4)
    # =========================
    c.execute("""
        CREATE TABLE IF NOT EXISTS resposta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            participante_id INTEGER NOT NULL,
            pergunta_id INTEGER NOT NULL,
            valor INTEGER NOT NULL,
            FOREIGN KEY (participante_id) REFERENCES participante(id),
            FOREIGN KEY (pergunta_id) REFERENCES pergunta(id)
        )
    """)

    # =========================
    # RELATÓRIOS GERADOS
    # =========================
    c.execute("""
        CREATE TABLE IF NOT EXISTS relatorio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL,
            caminho_pdf TEXT NOT NULL,
            data TEXT,
            FOREIGN KEY (empresa_id) REFERENCES empresa(id)
        )
    """)

    # =========================
    # EVENTOS CRÍTICOS
    # (sem pontuação COPSOQ)
    # =========================
    c.execute("""
        CREATE TABLE IF NOT EXISTS evento_origem (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            participante_id INTEGER NOT NULL,
            pergunta_id INTEGER NOT NULL,
            origem TEXT NOT NULL,
            FOREIGN KEY (participante_id) REFERENCES participante(id),
            FOREIGN KEY (pergunta_id) REFERENCES pergunta(id)
        )
    """)

    conn.commit()
    conn.close()

def migrar_perguntas():
    conn = conectar_db()
    c = conn.cursor()

    # 🔒 Evita migração duplicada
    c.execute("SELECT 1 FROM controle WHERE chave = 'perguntas_migradas'")
    if c.fetchone():
        conn.close()
        return

    DIMENSOES = {
        # ==================================================
        # 01 — DEMANDAS DE TRABALHO
        # Quanto maior a frequência, MAIOR o risco
        # ==================================================
        "Demandas de Trabalho": [
            ("Você atrasa a entrega do seu trabalho?", "frequencia_crescente"),
            ("O tempo para realizar as suas tarefas no trabalho é suficiente?", "frequencia_decrescente"),
            ("É necessário manter um ritmo acelerado no trabalho?", "frequencia_crescente"),
            ("Você trabalha em ritmo acelerado ao longo de toda jornada?", "frequencia_crescente"),
            ("Seu trabalho coloca você em situações emocionalmente desgastantes?", "frequencia_crescente"),
            ("Você tem que lidar com os problemas pessoais de outras pessoas como parte do seu trabalho?", "frequencia_crescente"),
        ],

        # ==================================================
        # 02 — INFLUÊNCIA E DESENVOLVIMENTO
        # Quanto maior o grau, MENOR o risco
        # ==================================================
        "Influência e possibilidade de desenvolvimento": [
            ("Você tem um alto grau de influência nas decisões sobre o seu trabalho?", "grau_decrescente"),
            ("Você pode interferir na quantidade de trabalho atribuída a você?", "grau_decrescente"),
            ("Você tem a possibilidade de aprender coisas novas através do seu trabalho?", "grau_decrescente"),
            ("Seu trabalho exige que você tome iniciativas?", "grau_decrescente"),
        ],

        # ==================================================
        # 03 — SIGNIFICADO DO TRABALHO
        # ==================================================
        "Significado do trabalho e comprometimento": [
            ("Seu trabalho é significativo?", "grau_decrescente"),
            ("Você sente que o trabalho que faz é importante?", "grau_decrescente"),
            ("Você sente que o seu local de trabalho é muito importante para você?", "grau_decrescente"),
            ("Você recomendaria a um amigo que se candidatasse a uma vaga no seu local de trabalho?", "grau_decrescente"),
        ],

        # ==================================================
        # 04 — RELAÇÕES INTERPESSOAIS
        # ==================================================
        "Relações Interpessoais": [
            ("No seu local de trabalho, você é informado antecipadamente sobre decisões importantes, mudanças ou planos para o futuro?", "grau_decrescente"),
            ("Você recebe toda a informação necessária para fazer bem o seu trabalho?", "grau_decrescente"),
            ("O seu trabalho é reconhecido e valorizado pelos seus superiores?", "grau_decrescente"),
            ("Você é tratado de forma justa no seu local de trabalho?", "grau_decrescente"),
            ("O seu trabalho tem objetivos/metas claros(as)?", "grau_decrescente"),
            ("Você sabe exatamente o que se espera de você no trabalho?", "grau_decrescente"),
        ],

        # ==================================================
        # 05 — LIDERANÇA
        # ==================================================
        "Liderança": [
            ("Você diria que seu superior imediato dá alta prioridade à satisfação com o trabalho?", "grau_decrescente"),
            ("Você diria que seu superior imediato é bom no planejamento do trabalho?", "grau_decrescente"),
            ("Com que frequência seu superior imediato está disposto a ouvir os seus problemas no trabalho?", "frequencia_decrescente"),
            ("Com que frequência você recebe ajuda e suporte do seu superior imediato?", "frequencia_decrescente"),
        ],

        # ==================================================
        # 06 — SATISFAÇÃO GERAL
        # ==================================================
        "Interface trabalho-indivíduo": [
            ("Qual o seu nível de satisfação com o seu trabalho como um todo, considerando todos os aspectos?", "satisfacao_decrescente"),
        ],

        # ==================================================
        # 07 — CONFLITO TRABALHO–VIDA
        # Quanto maior o impacto, MAIOR o risco
        # ==================================================
        "Conflitos família e trabalho": [
            ("Você sente que o seu trabalho consome tanto sua energia que ele tem um efeito negativo na sua vida particular?", "impacto_negativo_crescente"),
            ("Você sente que o seu trabalho ocupa tanto tempo que ele tem um efeito negativo na sua vida particular?", "impacto_negativo_crescente"),
        ],

        # ==================================================
        # 08 — VALORES ORGANIZACIONAIS
        # ==================================================
        "Valores no local de trabalho": [
            ("Você pode confiar nas informações que vêm dos seus superiores?", "grau_decrescente"),
            ("Os seus superiores confiam que os funcionários farão bem seu trabalho?", "grau_decrescente"),
            ("Os conflitos são resolvidos de forma justa?", "grau_decrescente"),
            ("O trabalho é distribuído de forma justa?", "grau_decrescente"),
        ],

        # ==================================================
        # 09 — SAÚDE GERAL
        # ==================================================
        "Saúde geral": [
            ("Em geral, você diria que a sua saúde é:", "saude_decrescente"),
        ],

        # ==================================================
        # 10 — BURNOUT E ESTRESSE
        # ==================================================
        "Burnout e Estresse": [
            ("Com que frequência você se sente fisicamente esgotado?", "frequencia_crescente"),
            ("Com que frequência você se sente emocionalmente esgotado?", "frequencia_crescente"),
            ("Com que frequência você se sente estressado?", "frequencia_crescente"),
            ("Com que frequência você se sente irritado?", "frequencia_crescente"),
        ],

        # ==================================================
        # 11 — COMPORTAMENTOS OFENSIVOS (EVENTOS)
        # NÃO entram no cálculo COPSOQ
        # ==================================================
        "Comportamentos ofensivos": [
            ("Você foi exposto a atenção sexual indesejada no seu local de trabalho durante os últimos 12 meses?", "evento"),
            ("Você foi exposto a ameaças de violência no seu local de trabalho nos últimos 12 meses?", "evento"),
            ("Você foi exposto a violência física em seu local de trabalho durante os últimos 12 meses?", "evento"),
            ("Você foi exposto a bullying no seu local de trabalho durante os últimos 12 meses?", "evento"),
        ],
    }

    # =========================
    # INSERÇÃO NO BANCO
    # =========================
    for nome_dimensao, perguntas in DIMENSOES.items():
        c.execute("INSERT INTO dimensao (nome) VALUES (?)", (nome_dimensao,))
        c.execute("SELECT id FROM dimensao WHERE nome = ?", (nome_dimensao,))
        dimensao_id = c.fetchone()[0]

        for texto, escala in perguntas:
            c.execute("""
                INSERT INTO pergunta (dimensao_id, texto, escala)
                VALUES (?, ?, ?)
            """, (dimensao_id, texto, escala))

    c.execute("INSERT INTO controle (chave) VALUES ('perguntas_migradas')")
    conn.commit()
    conn.close()

ESCALAS = {
    "frequencia_crescente": [
        ("Nunca", 1),
        ("Raramente", 2),
        ("Às vezes", 3),
        ("Frequentemente", 4),
        ("Sempre", 5),
    ],

    "frequencia_decrescente": [
        ("Sempre", 1),
        ("Frequentemente", 2),
        ("Às vezes", 3),
        ("Raramente", 4),
        ("Nunca", 5),
    ],
    # GRAU / INTENSIDADE
    "grau_crescente": [
        ("Muito pouco", 1),
        ("Pouco", 2),
        ("De certa forma", 3),
        ("Em boa parte", 4),
        ("Em grande parte", 5),
    ],

    "grau_decrescente": [
        ("Em grande parte", 1),
        ("Em boa parte", 2),
        ("De certa forma", 3),
        ("Pouco", 4),
        ("Muito pouco", 5),
    ],
    # SATISFAÇÃO
    "satisfacao_crescente": [
        ("Muito insatisfeito", 1),
        ("Insatisfeito", 2),
        ("Satisfeito", 3),
        ("Muito satisfeito", 4),
    ],

    "satisfacao_decrescente": [
        ("Muito satisfeito", 1),
        ("Satisfeito", 2),
        ("Insatisfeito", 3),
        ("Muito insatisfeito", 4),
    ],
    # SAÚDE GERAL
    "saude_crescente": [
        ("Ruim", 1),
        ("Razoável", 2),
        ("Boa", 3),
        ("Muito boa", 4),
        ("Excelente", 5),
    ],

    "saude_decrescente": [
        ("Excelente", 1),
        ("Muito boa", 2),
        ("Boa", 3),
        ("Razoável", 4),
        ("Ruim", 5),
    ],
    # IMPACTO NEGATIVO TRABALHO → VIDA
    "impacto_negativo_crescente": [
        ("Não, realmente não", 1),
        ("Sim, mas muito pouco", 2),
        ("Sim, até certo ponto", 3),
        ("Sim, com certeza", 4),
    ],

    "impacto_negativo_decrescente": [
        ("Sim, com certeza", 1),
        ("Sim, até certo ponto", 2),
        ("Sim, mas muito pouco", 3),
        ("Não, realmente não", 4),
    ],
    
    "evento": [
        ("Não", 0),
        ("Sim", 1),
]
}

# FUNÇÕES AUXILIARES
def nome_seguro(texto):
    return re.sub(r"[^\w\-]", "_", texto.lower())

def calcular_medias_copsoq(respostas_por_dimensao):
    resultados = {}
    for dimensao, respostas in respostas_por_dimensao.items():
        medias_individuais = [sum(r) / len(r) for r in respostas]
        resultados[dimensao] = round(sum(medias_individuais) / len(medias_individuais), 2)
    return resultados

def classificar_risco(media):
    if media <= 2.33:
        return "🟢 Situação Favorável - Baixo/Nenhum risco - Condição psicossocial boa. Manter boas práticas."
    elif media <= 3.66:
        return "🟡 Risco Intermediário - Médio Risco - Moderado(pode indicar início de problemas. Monitorar, promover ações de suporte)."
    else:
        return "🔴 Risco para a Saúde - Alto risco - Intervenção imediata, revisão organizacional. Alto risco psicossocial."

def gerar_pdf(empresa, total, resultados, eventos):
    nome = nome_seguro(empresa)
    data = datetime.now().strftime("%Y%m%d_%H%M")
    caminho = os.path.join(PASTA_RELATORIOS, f"relatorio_{nome}_{data}.pdf")

    estilos = getSampleStyleSheet()
    elementos = []

    # =============================
    # CAPA
    # =============================
    elementos.append(Paragraph("Relatório de Avaliação Psicossocial", estilos["Title"]))
    elementos.append(Spacer(1, 20))
    elementos.append(Paragraph(f"<b>Empresa:</b> {empresa}", estilos["Normal"]))
    elementos.append(Paragraph(f"<b>Participantes:</b> {total}", estilos["Normal"]))
    elementos.append(Spacer(1, 30))

    # =============================
    # DIMENSÕES COM PONTUAÇÃO
    # =============================
    for dim, media in resultados.items():
        elementos.append(Paragraph(dim, estilos["Heading2"]))
        elementos.append(Spacer(1, 8))

        elementos.append(
            Paragraph(f"<b>Média da dimensão:</b> {media}", estilos["Normal"])
        )

        elementos.append(
            Paragraph(classificar_risco(media), estilos["Normal"])
        )

        elementos.append(Spacer(1, 20))

    # =============================
    # DIMENSÃO 11 — EVENTOS (SEMPRE EXIBIR)
    # =============================
    elementos.append(Spacer(1, 30))
    elementos.append(
        Paragraph("Comportamentos Ofensivos e Eventos Críticos", estilos["Heading1"])
    )
    elementos.append(Spacer(1, 15))

    elementos.append(
        Paragraph(
            "⚠️ Os itens abaixo representam ocorrência de eventos e "
            "não geram pontuação ou classificação de risco.",
            estilos["Italic"]
        )
    )

    elementos.append(Spacer(1, 10))

    if eventos:
        for evento, total_eventos in eventos.items():
            elementos.append(
                Paragraph(
                    f"• <b>{evento}</b>: {total_eventos} ocorrência(s)",
                    estilos["Normal"]
                )
            )
    else:
        elementos.append(
            Paragraph(
                "• Não foram registradas ocorrências de comportamentos ofensivos "
                "ou eventos críticos no período avaliado.",
                estilos["Normal"]
            )
        )
    # =============================
    # GERA PDF
    # =============================
    SimpleDocTemplate(caminho, pagesize=A4).build(elementos)
    return caminho
# ==================================================
# ROTAS
# ==================================================
@app.route("/", methods=["GET", "POST"])
def empresa():
    global empresa_id_atual
    if request.method == "POST":
        nome = request.form["empresa"]
        conn = conectar_db()
        c = conn.cursor()
        c.execute("INSERT INTO empresa (nome, data) VALUES (?, ?)",
                  (nome, datetime.now().strftime("%Y-%m-%d %H:%M")))
        empresa_id_atual = c.lastrowid
        conn.commit()
        conn.close()
        return redirect(url_for("questionario"))
    return render_template("empresa.html")

@app.route("/novo")
def novo():
    return redirect(url_for("questionario"))


@app.route("/questionario", methods=["GET", "POST"])
def questionario():

    if request.method == "POST":
        conn = conectar_db()
        c = conn.cursor()

        # Cria participante
        c.execute(
            "INSERT INTO participante (empresa_id, data) VALUES (?, ?)",
            (empresa_id_atual, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        participante_id = c.lastrowid

        for campo, valor in request.form.items():

            if not campo.startswith("pergunta_"):
                continue

            pergunta_id = int(campo.replace("pergunta_", ""))
            resposta_valor = int(valor)

            # Descobre o tipo da pergunta
            c.execute("SELECT escala FROM pergunta WHERE id = ?", (pergunta_id,))
            escala = c.fetchone()[0]

            # =========================
            # PERGUNTA NORMAL (COPSOQ)
            # =========================
            if escala != "evento":
                c.execute(
                    """
                    INSERT INTO resposta (participante_id, pergunta_id, valor)
                    VALUES (?, ?, ?)
                    """,
                    (participante_id, pergunta_id, resposta_valor)
                )

            # =========================
            # EVENTO (registro apenas)
            # =========================
            elif resposta_valor > 0:
                origens = request.form.getlist(f"origem_{pergunta_id}")
                for origem in origens:
                    c.execute(
                        """
                        INSERT INTO evento_origem
                        (participante_id, pergunta_id, origem)
                        VALUES (?, ?, ?)
                        """,
                        (participante_id, pergunta_id, origem)
                    )

        conn.commit()
        conn.close()
        return redirect(url_for("continuar"))

    # ==========================
    # GET → carrega perguntas
    # ==========================
    conn = conectar_db()
    c = conn.cursor()

    c.execute("""
        SELECT id, texto, escala
        FROM pergunta
        ORDER BY id
    """)
    perguntas = c.fetchall()

    conn.close()

    return render_template(
        "questionario.html",
        perguntas=perguntas,
        ESCALAS=ESCALAS
    )

@app.route("/continuar")
def continuar():
    if empresa_id_atual is None:
        return redirect(url_for("empresa"))

    conn = conectar_db()
    c = conn.cursor()

    # Busca nome da empresa
    c.execute(
        "SELECT nome FROM empresa WHERE id = ?",
        (empresa_id_atual,)
    )
    row = c.fetchone()

    if row is None:
        conn.close()
        return redirect(url_for("empresa"))

    empresa = row[0]

    # Conta participantes
    c.execute(
        "SELECT COUNT(*) FROM participante WHERE empresa_id = ?",
        (empresa_id_atual,)
    )
    total = c.fetchone()[0]

    conn.close()

    return render_template(
        "continuar.html",
        empresa=empresa,
        total=total
    )

@app.route("/finalizar")
def finalizar():
    conn = conectar_db()
    c = conn.cursor()

    # =============================
    # 1️⃣ Respostas COPSOQ
    # =============================
    c.execute("""
        SELECT
            pa.id,
            d.nome,
            r.valor
        FROM resposta r
        JOIN pergunta p ON r.pergunta_id = p.id
        JOIN dimensao d ON p.dimensao_id = d.id
        JOIN participante pa ON r.participante_id = pa.id
        WHERE pa.empresa_id = ?
        ORDER BY d.id, pa.id
    """, (empresa_id_atual,))
    dados = c.fetchall()

    # =============================
    # 2️⃣ Eventos
    # =============================
    c.execute("""
        SELECT
            p.texto,
            COUNT(*) 
        FROM evento_origem eo
        JOIN pergunta p ON eo.pergunta_id = p.id
        JOIN participante pa ON eo.participante_id = pa.id
        WHERE pa.empresa_id = ?
        GROUP BY p.texto
    """, (empresa_id_atual,))
    eventos = dict(c.fetchall())

    # =============================
    # 3️⃣ Empresa e participantes
    # =============================
    c.execute("SELECT nome FROM empresa WHERE id = ?", (empresa_id_atual,))
    empresa_nome = c.fetchone()[0]

    c.execute(
        "SELECT COUNT(*) FROM participante WHERE empresa_id = ?",
        (empresa_id_atual,)
    )
    total_participantes = c.fetchone()[0]

    conn.close()

    # =============================
    # 4️⃣ Agrupamento COPSOQ
    # =============================
    respostas_por_dimensao = {}

    for participante_id, dimensao, valor in dados:
        respostas_por_dimensao \
            .setdefault(dimensao, {}) \
            .setdefault(participante_id, []) \
            .append(valor)

    medias_dimensao = {}
    for dimensao, participantes in respostas_por_dimensao.items():
        medias_individuais = [
            sum(respostas) / len(respostas)
            for respostas in participantes.values()
        ]
        medias_dimensao[dimensao] = round(
            sum(medias_individuais) / len(medias_individuais), 2
        )

    # =============================
    # 5️⃣ PDF
    # =============================
    caminho_pdf = gerar_pdf(
        empresa_nome,
        total_participantes,
        medias_dimensao,
        eventos
    )

    # =============================
    # 6️⃣ Salva relatório
    # =============================
    conn = conectar_db()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO relatorio (empresa_id, caminho_pdf, data)
        VALUES (?, ?, ?)
        """,
        (empresa_id_atual, caminho_pdf, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()
    conn.close()

    return render_template("encerramento.html")


criar_tabelas()
migrar_perguntas()
if __name__ == "__main__":
    app.run(debug=True)