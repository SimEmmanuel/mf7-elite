#!/usr/bin/env python3
"""
Coletor do clã — Clash of Clans API oficial  →  SQLite  →  site/data.json

Só usa a biblioteca padrão do Python (nada para instalar).

Como usar
---------
1) Crie uma conta em https://developer.clashofclans.com
2) Escolha UMA das formas de autenticação (variáveis de ambiente):

   a) Token fixo (máquina com IP fixo):
        COC_TOKEN="eyJ0eXAi..."

   b) Login automático (IP variável — GitHub Actions, PC de casa):
        COC_EMAIL="seu@email.com"
        COC_PASSWORD="sua-senha-do-portal"
      O script descobre o IP atual, procura uma chave para ele e, se não
      existir, cria uma nova (apaga a mais antiga do script se já houver 10).

3) Rode:
        python3 coletor.py                 # coleta + gera site/data.json
        python3 coletor.py --so-exportar   # só regera o data.json a partir do banco

Agende a cada 15–30 min (cron, Agendador de Tarefas ou GitHub Actions).
O histórico (doações por temporada, entradas/saídas, ataques de guerra,
raids) só existe porque este script guarda uma foto a cada execução.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CLAN_TAG = os.environ.get("COC_CLAN_TAG") or "#2U2QJJ9J8"
API_BASE = os.environ.get("COC_API_BASE", "https://api.clashofclans.com/v1")
DEV_BASE = os.environ.get("COC_DEV_BASE", "https://developer.clashofclans.com")
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("COC_DB", BASE_DIR / "cla.db"))
OUT_JSON = Path(os.environ.get("COC_OUT", BASE_DIR / "site" / "data.json"))
KEY_NAME = "coletor-site-cla"

# Conquista que acumula pontos de Jogos do Clã (a API não dá os pontos direto)
ACH_JOGOS = "Games Champion"
ACH_DOACOES = "Friend in Need"
ACH_CAPITAL = "Aggressive Capitalism"


def agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def enc(tag: str) -> str:
    tag = tag.strip().upper()
    if not tag.startswith("#"):
        tag = "#" + tag
    return urllib.parse.quote(tag, safe="")


# --------------------------------------------------------------------------
# Autenticação
# --------------------------------------------------------------------------

def obter_token() -> str:
    token = os.environ.get("COC_TOKEN")
    if token:
        return token
    email, senha = os.environ.get("COC_EMAIL"), os.environ.get("COC_PASSWORD")
    if not (email and senha):
        sys.exit("Defina COC_TOKEN ou COC_EMAIL + COC_PASSWORD (veja o topo do arquivo).")
    return token_por_login(email, senha)


def token_por_login(email: str, senha: str) -> str:
    """Login no portal de desenvolvedor e chave para o IP atual."""
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def post(path, body):
        req = urllib.request.Request(
            DEV_BASE + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with op.open(req, timeout=30) as r:
            return json.load(r)

    login = post("/api/login", {"email": email, "password": senha})
    # O portal devolve um token temporário cujo payload traz o IP de origem
    ip = None
    try:
        import base64
        payload = login["temporaryAPIToken"].split(".")[1]
        payload += "=" * (-len(payload) % 4)
        ip = json.loads(base64.urlsafe_b64decode(payload))["limits"][1]["cidrs"][0].split("/")[0]
    except Exception:
        pass
    if not ip:
        with urllib.request.urlopen("https://api.ipify.org", timeout=15) as r:
            ip = r.read().decode().strip()

    chaves = post("/api/apikey/list", {}).get("keys", [])
    print(f"Login no portal OK. IP desta máquina: {ip}")
    for k in chaves:
        if ip in k.get("cidrRanges", []):
            print("Usando chave já existente para este IP.")
            return k["key"]

    if len(chaves) >= 10:
        minhas = [k for k in chaves if k.get("name") == KEY_NAME] or chaves
        post("/api/apikey/revoke", {"id": minhas[0]["id"]})

    nova = post("/api/apikey/create", {
        "name": KEY_NAME,
        "description": f"Criada automaticamente {agora()}",
        "cidrRanges": [ip],
        "scopes": ["clash"],
    })
    print("Nova chave criada para este IP.")
    return nova["key"]["key"]


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

class Api:
    def __init__(self, token: str):
        self.token = token

    def get(self, path: str, obrigatorio: bool = False):
        req = urllib.request.Request(
            API_BASE + path,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            corpo = e.read().decode(errors="ignore")
            try:
                motivo = json.loads(corpo).get("reason", "")
            except Exception:
                motivo = corpo[:200]
            if "invalidIp" in motivo:
                sys.exit("ERRO: chave recusada — o IP desta máquina não está liberado na chave. "
                         "Use COC_EMAIL/COC_PASSWORD para gerar a chave automaticamente.")
            if motivo == "accessDenied" and obrigatorio:
                sys.exit("ERRO: acesso negado pela API (chave inválida ou sem permissão). "
                         f"Detalhe: {corpo[:300]}")
            if obrigatorio:
                dica = {404: "não existe nenhum clã/jogador com essa tag — confira a tag copiando direto do jogo.",
                        400: "tag em formato inválido.",
                        429: "muitas requisições, tente de novo em alguns minutos.",
                        503: "API da Supercell em manutenção, tente mais tarde."}.get(e.code, "")
                sys.exit(f"ERRO {e.code} ({motivo}) em {path}: {dica}")
            if e.code == 503:
                print("API em manutenção (503).", file=sys.stderr)
            return None  # ex.: registro de guerra privado (403), sem CWL (404)


# --------------------------------------------------------------------------
# Banco
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS coleta (
    id INTEGER PRIMARY KEY, em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clan_snap (
    coleta_id INTEGER, em TEXT, nome TEXT, nivel INTEGER, pontos INTEGER,
    pontos_bb INTEGER, pontos_capital INTEGER, membros INTEGER,
    vitorias INTEGER, derrotas INTEGER, empates INTEGER, sequencia INTEGER,
    liga_cwl TEXT, raw TEXT
);
CREATE TABLE IF NOT EXISTS membro_snap (
    coleta_id INTEGER, em TEXT, tag TEXT, nome TEXT, cargo TEXT, cv INTEGER,
    xp INTEGER, trofeus INTEGER, trofeus_bb INTEGER, doou INTEGER, recebeu INTEGER,
    liga TEXT, jogos_total INTEGER, capital_total INTEGER,
    PRIMARY KEY (coleta_id, tag)
);
CREATE TABLE IF NOT EXISTS membro (
    tag TEXT PRIMARY KEY, nome TEXT, primeira_vez TEXT, ultima_vez TEXT,
    no_cla INTEGER, ultima_atividade TEXT, assinatura TEXT
);
CREATE TABLE IF NOT EXISTS evento (
    em TEXT, tag TEXT, nome TEXT, tipo TEXT      -- entrou | saiu | promovido | rebaixado
);
CREATE TABLE IF NOT EXISTS guerra (
    id TEXT PRIMARY KEY,           -- preparacao + tag adversário
    tipo TEXT,                     -- normal | cwl
    estado TEXT, tamanho INTEGER, ataques_por_membro INTEGER,
    inicio TEXT, fim TEXT,
    adversario TEXT, adversario_tag TEXT,
    estrelas INTEGER, estrelas_adv INTEGER,
    destruicao REAL, destruicao_adv REAL, resultado TEXT, raw TEXT
);
CREATE TABLE IF NOT EXISTS guerra_membro (
    guerra_id TEXT, tag TEXT, nome TEXT, cv INTEGER, posicao INTEGER,
    ataques_usados INTEGER, ataques_max INTEGER,
    PRIMARY KEY (guerra_id, tag)
);
CREATE TABLE IF NOT EXISTS guerra_ataque (
    guerra_id TEXT, atacante TEXT, defensor TEXT, ordem INTEGER,
    estrelas INTEGER, destruicao REAL, cv_atacante INTEGER, cv_defensor INTEGER,
    duracao INTEGER,
    PRIMARY KEY (guerra_id, atacante, ordem)
);
CREATE TABLE IF NOT EXISTS raid (
    inicio TEXT PRIMARY KEY, fim TEXT, estado TEXT, ouro_total INTEGER,
    ataques INTEGER, distritos INTEGER, medalhas_ofensivas INTEGER
);
CREATE TABLE IF NOT EXISTS raid_membro (
    inicio TEXT, tag TEXT, nome TEXT, ataques INTEGER, limite INTEGER, ouro INTEGER,
    PRIMARY KEY (inicio, tag)
);
"""


