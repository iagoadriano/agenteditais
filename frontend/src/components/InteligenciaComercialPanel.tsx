// Fase 2 — Painel de Inteligência Comercial (RF-CLA, RF-SCO, RF-PRE)
// Exibido no painel lateral de detalhes do edital (CaptacaoPage).
// Cada ação é on-demand para não pesar a abertura do painel.
import { useState } from "react";
import {
  classificarEdital,
  getScoreComercial,
  getRecomendacaoPreco,
  CATEGORIA_LABELS,
  type ClassificarResponse,
  type ScoreComercialResponse,
  type RecomendacaoPrecoResponse,
} from "../api/inteligencia";

interface Props {
  editalId: string | null;
}

const fmtBRL = (v: number) =>
  v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const corScore = (s: number) =>
  s >= 70 ? "#22c55e" : s >= 45 ? "#eab308" : "#ef4444";

const CORES_RECOMENDACAO: Record<string, string> = {
  GO: "#22c55e",
  AVALIAR: "#eab308",
  NO_GO: "#ef4444",
};

const labelStyle: React.CSSProperties = {
  color: "#64748b",
  fontSize: "12px",
};
const boxStyle: React.CSSProperties = {
  backgroundColor: "#0f172a",
  padding: "8px",
  borderRadius: "6px",
  fontSize: "12px",
  lineHeight: "1.5",
  marginTop: "6px",
};
const btnStyle: React.CSSProperties = {
  backgroundColor: "#1e293b",
  color: "#e2e8f0",
  border: "1px solid #334155",
  borderRadius: "6px",
  padding: "6px 10px",
  fontSize: "12px",
  cursor: "pointer",
};

