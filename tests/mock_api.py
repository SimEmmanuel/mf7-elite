"""API falsa da Supercell para testar o coletor sem chave/rede.

Uso: python3 tests/mock_api.py 8765 [rodada]
A 'rodada' muda alguns dados (doações, um membro sai, outro entra) para
testar o histórico.
"""
import json
import random
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
RODADA = int(sys.argv[2]) if len(sys.argv) > 2 else 1
TAG = "#2U2QJJ9J8"

rnd = random.Random(42)
NOMES = ["Wanderson", "Dragão Negro", "Capitão Feijão", "Tio Barba", "Mestre Pekka",
         "Bruxa do 71", "Corujão", "Zé Golem", "Lua Rainha", "Pastel de Vento",
         "Furacão MS", "Arqueira Mansa", "Baiano TH", "Rei Careca", "Sombra",
         "Nego Bala", "Chapéu de Palha", "Lenhador", "Fênix", "Neguinha Valk",
         "Tatu Bola", "Saci Hog", "Mineiro Hog", "Pantanal", "Leão do Norte",
         "Guerreira", "Mago Doido", "Paçoca", "Trovão", "Coxinha"]
TAGS = ["#" + "".join(rnd.choice("0289PYLQGRJCUV") for _ in range(9)) for _ in NOMES]
CARGOS = ["leader", "coLeader", "coLeader", "coLeader"] + ["admin"] * 7 + ["member"] * 19

agora = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
fmt = lambda d: d.strftime("%Y%m%dT%H%M%S.000Z")

