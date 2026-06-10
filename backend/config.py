import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# DeepSeek LLM - Mesmo modelo do trabalhista: reasoner com thinking mode e 64K tokens
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-reasoner")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# FAISS / Embeddings (opcional para este MVP - foco no banco estruturado)
FAISS_INDEX_PATH = str(Path(__file__).parent.parent / "faiss_index_editais")
EMBEDDINGS_MODEL = "intfloat/multilingual-e5-base"

# MySQL - Banco "editais"
# Defaults apontam para banco local; configure no .env (ver .env.example na raiz)
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "editais")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "editais")
MYSQL_URI = f"mysql+mysqlconnector://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"

# JWT
# OBRIGATORIO definir no .env em producao (default e apenas para dev local)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-secret-defina-JWT_SECRET_KEY-no-env")
JWT_ACCESS_TOKEN_EXPIRES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", "3600"))  # 1 hour
JWT_REFRESH_TOKEN_EXPIRES = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES", "2592000"))  # 30 days

# RAG / LLM
SIMILARITY_TOP_K = 15
MAX_HISTORY_MESSAGES = 10
TEMPERATURE = 0.7
MAX_TOKENS = 65536  # DeepSeek Reasoner suporta até 64K tokens de saída com thinking mode

# Diretórios de upload
UPLOAD_FOLDER = str(Path(__file__).parent.parent / "uploads")
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'doc', 'txt'}

# PNCP API (Portal Nacional de Contratações Públicas)
PNCP_BASE_URL = "https://pncp.gov.br/api/consulta/v1"

# API de scraping web (busca de editais em fontes alternativas)
# Opcoes: duckduckgo, serper, serpapi, google_cse, brave
SCRAPE_API = os.getenv("SCRAPE_API", "duckduckgo").lower().strip()

# Serper API (Google Search) - serper.dev
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
SERPER_API_URL = "https://google.serper.dev/search"

# SerpAPI (serpapi.com)
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "")

# Google Custom Search Engine (Programmable Search)
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "")

# Brave Search API (search.brave.com/api) - 2000 queries/mes gratis
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")

# BEC-SP API (Bolsa Eletrônica de Compras de São Paulo)
BEC_API_BASE_URL = "https://www.bec.sp.gov.br/BEC_API/API"
BEC_CACHE_TTL_HOURS = int(os.getenv("BEC_CACHE_TTL_HOURS", "24"))

# ComprasNet API (Portal de Compras do Governo Federal)
COMPRASNET_API_URL = "https://compras.dados.gov.br/licitacoes/v1/licitacoes.json"
COMPRASNET_TIMEOUT = int(os.getenv("COMPRASNET_TIMEOUT", "10"))

# CapSolver (resolução automática de captchas para certidões)
CAPSOLVER_API_KEY = os.getenv("CAPSOLVER_API_KEY", "")

# Criptografia de senhas (Fernet symmetric key)
CRYPTO_KEY = os.getenv("CRYPTO_KEY", "")

# MindsDB (Consultas analíticas via linguagem natural)
MINDSDB_HOST = os.getenv("MINDSDB_HOST", "127.0.0.1")
MINDSDB_PORT = os.getenv("MINDSDB_PORT", "47334")
MINDSDB_USER = os.getenv("MINDSDB_USER", "mindsdb")
MINDSDB_PASSWORD = os.getenv("MINDSDB_PASSWORD", "")