def abrir_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def ach(player: dict | None, nome: str) -> int | None:
    if not player:
        return None
    for a in player.get("achievements", []):
        if a.get("name") == nome:
            return a.get("value")
    return None


ORDEM_CARGO = {"leader": 4, "coLeader": 3, "admin": 2, "member": 1}


# --------------------------------------------------------------------------
# Coleta
# --------------------------------------------------------------------------

def coletar(api: Api, con: sqlite3.Connection) -> None:
    t = enc(CLAN_TAG)
    em = agora()
    print(f"Buscando clã {CLAN_TAG} ...")
    clan = api.get(f"/clans/{t}", obrigatorio=True)

    cur = con.execute("INSERT INTO coleta (em) VALUES (?)", (em,))
    cid = cur.lastrowid

    con.execute(
        "INSERT INTO clan_snap VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, em, clan.get("name"), clan.get("clanLevel"), clan.get("clanPoints"),
         clan.get("clanBuilderBasePoints"), clan.get("clanCapitalPoints"),
         clan.get("members"), clan.get("warWins"), clan.get("warLosses"),
         clan.get("warTies"), clan.get("warWinStreak"),
         (clan.get("warLeague") or {}).get("name"), json.dumps(clan, ensure_ascii=False)),
    )

    membros = clan.get("memberList", [])
    tags_atuais = set()
    for m in membros:
        tag = m["tag"]
        tags_atuais.add(tag)
        player = api.get(f"/players/{enc(tag)}")  # 1 chamada por membro (≤50)
        jogos = ach(player, ACH_JOGOS)
        capital = ach(player, ACH_CAPITAL)
        con.execute(
            "INSERT OR REPLACE INTO membro_snap VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, em, tag, m.get("name"), m.get("role"), m.get("townHallLevel"),
             m.get("expLevel"), m.get("trophies"), m.get("builderBaseTrophies"),
             m.get("donations"), m.get("donationsReceived"),
             (m.get("leagueTier") or m.get("league") or {}).get("name"),
             jogos, capital),
        )
        registrar_membro(con, em, m, jogos, capital, player)

    # quem saiu
    for row in con.execute("SELECT tag, nome FROM membro WHERE no_cla = 1").fetchall():
        if row["tag"] not in tags_atuais:
            con.execute("UPDATE membro SET no_cla = 0 WHERE tag = ?", (row["tag"],))
            con.execute("INSERT INTO evento VALUES (?,?,?,?)", (em, row["tag"], row["nome"], "saiu"))

    coletar_guerra(api, con, t)
    coletar_cwl(api, con, t)
    coletar_warlog(api, con, t)
    coletar_raids(api, con, t)
    con.commit()
    print(f"[{em}] {clan.get('name')} — {len(membros)} membros coletados.")


