#!/usr/bin/env python3
"""
Cria (ou reseta) um usuário de teste com empresa vinculada e imprime as
credenciais + link de acesso.

Uso (no servidor, onde o MySQL é alcançável):
    cd /caminho/do/agenteditais/backend
    python ../scripts/criar_usuario_teste.py
    python ../scripts/criar_usuario_teste.py --email qa@facilicita.ia --senha MinhaSenha1 --base-url http://SEU_IP:5180

Idempotente: se o usuário/empresa já existem, apenas reseta a senha e
garante o vínculo ativo. Dados prefixados com TESTE_ (convenção do projeto:
dados de validação humana são realistas mas identificáveis).
"""
import argparse
import sys
import os
import uuid
from datetime import datetime

# Permite rodar de qualquer diretório, desde que backend/ seja importável
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import bcrypt
from models import get_db, User, Empresa, UsuarioEmpresa

DEFAULTS = {
    "email": "teste@facilicita.ia",
    "senha": "Facilicita@2026",
    "nome": "Usuário de Teste",
    "empresa_cnpj": "11222333000181",  # CNPJ sintético válido (dígitos verificadores corretos)
    "empresa_razao": "TESTE Diagnósticos LTDA",
    "base_url": "http://localhost:5180",
}


def main():
    ap = argparse.ArgumentParser(description="Cria usuário de teste com empresa vinculada")
    ap.add_argument("--email", default=DEFAULTS["email"])
    ap.add_argument("--senha", default=DEFAULTS["senha"])
    ap.add_argument("--nome", default=DEFAULTS["nome"])
    ap.add_argument("--cnpj", default=DEFAULTS["empresa_cnpj"])
    ap.add_argument("--razao-social", default=DEFAULTS["empresa_razao"])
    ap.add_argument("--base-url", default=DEFAULTS["base_url"],
                    help="URL do frontend para compor o link (ex: http://IP:5180)")
    ap.add_argument("--super", action="store_true", dest="is_super",
                    help="Marca o usuário como superusuário (vê todas as empresas)")
    args = ap.parse_args()

    senha_hash = bcrypt.hashpw(args.senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    db = get_db()
    try:
        user = db.query(User).filter(User.email == args.email.lower()).first()
        if user:
            user.password_hash = senha_hash
            user.name = args.nome
            if args.is_super:
                user.is_super = True
            acao_user = "atualizado (senha resetada)"
        else:
            user = User(
                id=str(uuid.uuid4()),
                email=args.email.lower(),
                name=args.nome,
                password_hash=senha_hash,
                is_super=args.is_super,
                created_at=datetime.now(),
            )
            db.add(user)
            acao_user = "criado"
        db.flush()

        empresa = db.query(Empresa).filter(Empresa.cnpj == args.cnpj).first()
        if empresa:
            acao_empresa = "reutilizada"
        else:
            empresa = Empresa(
                id=str(uuid.uuid4()),
                user_id=user.id,
                cnpj=args.cnpj,
                razao_social=args.razao_social,
                nome_fantasia=args.razao_social,
                porte="epp",
                cidade="Campinas",
                uf="SP",
                ativo=True,
                created_at=datetime.now(),
            )
            db.add(empresa)
            acao_empresa = "criada"
        db.flush()

        vinculo = db.query(UsuarioEmpresa).filter(
            UsuarioEmpresa.user_id == user.id,
            UsuarioEmpresa.empresa_id == empresa.id,
        ).first()
        if vinculo:
            vinculo.ativo = True
        else:
            db.add(UsuarioEmpresa(
                id=str(uuid.uuid4()),
                user_id=user.id,
                empresa_id=empresa.id,
                papel="admin",
                ativo=True,
                created_at=datetime.now(),
            ))
        db.commit()

        print("=" * 60)
        print("USUÁRIO DE TESTE PRONTO")
        print("=" * 60)
        print(f"  Link de acesso : {args.base_url}")
        print(f"  Login (email)  : {args.email}")
        print(f"  Senha          : {args.senha}")
        print(f"  Usuário        : {acao_user}")
        print(f"  Empresa        : {empresa.razao_social} ({acao_empresa})")
        print(f"  Papel          : admin" + ("  [SUPERUSUÁRIO]" if args.is_super else ""))
        print("=" * 60)
    except Exception as e:
        db.rollback()
        print(f"ERRO: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
