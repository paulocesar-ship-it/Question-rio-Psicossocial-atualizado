from flask import Flask, render_template, request, redirect, url_for
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from datetime import datetime
import sqlite3
import os
import re
# ==================================================
# APP
# ==================================================
app = Flask(__name__)
# ==================================================
# CAMINHOS
# ==================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "avaliacoes.db")
PASTA_RELATORIOS = os.path.join(BASE_DIR, "relatorios")
os.makedirs(PASTA_RELATORIOS, exist_ok=True)
# ==================================================
# CONTROLE SIMPLES DE SESSÃO
# ==================================================
empresa_id_atual = None
# ==================================================
# BANCO DE DADOS
# ==================================================
def conectar_db():
    return sqlite3.connect(DB_NAME)

def criar_tabelas():
    conn = conectar_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS empresa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            data TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS dimensao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS participante (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER,
            data TEXT,
            FOREIGN KEY(empresa_id) REFERENCES empresa(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS pergunta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dimensao_id INTEGER NOT NULL,
            texto TEXT NOT NULL,
            escala TEXT NOT NULL,
            invertida INTEGER DEFAULT 0,
            valor_maximo INTEGER DEFAULT 4,
            UNIQUE(dimensao_id, texto),
            FOREIGN KEY(dimensao_id) REFERENCES dimensao(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS resposta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            participante_id INTEGER,
            pergunta_id INTEGER,
            valor INTEGER,
            FOREIGN KEY(participante_id) REFERENCES participante(id),
            FOREIGN KEY(pergunta_id) REFERENCES pergunta(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS relatorio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER,
            caminho_pdf TEXT,
            data TEXT
        )
    """)

    conn.commit()
    conn.close()
# ==================================================
# MIGRAÇÃO DE PERGUNTAS
# ==================================================
def migrar_perguntas():
    conn = conectar_db()
    c = conn.cursor()

    # Dimensão única (como você pediu, mesma abordagem atual)
    c.execute(
        "INSERT OR IGNORE INTO dimensao (nome) VALUES (?)",
        ("Demandas de Trabalho",)
    )
    c.execute(
        "SELECT id FROM dimensao WHERE nome = ?",
        ("Demandas de Trabalho",)
    )
    dimensao_id = c.fetchone()[0]

    perguntas = [
        # 1 – Demandas quantitativas
        ("Você atrasa a entrega do seu trabalho?", "frequencia", 4, True),
        ("O tempo para realizar as suas tarefas no trabalho é suficiente?", "frequencia", 4, True),

        # 2 – Ritmo de trabalho
        ("É necessário manter um ritmo acelerado no trabalho?", "frequencia", 4, True),
        ("Você trabalha em ritmo acelerado ao longo de toda jornada?", "frequencia", 4, True),

        # 3 – Demandas emocionais
        ("Seu trabalho coloca você em situações emocionalmente desgastantes?", "frequencia", 4, True),
        ("Você tem que lidar com os problemas pessoais de outras pessoas como parte do seu trabalho?", "frequencia", 4, True),

        # 4 – Influência no trabalho
        ("Você tem um alto grau de influência nas decisões sobre o seu trabalho?", "frequencia", 4, False),
        ("Você pode interferir na quantidade de trabalho atribuída a você?", "frequencia", 4, False),

        # 5 – Possibilidades de desenvolvimento
        ("Você tem a possibilidade de aprender coisas novas através do seu trabalho?", "grau", 4, False),
        ("Seu trabalho exige que você tome iniciativas?", "grau", 4, False),

        # 6 – Significado do trabalho
        ("Seu trabalho é significativo?", "grau", 4, False),
        ("Você sente que o trabalho que faz é importante?", "grau", 4, False),

        # 7 – Comprometimento com o local de trabalho
        ("Você sente que o seu local de trabalho é muito importante para você?", "grau", 4, False),
        ("Você recomendaria a um amigo que se candidatasse a uma vaga no seu local de trabalho?", "grau", 4, False),

        # 8 – Previsibilidade
        ("Você é informado antecipadamente sobre decisões importantes ou mudanças?", "grau", 4, False),
        ("Você recebe toda a informação necessária para fazer bem o seu trabalho?", "grau", 4, False),

        # 9 – Reconhecimento
        ("O seu trabalho é reconhecido e valorizado pelos seus superiores?", "grau", 4, False),
        ("Você é tratado de forma justa no seu local de trabalho?", "grau", 4, False),

        # 10 – Clareza de papel
        ("O seu trabalho tem objetivos claros?", "grau", 4, False),
        ("Você sabe exatamente o que se espera de você no trabalho?", "grau", 4, False),

        # 11 – Qualidade da liderança
        ("Seu superior imediato dá alta prioridade à satisfação com o trabalho?", "grau", 4, False),
        ("Seu superior imediato é bom no planejamento do trabalho?", "grau", 4, False),

        # 12 – Apoio do superior
        ("Com que frequência seu superior imediato ouve seus problemas?", "frequencia", 4, False),
        ("Com que frequência você recebe ajuda do seu superior imediato?", "frequencia", 4, False),

        # 13 – Satisfação geral
        ("Qual o seu nível de satisfação com o trabalho como um todo?", "satisfacao", 3, False),

        # 14 – Conflito trabalho–vida privada
        ("Seu trabalho afeta negativamente sua vida particular por consumir muita energia?", "concordancia", 3, True),
        ("Seu trabalho afeta negativamente sua vida particular por ocupar muito tempo?", "concordancia", 3, True),

        # 15 – Confiança vertical
        ("Você pode confiar nas informações que vêm dos seus superiores?", "grau", 4, False),
        ("Os superiores confiam que os funcionários farão bem o trabalho?", "grau", 4, False),

        # 16 – Justiça organizacional
        ("Os conflitos são resolvidos de forma justa?", "grau", 4, False),
        ("O trabalho é distribuído de forma justa?", "grau", 4, False),

        # 17 – Saúde geral
        ("Em geral, como você avalia sua saúde?", "avaliacao_saude", 4, False),

        # 18 – Exaustão
        ("Com que frequência você se sente fisicamente esgotado?", "frequencia", 4, True),
        ("Com que frequência você se sente emocionalmente esgotado?", "frequencia", 4, True),

        # 19 – Estresse
        ("Com que frequência você se sente estressado?", "frequencia", 4, True),
        ("Com que frequência você se sente irritado?", "frequencia", 4, True),

        # 20 – Assédio sexual
        ("Você foi exposto a atenção sexual indesejada no seu local de trabalho durante os últimos 12 meses?", "exposicao", 4, True),

        # 21 – Ameaça de violência
        ("Você foi exposto a ameaças de violência no seu local de trabalho nos últimos 12 meses?", "exposicao", 4, True),

        # 22 – Violência física
        ("Você foi exposto a violência física em seu local de trabalho durante os últimos 12 meses?", "exposicao", 4, True),

        # 23 – Bullying
        ("Você foi exposto a bullying no seu local de trabalho nos últimos 12 meses?", "exposicao", 4, True),
    ]

    for texto, escala, valor_maximo, invertida in perguntas:
        c.execute(
            """
            INSERT OR IGNORE INTO pergunta
            (dimensao_id, texto, escala, invertida, valor_maximo)
            VALUES (?, ?, ?, ?, ?)
            """,
            (dimensao_id, texto, escala, int(invertida), valor_maximo)
        )

    conn.commit()
    conn.close()
# ==================================================
# ESCALAS
# ==================================================
ESCALAS = {
    "frequencia": [
        "Sempre",
        "Frequentemente",
        "Às vezes",
        "Raramente",
        "Nunca"
    ],

    "satisfacao": [
        "Muito satisfeito",
        "Satisfeito",
        "Insatisfeito",
        "Muito insatisfeito"
    ],

    "concordancia": [
        "Sim, com certeza",
        "Sim, até certo ponto",
        "Sim, mas muito pouco",
        "Não, realmente não"
    ],

    "avaliacao_saude": [
        "Excelente",
        "Muito boa",
        "Boa",
        "Razoável",
        "Ruim"
    ],

    "grau": [
        "Em grande parte",
        "Em boa parte",
        "De certa forma",
        "Pouco",
        "Muito pouco"
    ],

    "exposicao": [
        "Sim, várias vezes",
        "Sim, algumas vezes",
        "Sim, uma vez",
        "Não"
    ]
}
# ==================================================
# FUNÇÕES AUXILIARES
# ==================================================
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

def gerar_pdf(empresa, total, resultados):
    nome = nome_seguro(empresa)
    data = datetime.now().strftime("%Y%m%d_%H%M")
    caminho = os.path.join(PASTA_RELATORIOS, f"relatorio_{nome}_{data}.pdf")

    estilos = getSampleStyleSheet()
    elementos = []

    elementos.append(Paragraph("Relatório Psicossocial", estilos["Title"]))
    elementos.append(Spacer(1, 20))
    elementos.append(Paragraph(f"Empresa: {empresa}", estilos["Normal"]))
    elementos.append(Paragraph(f"Participantes: {total}", estilos["Normal"]))
    elementos.append(Spacer(1, 20))

    for dim, media in resultados.items():
        elementos.append(Paragraph(dim, estilos["Heading2"]))
        elementos.append(Paragraph(f"Média: {media}", estilos["Normal"]))
        elementos.append(Paragraph(classificar_risco(media), estilos["Normal"]))
        elementos.append(Spacer(1, 15))

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

@app.route("/questionario", methods=["GET", "POST"])
def questionario():
    # ==========================
    # POST → salva respostas
    # ==========================
    if request.method == "POST":
        conn = conectar_db()
        c = conn.cursor()

        # Cria participante
        c.execute(
            "INSERT INTO participante (empresa_id, data) VALUES (?, ?)",
            (empresa_id_atual, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        participante_id = c.lastrowid

        # Salva respostas (valores crus)
        for campo, valor in request.form.items():
            if campo.startswith("pergunta_"):
                pergunta_id = int(campo.replace("pergunta_", ""))
                c.execute(
                    "INSERT INTO resposta (participante_id, pergunta_id, valor) VALUES (?, ?, ?)",
                    (participante_id, pergunta_id, int(valor))
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
        SELECT p.id, p.texto, p.escala, p.invertida
        FROM pergunta p
        ORDER BY p.id
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

    c.execute("""
        SELECT d.nome, r.valor, pa.id, p.invertida, p.valor_maximo
        FROM resposta r
        JOIN pergunta p ON r.pergunta_id = p.id
        JOIN dimensao d ON p.dimensao_id = d.id
        JOIN participante pa ON r.participante_id = pa.id
        WHERE pa.empresa_id = ?
    """, (empresa_id_atual,))
    dados = c.fetchall()

    c.execute("SELECT nome FROM empresa WHERE id = ?", (empresa_id_atual,))
    empresa_nome = c.fetchone()[0]
    conn.close()

    respostas_por_dimensao = {}

    for dim, valor, participante, invertida, valor_maximo in dados:
        respostas_por_dimensao.setdefault(dim, {})
        respostas_por_dimensao[dim].setdefault(participante, [])

        if invertida:
            valor = valor_maximo - valor

        respostas_por_dimensao[dim][participante].append(valor)

    respostas_formatadas = {
        dim: list(p.values())
        for dim, p in respostas_por_dimensao.items()
    }

    medias = calcular_medias_copsoq(respostas_formatadas)
    total = len(set(p for _, _, p, _, _ in dados))
    caminho_pdf = gerar_pdf(empresa_nome, total, medias)

    conn = conectar_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO relatorio (empresa_id, caminho_pdf, data) VALUES (?, ?, ?)",
        (empresa_id_atual, caminho_pdf, datetime.now().strftime("%Y-%m-%d %H:%M"))
    )
    conn.commit()
    conn.close()

    return render_template("encerramento.html")

# ==================================================
# INIT
# ==================================================
criar_tabelas()
migrar_perguntas()

if __name__ == "__main__":
    app.run(debug=True)