def registrar_membro(con, em, m, jogos, capital, player):
    tag = m["tag"]
    # "assinatura" muda quando o jogador faz algo: doa, ganha/perde troféu, sobe XP,
    # pontua nos jogos, ataca na capital… Serve para estimar a última atividade.
    heroes = sum(h.get("level", 0) for h in (player or {}).get("heroes", []))
    assinatura = json.dumps([m.get("donations"), m.get("donationsReceived"),
                             m.get("trophies"), m.get("builderBaseTrophies"),
                             m.get("expLevel"), jogos, capital, heroes,
                             (player or {}).get("attackWins")])
    antigo = con.execute("SELECT * FROM membro WHERE tag = ?", (tag,)).fetchone()
    if antigo is None:
        con.execute("INSERT INTO membro VALUES (?,?,?,?,?,?,?)",
                    (tag, m.get("name"), em, em, 1, em, assinatura))
        con.execute("INSERT INTO evento VALUES (?,?,?,?)", (em, tag, m.get("name"), "entrou"))
        return
    if not antigo["no_cla"]:
        con.execute("INSERT INTO evento VALUES (?,?,?,?)", (em, tag, m.get("name"), "entrou"))
    ult_ativ = antigo["ultima_atividade"]
    if antigo["assinatura"] != assinatura:
        ult_ativ = em
    # promoção / rebaixamento
    ant_cargo = con.execute(
        "SELECT cargo FROM membro_snap WHERE tag = ? AND em < ? ORDER BY em DESC LIMIT 1",
        (tag, em)).fetchone()
    if ant_cargo and ant_cargo["cargo"] != m.get("role"):
        tipo = "promovido" if ORDEM_CARGO.get(m.get("role"), 0) > ORDEM_CARGO.get(ant_cargo["cargo"], 0) else "rebaixado"
        con.execute("INSERT INTO evento VALUES (?,?,?,?)", (em, tag, m.get("name"), tipo))
    con.execute(
        "UPDATE membro SET nome=?, ultima_vez=?, no_cla=1, ultima_atividade=?, assinatura=? WHERE tag=?",
        (m.get("name"), em, ult_ativ, assinatura, tag))


