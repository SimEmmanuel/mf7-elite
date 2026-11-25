#!/usr/bin/env bash
# Testa o coletor inteiro contra a API falsa (sem chave, sem internet).
set -e
cd "$(dirname "$0")/.."
export COC_TOKEN=teste COC_API_BASE=http://127.0.0.1:8765/v1 COC_DB=/tmp/teste.db COC_OUT=/tmp/data.json
rm -f "$COC_DB"

python3 tests/mock_api.py 8765 1 & P=$!; sleep 1
python3 coletor.py
python3 - <<'EOF'
import json, sys, urllib.request
sys.path.insert(0, '.')
import coletor
req = urllib.request.Request("http://127.0.0.1:8765/v1/_encerradas", headers={"Authorization": "Bearer x"})
con = coletor.abrir_db()
for w in json.load(urllib.request.urlopen(req)):
    coletor.salvar_guerra(con, w, "normal", "#2U2QJJ9J8")
con.commit()
EOF
kill $P; sleep 0.5

python3 tests/mock_api.py 8765 2 & P=$!; sleep 1
python3 coletor.py
kill $P
