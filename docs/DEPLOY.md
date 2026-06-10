# Deploy em servidor novo (do zero)

Guia para subir a plataforma completa (MySQL + backend Flask + frontend React)
num servidor limpo, incluindo opções de servidor **gratuito** e o checklist de
**rebrand** (mudar o nome do produto).

A stack precisa de: Linux, Python 3.11+, Node 20+, MySQL 8. RAM mínima
recomendada: 2 GB (4+ GB se for usar os recursos com Playwright/captura de
certidões).

---

## 1. Escolhendo o servidor

### Opção gratuita recomendada: Oracle Cloud "Always Free"

É a única oferta gratuita do mercado que roda esta stack inteira com folga e
**sem prazo de expiração**: até 4 vCPUs ARM (Ampere) + 24 GB de RAM + 200 GB de
disco, com IP público.

- Cadastro em <https://www.oracle.com/br/cloud/free/> (pede cartão de crédito
  para verificação, mas instâncias Always Free não geram cobrança).
- Crie uma instância **VM.Standard.A1.Flex** (ex.: 2 OCPUs / 12 GB) com
  **Ubuntu 24.04**.
- Avisos práticos: a capacidade ARM esgota em algumas regiões — se der "out of
  capacity", tente outra availability domain ou horário; toda a stack
  (Python/Node/MySQL/Chromium) roda normalmente em ARM64.
- Libere as portas 80 e 443 na Security List da VCN **e** no firewall da VM.

### Alternativas gratuitas (com limitações)

| Opção | O que cobre | Limitação |
|---|---|---|
| Google Cloud `e2-micro` (always free) | VM 1 vCPU / 1 GB | Apertado: exige swap, sem Playwright; só para demo leve |
| AWS free tier (12 meses) | VM `t3.micro` 1 GB | Expira em 12 meses; mesmo aperto de RAM |
| Aiven free MySQL | Só o banco (5 GB) | Backend/frontend precisam de host à parte |
| Vercel / Cloudflare Pages | Só o frontend (estático) | Backend+MySQL precisam de host à parte |

Se o gratuito não atender, um VPS pago básico (ex.: Hetzner CX22 ~€4/mês,
2 vCPU/4 GB) roda tudo sem malabarismo.

> PaaS com "free tier" tipo Render/Railway/Fly não servem bem aqui: o backend
> usa APScheduler residente (jobs de alertas) e MySQL — os planos gratuitos
> hibernam o processo e não oferecem MySQL persistente.

---

## 2. Preparar o servidor (Ubuntu 24.04)

```bash
sudo apt update && sudo apt -y upgrade
sudo apt install -y python3.12-venv python3-pip git nginx mysql-server
# Node 20+
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# (apenas em VMs de 1-2 GB) swap de 2 GB:
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 3. Banco de dados

```bash
sudo mysql <<'SQL'
CREATE DATABASE editais CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'editais'@'localhost' IDENTIFIED BY 'TROQUE_ESTA_SENHA';
GRANT ALL PRIVILEGES ON editais.* TO 'editais'@'localhost';
FLUSH PRIVILEGES;
SQL
```

## 4. Projeto + backend

```bash
sudo mkdir -p /opt/editais && sudo chown $USER /opt/editais
git clone <URL_DO_SEU_REPOSITORIO> /opt/editais
cd /opt/editais

# Ambiente
cp .env.example .env
nano .env   # preencha: MYSQL_PASSWORD, JWT_SECRET_KEY, CRYPTO_KEY, DEEPSEEK_API_KEY, CORS_ORIGINS

python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

# Cria o schema (todas as tabelas) e aplica migrations incrementais
cd backend
python -c "from models import init_db; init_db()"
for f in migrations/*.sql; do mysql -u editais -p editais < "$f" || true; done
# (algumas migrations podem já estar contempladas pelo create_all — erros de
#  "duplicate column" nesses arquivos são inofensivos)

# Smoke test manual
python app.py   # deve imprimir "Servidor pronto na porta 5007!" — Ctrl+C depois
```

Serviço permanente:

```bash
sudo cp /opt/editais/deploy/editais-backend.service /etc/systemd/system/
sudo nano /etc/systemd/system/editais-backend.service  # ajuste User=
sudo systemctl daemon-reload
sudo systemctl enable --now editais-backend
journalctl -u editais-backend -f
```

## 5. Frontend (build + nginx)

```bash
cd /opt/editais/frontend
npm ci
# Rebrand opcional já no build:
VITE_APP_NAME="MeuNome.IA" VITE_APP_TAGLINE="Minha descrição" npm run build

sudo cp /opt/editais/deploy/nginx.conf.example /etc/nginx/sites-available/editais
sudo nano /etc/nginx/sites-available/editais   # server_name + caminhos
sudo ln -s /etc/nginx/sites-available/editais /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Com nginx servindo tudo na porta 80, configure no `.env`:
`CORS_ORIGINS=http://SEU_IP` (ou seu domínio) e reinicie o backend.

## 6. Usuário de teste

```bash
cd /opt/editais/backend
../venv/bin/python ../scripts/criar_usuario_teste.py --base-url http://SEU_IP
# imprime: link + login (teste@facilicita.ia) + senha (Facilicita@2026)
```

## 7. Rebrand — mudar o nome do produto

O nome visível ao usuário está centralizado em
**`frontend/src/config/branding.ts`** (`APP_NAME` / `APP_TAGLINE`), consumido
pela Sidebar, telas de Login/Registro e título da aba. Duas formas de trocar:

1. **Sem tocar no código**: `VITE_APP_NAME="NovoNome" npm run build`
2. **Permanente**: edite o default em `branding.ts`

Pontos adicionais (cosméticos/técnicos) se quiser rebrand completo:

- `frontend/index.html` — `<title>` estático de fallback
- E-mails de alerta: `SMTP_FROM` no `.env` e templates em
  `backend/notifications.py`
- Documentos gerados: cabeçalhos em `backend/gerador_documentos.py`
- **Não renomeie** as chaves de localStorage (`editais_ia_access_token`,
  `facilicita_sidebar_*`) nem o banco `editais` — são identificadores técnicos;
  mudar desloga/resseta preferências de todos os usuários sem ganho visível.

## 8. Checklist de segurança antes de divulgar o link

- [ ] `JWT_SECRET_KEY` forte e único no `.env` (o default do código é só dev)
- [ ] `CRYPTO_KEY` gerada (Fernet) se for usar o cofre de senhas de certidões
- [ ] Senha própria no MySQL; usuário do banco restrito a `localhost`
- [ ] `CORS_ORIGINS` apontando só para a URL real do frontend (nunca `*`)
- [ ] HTTPS via certbot se houver domínio
- [ ] Registro aberto: `/api/auth/register` permite qualquer cadastro — avalie
      desabilitar ou proteger se o link for público