def salvar_guerra(con, w: dict, tipo: str, minha_tag: str):
    if not w or w.get("state") in (None, "notInWar"):
        return
    a, b = w.get("clan", {}), w.get("opponent", {})
    if b.get("tag") == minha_tag:      # na CWL o "clan" pode ser o adversário
        a, b = b, a
    if a.get("tag") != minha_tag:
        return
    gid = f"{w.get('preparationStartTime')}_{b.get('tag')}"
    resultado = None
    if w.get("state") == "warEnded":
        ea, eb = a.get("stars", 0), b.get("stars", 0)
        da, db = a.get("destructionPercentage", 0), b.get("destructionPercentage", 0)
        resultado = "vitoria" if (ea, da) > (eb, db) else "derrota" if (ea, da) < (eb, db) else "empate"
    apm = w.get("attacksPerMember", 1 if tipo == "cwl" else 2)
    # se a mesma guerra já entrou resumida pelo warlog, troca pela versão completa
    con.execute("DELETE FROM guerra WHERE id LIKE 'log_%' AND adversario_tag=? AND fim=?",
                (b.get("tag"), w.get("endTime")))
    con.execute(
        "INSERT OR REPLACE INTO guerra VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (gid, tipo, w.get("state"), w.get("teamSize"), apm,
         w.get("startTime"), w.get("endTime"), b.get("name"), b.get("tag"),
         a.get("stars"), b.get("stars"), a.get("destructionPercentage"),
         b.get("destructionPercentage"), resultado, json.dumps(w, ensure_ascii=False)),
    )
    cv_adv = {m["tag"]: m.get("townhallLevel") for m in b.get("members", [])}
    for m in a.get("members", []):
        ataques = m.get("attacks", []) or []
        con.execute("INSERT OR REPLACE INTO guerra_membro VALUES (?,?,?,?,?,?,?)",
                    (gid, m["tag"], m.get("name"), m.get("townhallLevel"),
                     m.get("mapPosition"), len(ataques), apm))
        for at in ataques:
            con.execute(
                "INSERT OR REPLACE INTO guerra_ataque VALUES (?,?,?,?,?,?,?,?,?)",
                (gid, m["tag"], at.get("defenderTag"), at.get("order"), at.get("stars"),
                 at.get("destructionPercentage"), m.get("townhallLevel"),
                 cv_adv.get(at.get("defenderTag")), at.get("duration")))


def coletar_guerra(api, con, t):
    salvar_guerra(con, api.get(f"/clans/{t}/currentwar"), "normal", CLAN_TAG.upper())


def coletar_cwl(api, con, t):
    grupo = api.get(f"/clans/{t}/currentwar/leaguegroup")
    if not grupo or grupo.get("state") in (None, "notInWar"):
        return
    for rodada in grupo.get("rounds", []):
        for wt in rodada.get("warTags", []):
            if wt == "#0":
                continue
            w = api.get(f"/clanwarleagues/wars/{enc(wt)}")
            if w and CLAN_TAG.upper() in (w.get("clan", {}).get("tag"), w.get("opponent", {}).get("tag")):
                salvar_guerra(con, w, "cwl", CLAN_TAG.upper())