export default function InteligenciaComercialPanel({ editalId }: Props) {
  const [classif, setClassif] = useState<ClassificarResponse | null>(null);
  const [score, setScore] = useState<ScoreComercialResponse | null>(null);
  const [preco, setPreco] = useState<RecomendacaoPrecoResponse | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  if (!editalId) {
    return (
      <div className="panel-section">
        <h4>Inteligência Comercial</h4>
        <div style={{ ...boxStyle, color: "#64748b", fontStyle: "italic" }}>
          Salve o edital no banco para classificar, calcular score comercial e
          recomendar preço.
        </div>
      </div>
    );
  }

  const executar = async (acao: "classificar" | "score" | "preco") => {
    setLoading(acao);
    setErro(null);
    try {
      if (acao === "classificar") setClassif(await classificarEdital(editalId));
      if (acao === "score") setScore(await getScoreComercial(editalId));
      if (acao === "preco") setPreco(await getRecomendacaoPreco(editalId));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro inesperado");
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="panel-section">
      <h4>Inteligência Comercial</h4>

      <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "6px" }}>
        <button style={btnStyle} disabled={loading !== null} onClick={() => executar("classificar")}>
          {loading === "classificar" ? "Classificando..." : "Classificar"}
        </button>
        <button style={btnStyle} disabled={loading !== null} onClick={() => executar("score")}>
          {loading === "score" ? "Calculando..." : "Score Comercial"}
        </button>
        <button style={btnStyle} disabled={loading !== null} onClick={() => executar("preco")}>
          {loading === "preco" ? "Analisando..." : "Recomendar Preço"}
        </button>
      </div>

      {erro && (
        <div style={{ ...boxStyle, color: "#ef4444" }}>{erro}</div>
      )}

      {/* RF-CLA — resultado da classificação */}
      {classif && (
        <div style={boxStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={labelStyle}>Categoria sugerida:</span>
            <strong style={{ color: "#e2e8f0" }}>
              {CATEGORIA_LABELS[classif.classificacao.categoria] || classif.classificacao.categoria}
            </strong>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: "4px" }}>
            <span style={labelStyle}>Confiança:</span>
            <span style={{ color: corScore(classif.classificacao.confianca * 100) }}>
              {Math.round(classif.classificacao.confianca * 100)}%
            </span>
          </div>
          {classif.classificacao.sinais.length > 0 && (
            <div style={{ marginTop: "4px", color: "#94a3b8" }}>
              Sinais: {classif.classificacao.sinais.join(", ")}
            </div>
          )}
          <div style={{ marginTop: "4px", color: classif.aplicada ? "#22c55e" : "#eab308" }}>
            {classif.aplicada
              ? "Categoria aplicada ao edital"
              : "Confiança insuficiente — categoria não aplicada automaticamente"}
          </div>
        </div>
      )}

      {/* RF-SCO — score comercial */}
      {score && (
        <div style={boxStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={labelStyle}>Score comercial:</span>
            <strong style={{ color: corScore(score.score_final), fontSize: "16px" }}>
              {score.score_final}
            </strong>
            <span
              style={{
                color: CORES_RECOMENDACAO[score.recomendacao],
                border: `1px solid ${CORES_RECOMENDACAO[score.recomendacao]}`,
                borderRadius: "4px",
                padding: "1px 8px",
                fontSize: "11px",
                fontWeight: 600,
              }}
            >
              {score.recomendacao.replace("_", " ")}
            </span>
          </div>
          {(
            [
              ["Logística", score.componentes.logistico],
              ["Porte x Valor", score.componentes.porte],
              ["Histórico", score.componentes.historico],
              ["Prazo", score.componentes.prazo],
            ] as const
          ).map(([nome, comp]) => (
            <div key={nome} style={{ marginTop: "6px" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={labelStyle}>{nome}</span>
                <span style={{ color: corScore(comp.score) }}>{comp.score}</span>
              </div>
              <div style={{ color: "#94a3b8", fontSize: "11px" }}>{comp.motivo}</div>
            </div>
          ))}
        </div>
      )}

      {/* RF-PRE — recomendação de preço */}
      {preco && (
        <div style={boxStyle}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={labelStyle}>Valor de referência:</span>
            <span style={{ color: "#e2e8f0" }}>{fmtBRL(preco.valor_referencia)}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: "4px" }}>
            <span style={labelStyle}>Amostra histórica:</span>
            <span style={{ color: "#e2e8f0" }}>
              {preco.amostra} certame(s)
              {preco.contexto_amostra === "mesma_categoria_ou_uf" ? " (similares)" : ""}
            </span>
          </div>
          {(
            [
              ["Conservador", preco.cenarios.conservador, "#22c55e"],
              ["Equilibrado", preco.cenarios.equilibrado, "#eab308"],
              ["Competitivo", preco.cenarios.competitivo, "#ef4444"],
            ] as const
          ).map(([nome, cenario, cor]) => (
            <div key={nome} style={{ display: "flex", justifyContent: "space-between", marginTop: "6px" }}>
              <span style={{ color: cor, fontSize: "12px" }}>{nome}</span>
              <span style={{ color: "#e2e8f0" }}>
                {fmtBRL(cenario.preco_sugerido)}{" "}
                <span style={labelStyle}>(-{cenario.desconto_percentual.toFixed(1)}%)</span>
              </span>
            </div>
          ))}
          {preco.curva_probabilidade.length > 0 && (
            <div style={{ marginTop: "8px" }}>
              <span style={labelStyle}>Probabilidade de vitória por desconto:</span>
              <div style={{ display: "flex", alignItems: "flex-end", gap: "2px", height: "40px", marginTop: "4px" }}>
                {preco.curva_probabilidade.map((p) => (
                  <div
                    key={p.desconto_percentual}
                    title={`-${p.desconto_percentual}% → ${Math.round(p.probabilidade_vitoria * 100)}% de chance (${fmtBRL(p.preco)})`}
                    style={{
                      flex: 1,
                      height: `${Math.max(p.probabilidade_vitoria * 100, 3)}%`,
                      backgroundColor: corScore(p.probabilidade_vitoria * 100),
                      borderRadius: "2px 2px 0 0",
                      opacity: 0.85,
                    }}
                  />
                ))}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", ...labelStyle }}>
                <span>0%</span>
                <span>desconto</span>
                <span>40%</span>
              </div>
            </div>
          )}
          {preco.aviso && (
            <div style={{ marginTop: "6px", color: "#eab308", fontSize: "11px" }}>{preco.aviso}</div>
          )}
        </div>
      )}
    </div>
  );
}
