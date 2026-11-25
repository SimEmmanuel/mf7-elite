# Site do clã #2U2QJJ9J8

Coletor em Python (sem dependências) + site estático que lê `site/data.json`.

```
coletor.py            → chama a API oficial, grava cla.db (histórico) e gera site/data.json
site/index.html       → o site (abre data.json; sem ele, mostra o exemplo embutido)
site/data-exemplo.json→ dados fictícios usados na prévia
.github/workflows/    → coleta automática a cada 30 min + publicação no GitHub Pages
tests/                → API falsa para testar sem chave
```

## Colocar no ar (grátis, pelo GitHub)

1. Crie uma conta em https://developer.clashofclans.com (pode ser o mesmo e-mail do Supercell ID).
2. Crie um repositório no GitHub e suba esta pasta.
3. Em **Settings → Secrets and variables → Actions**, crie `COC_EMAIL` e `COC_PASSWORD`
   com o login do portal de desenvolvedor.
4. Em **Settings → Pages**, escolha **Source: GitHub Actions**.
5. Em **Actions → Coletar dados do clã → Run workflow**, rode a primeira vez.
   O site fica em `https://SEU-USUARIO.github.io/NOME-DO-REPO/`.

O GitHub muda de IP a cada execução, por isso o coletor faz login no portal e cria
a chave para o IP do momento (mantém no máximo 10 chaves, apagando a mais antiga).

## Rodar no seu PC

```bash
# Windows (PowerShell)
$env:COC_TOKEN="cole-a-chave-aqui"     # chave criada para o seu IP
python coletor.py

# depois, para ver o site:
cd site; python -m http.server 8000     # abra http://localhost:8000
```

## Importante

- Deixe o **registro de guerra público** nas configurações do clã, senão o histórico fica vazio.
- O histórico (doações por temporada, entradas e saídas, ataques por guerra, inatividade)
  começa a contar **a partir da primeira coleta**. A API não dá o passado.
- Jogos do Clã: a API não informa os pontos direto. O coletor mede a diferença da conquista
  "Games Champion" desde a primeira coleta do mês.
- Última atividade é **estimada**: muda quando o jogador doa, ganha troféu, sobe XP,
  pontua nos Jogos ou ataca na Capital.

## Testar sem chave

```bash
bash tests/rodar_teste.sh   # sobe uma API falsa, roda o coletor 2x e gera /tmp/data.json
```