def coletar_warlog(api, con, t):
    """Preenche resultado de guerras antigas (o warlog não traz ataques individuais)."""
    log = api.get(f"/clans/{t}/warlog?limit=50")
    if not log:
        return  # registro de guerra privado
    for w in log.get("items", []):
        b = w.get("opponent", {})
        if not b.get("tag"):
            continue  # entradas de CWL no warlog não têm adversário
        fim = w.get("endTime")
        existe = con.execute("SELECT 1 FROM guerra WHERE adversario_tag=? AND fim=?", (b.get("tag"), fim)).fetchone()
        if existe:
            continue
        res = {"win": "vitoria", "lose": "derrota", "tie": "empate"}.get(w.get("result"))
        a = w.get("clan", {})
        con.execute(
            "INSERT OR IGNORE INTO guerra VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"log_{fim}_{b.get('tag')}", "normal", "warEnded", w.get("teamSize"),
             w.get("attacksPerMember"), None, fim, b.get("name"), b.get("tag"),
             a.get("stars"), b.get("stars"), a.get("destructionPercentage"),
             b.get("destructionPercentage"), res, None))


def coletar_raids(api, con, t):
    r = api.get(f"/clans/{t}/capitalraidseasons?limit=10")
    if not r:
        return
    for s in r.get("items", []):
        con.execute("INSERT OR REPLACE INTO raid VALUES (?,?,?,?,?,?,?)",
                    (s.get("startTime"), s.get("endTime"), s.get("state"),
                     s.get("capitalTotalLoot"), s.get("totalAttacks"),
                     s.get("enemyDistrictsDestroyed"), s.get("offensiveReward")))
        for m in s.get("members", []):
            con.execute("INSERT OR REPLACE INTO raid_membro VALUES (?,?,?,?,?,?)",
                        (s.get("startTime"), m["tag"], m.get("name"), m.get("attacks"),
                         (m.get("attackLimit") or 0) + (m.get("bonusAttackLimit") or 0),
                         m.get("capitalResourcesLooted")))


# --------------------------------------------------------------------------
# Exportação para o site
# --------------------------------------------------------------------------

def inicio_temporada(ref: datetime) -> datetime:
    """Temporada (troféus/doações) reinicia na última segunda-feira do mês, 05:00 UTC."""
    def ultima_segunda(ano, mes):
        prox = datetime(ano + (mes == 12), mes % 12 + 1, 1, tzinfo=timezone.utc)
        d = prox - timedelta(days=1)
        while d.weekday() != 0:
            d -= timedelta(days=1)
        return d.replace(hour=5)
    s = ultima_segunda(ref.year, ref.month)
    if ref < s:
        ano, mes = (ref.year - 1, 12) if ref.month == 1 else (ref.year, ref.month - 1)
        s = ultima_segunda(ano, mes)
    return s


def fmt_api(d: datetime) -> str:
    """Mesmo formato de data da API (YYYYMMDDTHHMMSS.000Z), comparável como texto."""
    return d.strftime("%Y%m%dT%H%M%S.000Z")


# Pontuação do MVP — o site mostra esta tabela para todo mundo entender
PONTOS_MVP = {
    "estrela": 10,          # cada estrela em guerra na temporada
    "tres_estrelas": 5,     # bônus por ataque de 3 estrelas
    "cem_doacoes": 4,       # a cada 100 tropas doadas
    "mil_ouro_capital": 3,  # a cada 1.000 de ouro saqueado na Capital
    "cem_jogos": 2,         # a cada 100 pontos nos Jogos do Clã (mês)
    "ataque_perdido": -10,  # cada ataque de guerra não usado
}


