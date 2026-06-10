import { APP_NAME, APP_TAGLINE } from "../config/branding";
import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "../contexts/AuthContext";
import { FileText, Building } from "lucide-react";

interface LoginPageProps {
  onSwitchToRegister: () => void;
}

export function LoginPage({ onSwitchToRegister }: LoginPageProps) {
  const { login, isAuthenticated, empresa, minhasEmpresasList, selecionarEmpresa } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [selecting, setSelecting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      await login(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao fazer login");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelecionarEmpresa = async (empresaId: string) => {
    setSelecting(true);
    setError("");
    try {
      await selecionarEmpresa(empresaId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao selecionar empresa");
      setSelecting(false);
    }
  };

  const handleGoogleLogin = () => {
    // TODO: Implementar login com Google OAuth
    alert("Login com Google será implementado em breve!");
  };

  // Step 2: show company picker when authenticated but empresa not yet selected
  if (isAuthenticated && !empresa && minhasEmpresasList.length > 0) {
    return (
      <div className="login-page">
        <div className="login-container" style={{ maxWidth: 520 }}>
          <div className="login-header">
            <Building size={48} className="login-icon" />
            <h1>Selecionar Empresa</h1>
            <p>Escolha a empresa com que deseja trabalhar</p>
          </div>

          {error && <div className="login-error">{error}</div>}

          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 16 }}>
            {minhasEmpresasList.map((e) => (
              <button
                key={e.id}
                onClick={() => handleSelecionarEmpresa(e.id)}
                disabled={selecting}
                style={{
                  padding: "16px 20px",
                  border: "2px solid var(--border-color, #e5e7eb)",
                  borderRadius: 10,
                  background: "var(--bg-card, #fff)",
                  cursor: selecting ? "not-allowed" : "pointer",
                  textAlign: "left",
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                  opacity: selecting ? 0.6 : 1,
                  transition: "border-color 0.15s, background 0.15s",
                }}
                onMouseEnter={(ev) => {
                  if (!selecting) {
                    (ev.currentTarget as HTMLButtonElement).style.borderColor = "var(--primary, #3b82f6)";
                    (ev.currentTarget as HTMLButtonElement).style.background = "var(--primary-light, #eff6ff)";
                  }
                }}
                onMouseLeave={(ev) => {
                  (ev.currentTarget as HTMLButtonElement).style.borderColor = "var(--border-color, #e5e7eb)";
                  (ev.currentTarget as HTMLButtonElement).style.background = "var(--bg-card, #fff)";
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <Building size={18} style={{ color: "var(--primary, #3b82f6)", flexShrink: 0 }} />
                  <strong style={{ fontSize: 15 }}>{e.razao_social}</strong>
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted, #6b7280)", paddingLeft: 26 }}>CNPJ: {e.cnpj}</div>
                <div style={{ fontSize: 12, color: "var(--text-muted, #6b7280)", paddingLeft: 26, textTransform: "capitalize" }}>Papel: {e.papel}</div>
              </button>
            ))}
          </div>

          {selecting && (
            <p style={{ textAlign: "center", marginTop: 16, color: "var(--text-muted, #6b7280)", fontSize: 14 }}>
              Entrando...
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="login-page">
      <div className="login-container">
        <div className="login-header">
          <FileText size={48} className="login-icon" />
          <h1>{APP_NAME}</h1>
          <p>{APP_TAGLINE}</p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          {error && <div className="login-error">{error}</div>}

          <div className="form-group">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="seu@email.com"
              required
              disabled={isLoading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Senha</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Sua senha"
              required
              disabled={isLoading}
            />
          </div>

          <button type="submit" className="login-btn" disabled={isLoading}>
            {isLoading ? "Entrando..." : "Entrar"}
          </button>

          <div className="login-divider">
            <span>ou</span>
          </div>

          <button
            type="button"
            className="google-btn"
            onClick={handleGoogleLogin}
            disabled={isLoading}
          >
            <svg viewBox="0 0 24 24" width="20" height="20">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              />
            </svg>
            Entrar com Google
          </button>

          <div className="login-footer">
            <span>Não tem uma conta?</span>
            <button
              type="button"
              className="link-btn"
              onClick={onSwitchToRegister}
            >
              Criar conta
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