membros = []
for i, (n, t) in enumerate(zip(NOMES, TAGS)):
    cv = max(9, 17 - i // 4 - rnd.randint(0, 2))
    membros.append({
        "tag": t, "name": n, "role": CARGOS[i], "townHallLevel": cv,
        "expLevel": 80 + cv * 12 + rnd.randint(0, 40),
        "trophies": 1800 + cv * 180 + rnd.randint(-300, 400),
        "builderBaseTrophies": 2000 + rnd.randint(0, 3000),
        "donations": rnd.choice([0, 0, 20, 60, 150, 400, 900, 1500]) * RODADA,
        "donationsReceived": rnd.choice([0, 40, 120, 300, 600]) * RODADA,
        "leagueTier": {"name": rnd.choice(["Lendária", "Titã I", "Campeão II", "Mestre I", "Cristal II"])},
    })
if RODADA >= 2:   # um sai, um entra
    membros.pop(17)
    membros.append({"tag": "#QQ2YVL0P8", "name": "Novato BR", "role": "member", "townHallLevel": 12,
                    "expLevel": 160, "trophies": 3600, "builderBaseTrophies": 2500,
                    "donations": 10, "donationsReceived": 80, "leagueTier": {"name": "Cristal I"}})
    membros[5]["role"] = "coLeader"

membros.sort(key=lambda m: -m["trophies"])
for i, m in enumerate(membros, 1):
    m["clanRank"] = i

clan = {
    "tag": TAG, "name": "Guardiões do MS", "type": "inviteOnly",
    "description": "Clã brasileiro ⚔️ Guerra 2x por semana, CWL todo mês. Doe, ataque nas 2, respeite todos. Discord no perfil!",
    "location": {"name": "Brazil"}, "chatLanguage": {"name": "Portuguese"},
    "badgeUrls": {"medium": ""}, "clanLevel": 18, "clanPoints": 52340 + 120 * RODADA,
    "clanBuilderBasePoints": 41200, "clanCapitalPoints": 3210,
    "capitalLeague": {"name": "Liga Mestre II"}, "requiredTrophies": 2600,
    "warFrequency": "always", "warWinStreak": 4, "warWins": 312, "warTies": 9, "warLosses": 141,
    "isWarLogPublic": True, "warLeague": {"name": "Cristal I"},
    "members": len(membros), "labels": [{"name": "Guerra de Clãs"}, {"name": "Liga de Clãs"}, {"name": "Doações"}],
    "requiredTownhallLevel": 10, "clanCapital": {"capitalHallLevel": 8},
    "memberList": membros,
}


def player(m):
    base = sum(ord(c) for c in m["tag"])
    return {"tag": m["tag"], "name": m["name"], "attackWins": 40 + base % 60 + RODADA * 3,
            "heroes": [{"name": "Barbarian King", "level": m["townHallLevel"] * 5}],
            "achievements": [
                {"name": "Games Champion", "value": 50000 + base * 7 + (RODADA - 1) * (base % 4) * 1000},
                {"name": "Aggressive Capitalism", "value": 200000 + base * 31 + RODADA * 5000},
                {"name": "Friend in Need", "value": 30000 + base * 11},
            ]}


# Guerra atual 15x15, dia de batalha
top = sorted(membros, key=lambda m: -m["townHallLevel"])[:15]
opp = [{"tag": f"#OPP{i:05d}", "name": f"Inimigo {i}", "townhallLevel": top[i - 1]["townHallLevel"] - rnd.randint(0, 1),
        "mapPosition": i} for i in range(1, 16)]
mine, estrelas, ordem = [], 0, 1
for i, m in enumerate(top, 1):
    ataques = []
    for k in range(rnd.choice([0, 1, 2, 2, 2])):
        alvo = opp[min(14, max(0, i - 1 + rnd.randint(-2, 2)))]
        s = rnd.choice([1, 2, 2, 3, 3, 3])
        ataques.append({"attackerTag": m["tag"], "defenderTag": alvo["tag"], "stars": s,
                        "destructionPercentage": {1: 55, 2: 78, 3: 100}[s] + (rnd.randint(-5, 15) if s < 3 else 0),
                        "order": ordem, "duration": rnd.randint(90, 180)})
        ordem += 1
    mine.append({"tag": m["tag"], "name": m["name"], "townhallLevel": m["townHallLevel"], "mapPosition": i,
                 "attacks": ataques})
currentwar = {
    "state": "inWar", "teamSize": 15, "attacksPerMember": 2,
    "preparationStartTime": fmt(agora - timedelta(hours=30)), "startTime": fmt(agora - timedelta(hours=6)),
    "endTime": fmt(agora + timedelta(hours=18)),
    "clan": {"tag": TAG, "name": clan["name"], "stars": 31, "destructionPercentage": 71.4,
             "attacks": ordem - 1, "members": mine},
    "opponent": {"tag": "#2PQ8LLR0C", "name": "Los Guerreros", "stars": 27, "destructionPercentage": 64.9,
                 "attacks": 19, "members": opp},
}

# Guerras encerradas (para o histórico) — com ataques, como se o coletor já estivesse rodando
encerradas = []
for g in range(1, 9):
    fim = agora - timedelta(days=3.5 * g)
    mem = []
    for i, m in enumerate(top, 1):
        at = []
        for k in range(rnd.choice([1, 2, 2, 2, 2])):
            s = rnd.choice([1, 2, 2, 3, 3, 3, 3])
            at.append({"defenderTag": f"#E{g}{i:03d}", "stars": s,
                       "destructionPercentage": {1: 52, 2: 80, 3: 100}[s], "order": i * 2 + k,
                       "duration": 150})
        mem.append({"tag": m["tag"], "name": m["name"], "townhallLevel": m["townHallLevel"], "mapPosition": i, "attacks": at})
    ea, eb = rnd.randint(30, 45), rnd.randint(25, 45)
    encerradas.append({"state": "warEnded", "teamSize": 15, "attacksPerMember": 2,
                       "preparationStartTime": fmt(fim - timedelta(days=2)), "startTime": fmt(fim - timedelta(days=1)),
                       "endTime": fmt(fim),
                       "clan": {"tag": TAG, "name": clan["name"], "stars": ea, "destructionPercentage": 60 + ea * 0.8, "members": mem},
                       "opponent": {"tag": f"#ADV{g:04d}", "name": rnd.choice(["Tropa do Sul", "Brasil Elite", "Os Imortais", "Clan Lusitano", "Furia Latina", "Nordeste War", "Black Dragons", "Hermanos"]),
                                    "stars": eb, "destructionPercentage": 60 + eb * 0.8, "members": []}})

warlog = {"items": [{"result": "win" if w["clan"]["stars"] > w["opponent"]["stars"] else "lose",
                     "endTime": w["endTime"], "teamSize": 15, "attacksPerMember": 2,
                     "clan": w["clan"] | {"members": None}, "opponent": w["opponent"] | {"members": None}}
                    for w in encerradas]}

raids = {"items": []}
for r in range(3):
    ini = agora - timedelta(days=7 * r + 3)
    ms = [{"tag": m["tag"], "name": m["name"], "attacks": rnd.choice([6, 6, 6, 5, 4, 2]),
           "attackLimit": 5, "bonusAttackLimit": 1, "capitalResourcesLooted": rnd.randint(8000, 26000)}
          for m in membros if rnd.random() > 0.25]
    raids["items"].append({"state": "ongoing" if r == 0 else "ended", "startTime": fmt(ini),
                           "endTime": fmt(ini + timedelta(days=3)),
                           "capitalTotalLoot": sum(x["capitalResourcesLooted"] for x in ms),
                           "totalAttacks": sum(x["attacks"] for x in ms), "enemyDistrictsDestroyed": 40 + r * 3,
                           "offensiveReward": 1200 - r * 50, "members": ms})

ROTAS = {
    f"/v1/clans/{urllib.parse.quote(TAG, safe='')}": clan,
    f"/v1/clans/{urllib.parse.quote(TAG, safe='')}/currentwar": currentwar,
    f"/v1/clans/{urllib.parse.quote(TAG, safe='')}/warlog": warlog,
    f"/v1/clans/{urllib.parse.quote(TAG, safe='')}/capitalraidseasons": raids,
}
PLAYERS = {urllib.parse.quote(m["tag"], safe=""): player(m) for m in membros}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        if not self.headers.get("Authorization", "").startswith("Bearer "):
            return self._send(403, {"reason": "accessDenied"})
        if p in ROTAS:
            return self._send(200, ROTAS[p])
        if p.startswith("/v1/players/"):
            k = p.rsplit("/", 1)[1]
            return self._send(200, PLAYERS[k]) if k in PLAYERS else self._send(404, {"reason": "notFound"})
        if p == "/v1/_encerradas":
            return self._send(200, encerradas)
        self._send(404, {"reason": "notFound"})

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