def exportar(con: sqlite3.Connection) -> dict:
    ult = con.execute("SELECT * FROM coleta ORDER BY id DESC LIMIT 1").fetchone()
    if not ult:
        sys.exit("Banco vazio — rode a coleta primeiro.")
    cid, em = ult["id"], ult["em"]
    clan = json.loads(con.execute("SELECT raw FROM clan_snap WHERE coleta_id=?", (cid,)).fetchone()["raw"])
    agora_dt = datetime.strptime(em, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    temp_dt = inicio_temporada(agora_dt)
    temp_ini, temp_api = temp_dt.strftime("%Y-%m-%dT%H:%M:%SZ"), fmt_api(temp_dt)
    mes_ini = agora_dt.replace(day=1, hour=0, minute=0, second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    P = PONTOS_MVP

    publicos, sigilosos = [], []
    for m in con.execute("SELECT * FROM membro_snap WHERE coleta_id=? ORDER BY trofeus DESC", (cid,)):
        tag = m["tag"]
        info = con.execute("SELECT * FROM membro WHERE tag=?", (tag,)).fetchone()
        base_jogos = con.execute(
            "SELECT jogos_total FROM membro_snap WHERE tag=? AND em>=? AND jogos_total IS NOT NULL ORDER BY em LIMIT 1",
            (tag, mes_ini)).fetchone()
        jogos_mes = (m["jogos_total"] - base_jogos["jogos_total"]) if (base_jogos and m["jogos_total"] is not None) else None
        base_trof = con.execute("SELECT trofeus FROM membro_snap WHERE tag=? AND em>=? ORDER BY em LIMIT 1",
                                (tag, temp_ini)).fetchone()
        trof_ganhos = (m["trofeus"] - base_trof["trofeus"]) if base_trof else 0
        # guerra — total
        g = con.execute("""
            SELECT COUNT(*) n, COALESCE(SUM(gm.ataques_max),0) possiveis, COALESCE(SUM(gm.ataques_usados),0) usados
            FROM guerra_membro gm JOIN guerra g ON g.id=gm.guerra_id
            WHERE gm.tag=? AND g.estado='warEnded'""", (tag,)).fetchone()
        a = con.execute("""
            SELECT COUNT(*) n, AVG(estrelas) media, AVG(destruicao) destr,
                   SUM(CASE WHEN estrelas=3 THEN 1 ELSE 0 END) tres
            FROM guerra_ataque WHERE atacante=?""", (tag,)).fetchone()
        # guerra — temporada (inclui a guerra em andamento)
        at = con.execute("""
            SELECT COUNT(*) n, COALESCE(SUM(ga.estrelas),0) estrelas,
                   SUM(CASE WHEN ga.estrelas=3 THEN 1 ELSE 0 END) tres
            FROM guerra_ataque ga JOIN guerra g ON g.id=ga.guerra_id
            WHERE ga.atacante=? AND g.inicio>=?""", (tag, temp_api)).fetchone()
        gt = con.execute("""
            SELECT COALESCE(SUM(gm.ataques_max - gm.ataques_usados),0) perdidos
            FROM guerra_membro gm JOIN guerra g ON g.id=gm.guerra_id
            WHERE gm.tag=? AND g.estado='warEnded' AND g.inicio>=?""", (tag, temp_api)).fetchone()
        rc = con.execute("""
            SELECT COALESCE(SUM(rm.ouro),0) ouro FROM raid_membro rm JOIN raid r ON r.inicio=rm.inicio
            WHERE rm.tag=? AND r.inicio>=?""", (tag, temp_api)).fetchone()

        estrelas_t, tres_t, perdidos_t = at["estrelas"], at["tres"] or 0, gt["perdidos"]
        ouro_t, doou = rc["ouro"], m["doou"] or 0
        pontos = (estrelas_t * P["estrela"] + tres_t * P["tres_estrelas"]
                  + doou / 100 * P["cem_doacoes"] + ouro_t / 1000 * P["mil_ouro_capital"]
                  + (jogos_mes or 0) / 100 * P["cem_jogos"] + perdidos_t * P["ataque_perdido"])

        publicos.append({
            "tag": tag, "nome": m["nome"], "cargo": m["cargo"], "cv": m["cv"], "xp": m["xp"],
            "trofeus": m["trofeus"], "trofeusBB": m["trofeus_bb"], "liga": m["liga"],
            "doou": m["doou"], "recebeu": m["recebeu"], "jogosMes": jogos_mes,
            "ataques": a["n"], "tresEstrelas": a["tres"] or 0,
            "mediaEstrelas": round(a["media"], 2) if a["media"] is not None else None,
            "mediaDestruicao": round(a["destr"], 1) if a["destr"] is not None else None,
            "temporada": {"estrelas": estrelas_t, "ataques": at["n"], "tres": tres_t,
                          "ouroCapital": ouro_t, "trofeusGanhos": trof_ganhos},
            "mvp": round(pontos, 1),
        })
        sigilosos.append({
            "tag": tag, "nome": m["nome"], "cargo": m["cargo"], "cv": m["cv"],
            "doou": m["doou"], "recebeu": m["recebeu"],
            "entrou": info["primeira_vez"] if info else None,
            "ultimaAtividade": info["ultima_atividade"] if info else None,
            "guerras": g["n"], "ataquesPerdidos": g["possiveis"] - g["usados"],
            "perdidosTemporada": perdidos_t, "mediaEstrelas": publicos[-1]["mediaEstrelas"],
            "jogosMes": jogos_mes, "mvp": publicos[-1]["mvp"],
        })

    # MVP da última guerra encerrada (com ataques registrados)
    mvp_guerra = None
    ug = con.execute("""SELECT g.id, g.adversario, g.fim, g.resultado FROM guerra g
                        WHERE g.estado='warEnded' AND EXISTS (SELECT 1 FROM guerra_ataque a WHERE a.guerra_id=g.id)
                        ORDER BY g.fim DESC LIMIT 1""").fetchone()
    if ug:
        top = con.execute("""
            SELECT gm.nome, gm.tag, SUM(a.estrelas) estrelas, AVG(a.destruicao) destr, COUNT(*) ataques
            FROM guerra_ataque a JOIN guerra_membro gm ON gm.guerra_id=a.guerra_id AND gm.tag=a.atacante
            WHERE a.guerra_id=? GROUP BY a.atacante ORDER BY estrelas DESC, destr DESC LIMIT 3""", (ug["id"],)).fetchall()
        mvp_guerra = {"adversario": ug["adversario"], "fim": ug["fim"], "resultado": ug["resultado"],
                      "top": [dict(t) | {"destr": round(t["destr"], 1)} for t in top]}

    guerra_atual = None
    gw = con.execute("SELECT raw, tipo FROM guerra WHERE raw IS NOT NULL ORDER BY inicio DESC LIMIT 1").fetchone()
    if gw:
        guerra_atual = json.loads(gw["raw"])
        guerra_atual["_tipo"] = gw["tipo"]

    guerras = [dict(r) for r in con.execute("""
        SELECT tipo, estado, tamanho, inicio, fim, adversario, adversario_tag,
               estrelas, estrelas_adv, destruicao, destruicao_adv, resultado
        FROM guerra WHERE estado='warEnded' ORDER BY fim DESC LIMIT 30""")]

    raids = []
    for r in con.execute("SELECT * FROM raid ORDER BY inicio DESC LIMIT 6"):
        d = dict(r)
        d["membros"] = [dict(x) for x in con.execute(
            "SELECT tag, nome, ataques, limite, ouro FROM raid_membro WHERE inicio=? ORDER BY ouro DESC", (r["inicio"],))]
        raids.append(d)

    eventos = [dict(r) for r in con.execute("SELECT * FROM evento ORDER BY em DESC LIMIT 60")]
    historico = [dict(r) for r in con.execute("""
        SELECT substr(em,1,10) dia, MAX(pontos) pontos, MAX(membros) membros, MAX(nivel) nivel
        FROM clan_snap GROUP BY dia ORDER BY dia DESC LIMIT 90""")][::-1]

    painel = {"membros": sigilosos, "eventos": eventos, "geradoEm": em}
    senha = os.environ.get("COC_PAINEL_SENHA")

    dados = {
        "geradoEm": em, "exemplo": False, "inicioTemporada": temp_ini, "pontosMvp": PONTOS_MVP,
        "cla": {
            "tag": clan.get("tag"), "nome": clan.get("name"), "descricao": clan.get("description"),
            "nivel": clan.get("clanLevel"), "pontos": clan.get("clanPoints"),
            "pontosBB": clan.get("clanBuilderBasePoints"), "pontosCapital": clan.get("clanCapitalPoints"),
            "membros": clan.get("members"), "tipo": clan.get("type"),
            "local": (clan.get("location") or {}).get("name"),
            "idioma": (clan.get("chatLanguage") or {}).get("name"),
            "trofeusMin": clan.get("requiredTrophies"), "cvMin": clan.get("requiredTownhallLevel"),
            "frequenciaGuerra": clan.get("warFrequency"),
            "vitorias": clan.get("warWins"), "derrotas": clan.get("warLosses"),
            "empates": clan.get("warTies"), "sequencia": clan.get("warWinStreak"),
            "ligaCWL": (clan.get("warLeague") or {}).get("name"),
            "ligaCapital": (clan.get("capitalLeague") or {}).get("name"),
            "nivelCapital": (clan.get("clanCapital") or {}).get("capitalHallLevel"),
            "warlogPublico": clan.get("isWarLogPublic"),
            "badge": (clan.get("badgeUrls") or {}).get("medium"),
            "labels": [l.get("name") for l in clan.get("labels", [])],
        },
        "membros": publicos,
        "mvpGuerra": mvp_guerra,
        "guerraAtual": guerra_atual,
        "guerras": guerras,
        "raids": raids,
        "historico": historico,
        "painel": cifrar_json(painel, senha) if senha else None,
    }
    if not senha:
        print("AVISO: COC_PAINEL_SENHA não definida — o painel da liderança não foi gerado.", file=sys.stderr)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Site atualizado: {OUT_JSON}")
    return dados


# --------------------------------------------------------------------------
# Criptografia (painel da liderança e banco de histórico)
#   PBKDF2-SHA256 → chave AES-256-GCM. O navegador decifra com a Web Crypto API.
# --------------------------------------------------------------------------

ITER = 210_000


def _chave(senha: str, salt: bytes) -> bytes:
    import hashlib
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, ITER, dklen=32)


def _aes():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM
    except ImportError:
        sys.exit("Falta o pacote 'cryptography' (pip install cryptography).")


def cifrar_json(obj, senha: str) -> dict:
    import base64
    salt, iv = os.urandom(16), os.urandom(12)
    ct = _aes()(_chave(senha, salt)).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode("utf-8"), None)
    b = lambda x: base64.b64encode(x).decode()
    return {"v": 1, "iter": ITER, "salt": b(salt), "iv": b(iv), "dados": b(ct)}


def decifrar_json(pac: dict, senha: str):
    import base64
    d = base64.b64decode
    return json.loads(_aes()(_chave(senha, d(pac["salt"]))).decrypt(d(pac["iv"]), d(pac["dados"]), None))


DB_ENC = DB_PATH.with_suffix(DB_PATH.suffix + ".enc")


def abrir_db_cifrado(senha: str):
    """cla.db.enc → cla.db (só se ainda não houver um cla.db local)."""
    if DB_PATH.exists() or not DB_ENC.exists():
        return
    raw = DB_ENC.read_bytes()
    salt, iv, ct = raw[:16], raw[16:28], raw[28:]
    try:
        DB_PATH.write_bytes(_aes()(_chave(senha, salt)).decrypt(iv, ct, None))
    except Exception:
        sys.exit("ERRO: não consegui abrir cla.db.enc — a senha COC_PAINEL_SENHA mudou? "
                 "Volte a senha antiga ou apague cla.db.enc (perde o histórico).")


def fechar_db_cifrado(senha: str):
    salt, iv = os.urandom(16), os.urandom(12)
    DB_ENC.write_bytes(salt + iv + _aes()(_chave(senha, salt)).encrypt(iv, DB_PATH.read_bytes(), None))


def main():
    ap = argparse.ArgumentParser(description="Coletor do clã de Clash of Clans")
    ap.add_argument("--so-exportar", action="store_true", help="não chama a API, só gera o data.json")
    args = ap.parse_args()
    senha = os.environ.get("COC_PAINEL_SENHA")
    if os.environ.get("COC_EXIGIR_SENHA") and not senha:
        sys.exit("ERRO: cadastre o secret COC_PAINEL_SENHA no GitHub (Settings → Secrets → Actions).")
    if senha:
        abrir_db_cifrado(senha)
    con = abrir_db()
    if not args.so_exportar:
        coletar(Api(obter_token()), con)
    exportar(con)
    con.close()
    if senha:
        fechar_db_cifrado(senha)


if __name__ == "__main__":
    main()
