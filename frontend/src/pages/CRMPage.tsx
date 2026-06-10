import { useState, useEffect, useCallback } from "react";
import type { PageProps } from "../types";
import { Plus, Loader2, RefreshCw, TrendingUp, Target, Award, AlertTriangle } from "lucide-react";
import { Card, ActionButton, FormField, TextInput, TextArea, SelectInput, Modal, TabPanel } from "../components/common";
import { crudList, crudCreate, crudDelete } from "../api/crud";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import "leaflet/dist/leaflet.css";

// ─── Types ────────────────────────────────────────────────────────────────────

interface PipelineStage {
  stage: string;
  label: string;
  color: string;
  count: number;
  editais: PipelineEdital[];
}

interface PipelineEdital {
  id: string;
  numero: string;
  orgao: string;
  uf: string | null;
  objeto: string;
  valor_referencia: number | null;
  data_abertura: string | null;
  pipeline_stage: string;
  pipeline_substage: string | null;
  pipeline_tipo_venda: string | null;
  vendedor_responsavel: string | null;
  status: string;
}

interface CRMParametrizacao {
  id: string;
  tipo: string;
  valor: string;
  ordem: number;
  ativo: boolean;
}

interface EditalDecisao {
  id: string;
  edital_id: string;
  tipo: string;
  motivo_texto: string | null;
  justificativa: string | null;
  teve_contra_razao: boolean;
  pipeline_stage_anterior: string | null;
  created_at: string | null;
}

interface MapaUF {
  uf: string;
  lat: number;
  lon: number;
  editais: Array<{ id: string; numero: string; orgao: string; pipeline_stage: string; valor_referencia: number | null }>;
  stages: Record<string, number>;
}

interface AgendaItem {
  id: string;
  origem: "manual" | "auto";
  titulo: string;
  descricao: string | null;
  responsavel: string | null;
  data_limite: string | null;
  urgencia: string;
  concluido: boolean;
  pipeline_stage: string | null;
  edital_id: string | null;
  contrato_id: string | null;
}

interface KPIsCRM {
  kpis: {
    total_editais: number;
    analisados: number;
    participados: number;
    nao_participados: number;
    ganhos: number;
    perdidos: number;
    em_recurso: number;
    em_contra_razao: number;
    taxa_participacao_pct: number;
    taxa_vitoria_pct: number;
    valor_ganhos: number;
    valor_participados: number;
    ticket_medio_ganhos: number;
    ticket_medio_participados: number;
  };
}

// ─── Component ────────────────────────────────────────────────────────────────

export function CRMPage(_props?: PageProps) {
  const token = localStorage.getItem("editais_ia_access_token");
  const headers: Record<string, string> = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  const fmt = (v: number | null | undefined) => v != null ? `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}` : "—";

  // State
  const [pipeline, setPipeline] = useState<PipelineStage[]>([]);
  const [loadingPipeline, setLoadingPipeline] = useState(false);
  const [parametrizacoes, setParametrizacoes] = useState<CRMParametrizacao[]>([]);
  const [decisoes, setDecisoes] = useState<EditalDecisao[]>([]);
  const [mapaUFs, setMapaUFs] = useState<MapaUF[]>([]);
  const [mapaRanking, setMapaRanking] = useState<any[]>([]);
  const [mapaStatsSAM, setMapaStatsSAM] = useState<any>({});
  const [mapaSegmento, setMapaSegmento] = useState("");
  const [mapaMetrica, setMapaMetrica] = useState("quantidade");
  const [agenda, setAgenda] = useState<AgendaItem[]>([]);
  const [kpis, setKpis] = useState<KPIsCRM | null>(null);

  // Parametrizacoes sub-tab
  const [tipoParam, setTipoParam] = useState<"tipo_edital" | "agrupamento_portfolio" | "motivo_derrota">("tipo_edital");
  const [novoParam, setNovoParam] = useState("");

  // Decisao modal
  const [showDecisaoModal, setShowDecisaoModal] = useState(false);
  const [formDecisao, setFormDecisao] = useState({ edital_id: "", tipo: "nao_participacao", motivo_texto: "", justificativa: "", teve_contra_razao: false });

  // ─── Fetchers ───────────────────────────────────────────────────────────────
  const fetchPipeline = useCallback(async () => {
    setLoadingPipeline(true);
    try {
      const res = await fetch("/api/crm/pipeline", { headers });
      if (res.ok) { const data = await res.json(); setPipeline(data.pipeline || []); }
    } catch (e) { console.error(e); }
    setLoadingPipeline(false);
  }, []);

  const fetchParametrizacoes = useCallback(async () => {
    try {
      const res = await crudList("crm-parametrizacoes", { limit: 500 });
      setParametrizacoes((res.items || []) as unknown as CRMParametrizacao[]);
    } catch (e) { console.error(e); }
  }, []);

  const fetchDecisoes = useCallback(async () => {
    try {
      const res = await crudList("edital-decisoes", { limit: 200 });
      setDecisoes((res.items || []) as unknown as EditalDecisao[]);
    } catch (e) { console.error(e); }
  }, []);

  const fetchMapa = useCallback(async () => {
    try {
      const qs = new URLSearchParams();
      if (mapaSegmento) qs.set("segmento", mapaSegmento);
      if (mapaMetrica) qs.set("metrica", mapaMetrica);
      const q = qs.toString() ? `?${qs}` : "";
      const res = await fetch(`/api/crm/mapa${q}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setMapaUFs(data.ufs || []);
        setMapaRanking(data.ranking || []);
        setMapaStatsSAM(data.stat_cards_sam || {});
      }
    } catch (e) { console.error(e); }
  }, [mapaSegmento, mapaMetrica]);

  const fetchAgenda = useCallback(async () => {
    try {
      const res = await fetch("/api/crm/agenda", { headers });
      if (res.ok) { const data = await res.json(); setAgenda(data.items || []); }
    } catch (e) { console.error(e); }
  }, []);

  const fetchKPIs = useCallback(async () => {
    try {
      const res = await fetch("/api/crm/kpis", { headers });
      if (res.ok) setKpis(await res.json());
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => {
    fetchPipeline();
    fetchParametrizacoes();
    fetchDecisoes();
    fetchMapa();
    fetchAgenda();
    fetchKPIs();
  }, [fetchPipeline, fetchParametrizacoes, fetchDecisoes, fetchMapa, fetchAgenda, fetchKPIs]);

  // ─── Actions ────────────────────────────────────────────────────────────────
  const handleMoveStage = async (editalId: string, newStage: string) => {
    try {
      await fetch(`/api/editais/${editalId}/pipeline-stage`, {
        method: "PUT",
        headers,
        body: JSON.stringify({ pipeline_stage: newStage }),
      });
      fetchPipeline();
    } catch (e) { console.error(e); }
  };

  const handleMigrate = async () => {
    try {
      await fetch("/api/crm/pipeline/migrate", { method: "POST", headers });
      fetchPipeline();
    } catch (e) { console.error(e); }
  };

  const handleSeedParam = async () => {
    try {
      await fetch("/api/crm/parametrizacoes/seed", { method: "POST", headers });
      fetchParametrizacoes();
    } catch (e) { console.error(e); }
  };

  const handleAddParam = async () => {
    if (!novoParam.trim()) return;
    try {
      await crudCreate("crm-parametrizacoes", { tipo: tipoParam, valor: novoParam, ordem: parametrizacoes.filter(p => p.tipo === tipoParam).length, ativo: true });
      setNovoParam("");
      fetchParametrizacoes();
    } catch (e) { console.error(e); }
  };

  const handleDeleteParam = async (id: string) => {
    try {
      await crudDelete("crm-parametrizacoes", id);
      fetchParametrizacoes();
    } catch (e) { console.error(e); }
  };

  const handleCreateDecisao = async () => {
    try {
      await crudCreate("edital-decisoes", { ...formDecisao });
      setShowDecisaoModal(false);
      setFormDecisao({ edital_id: "", tipo: "nao_participacao", motivo_texto: "", justificativa: "", teve_contra_razao: false });
      fetchDecisoes();
    } catch (e) { console.error(e); }
  };

  // ─── TAB: Pipeline Kanban ────────────────────────────────────────────────────
  const tabPipeline = (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <h3>Pipeline de Vendas ({pipeline.reduce((s, p) => s + p.count, 0)} editais)</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <ActionButton label="Migrar Legado" onClick={handleMigrate} variant="secondary" icon={<RefreshCw size={14} />} />
          <ActionButton label="Atualizar" onClick={fetchPipeline} icon={<RefreshCw size={14} />} />
        </div>
      </div>
      {loadingPipeline ? <Loader2 className="animate-spin" /> : (
        <div style={{ display: "flex", gap: 12, overflowX: "auto", paddingBottom: 16 }}>
          {pipeline.map(col => (
            <div key={col.stage} style={{ minWidth: 260, maxWidth: 260 }}>
              <Card>
                <div style={{ borderLeft: `4px solid ${col.color}`, paddingLeft: 8, marginBottom: 8 }}>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>{col.label}</div>
                  <div style={{ fontSize: 11, color: "#6b7280" }}>{col.count} editais</div>
                </div>
                <div style={{ maxHeight: 500, overflowY: "auto" }}>
                  {col.editais.map(e => (
                    <div key={e.id} style={{ padding: 8, marginBottom: 6, background: "#f9fafb", borderRadius: 6, borderLeft: `3px solid ${col.color}` }}>
                      <div style={{ fontSize: 12, fontWeight: 600 }}>{e.numero}</div>
                      <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>{e.orgao} {e.uf ? `(${e.uf})` : ""}</div>
                      <div style={{ fontSize: 10, color: "#9ca3af", marginTop: 4 }}>{e.objeto.substring(0, 60)}{e.objeto.length > 60 ? "..." : ""}</div>
                      {e.valor_referencia && <div style={{ fontSize: 11, fontWeight: 600, color: "#16a34a", marginTop: 4 }}>{fmt(e.valor_referencia)}</div>}
                      <div style={{ marginTop: 6 }}>
                        <select
                          value={e.pipeline_stage}
                          onChange={ev => handleMoveStage(e.id, ev.target.value)}
                          style={{ width: "100%", fontSize: 10, padding: 4, border: "1px solid #e5e7eb", borderRadius: 4 }}
                        >
                          {pipeline.map(s => <option key={s.stage} value={s.stage}>{s.label}</option>)}
                        </select>
                      </div>
                    </div>
                  ))}
                  {col.count === 0 && <div style={{ padding: 16, textAlign: "center", color: "#9ca3af", fontSize: 11 }}>Vazio</div>}
                </div>
              </Card>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  // ─── TAB: Parametrizacoes ────────────────────────────────────────────────────
  const paramsFiltered = parametrizacoes.filter(p => p.tipo === tipoParam);
  const tabParametrizacoes = (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <h3>Parametrizações CRM</h3>
        <ActionButton label="Popular Padrões" onClick={handleSeedParam} variant="secondary" />
      </div>
      <Card>
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          {(["tipo_edital", "agrupamento_portfolio", "motivo_derrota"] as const).map(t => (
            <button
              key={t}
              onClick={() => setTipoParam(t)}
              style={{
                padding: "8px 16px",
                background: tipoParam === t ? "#3b82f6" : "#f3f4f6",
                color: tipoParam === t ? "white" : "#374151",
                border: "none",
                borderRadius: 6,
                cursor: "pointer",
              }}
            >
              {t === "tipo_edital" ? "Tipos de Edital" : t === "agrupamento_portfolio" ? "Agrupamento Portfolio" : "Motivos de Derrota"}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <TextInput value={novoParam} onChange={setNovoParam} placeholder="Novo valor..." />
          <ActionButton label="Adicionar" onClick={handleAddParam} icon={<Plus size={14} />} />
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr style={{ borderBottom: "2px solid #e5e7eb" }}>
            <th style={{ padding: 8, textAlign: "left" }}>Ordem</th>
            <th style={{ padding: 8, textAlign: "left" }}>Valor</th>
            <th style={{ padding: 8, textAlign: "center" }}>Ativo</th>
            <th style={{ padding: 8, textAlign: "right" }}>Ação</th>
          </tr></thead>
          <tbody>{paramsFiltered.map(p => (
            <tr key={p.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
              <td style={{ padding: 8 }}>{p.ordem}</td>
              <td style={{ padding: 8 }}>{p.valor}</td>
              <td style={{ padding: 8, textAlign: "center" }}>{p.ativo ? "✅" : "❌"}</td>
              <td style={{ padding: 8, textAlign: "right" }}>
                <ActionButton label="Excluir" onClick={() => handleDeleteParam(p.id)} size="sm" variant="danger" />
              </td>
            </tr>
          ))}
          {paramsFiltered.length === 0 && <tr><td colSpan={4} style={{ padding: 20, textAlign: "center", color: "#9ca3af" }}>Nenhum valor cadastrado</td></tr>}
          </tbody>
        </table>
      </Card>
    </div>
  );

  // ─── TAB: Decisões ───────────────────────────────────────────────────────────
  const motivosDerrota = parametrizacoes.filter(p => p.tipo === "motivo_derrota" && p.ativo);
  const tabDecisoes = (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <h3>Decisões de Editais</h3>
        <ActionButton label="Nova Decisão" onClick={() => setShowDecisaoModal(true)} icon={<Plus size={16} />} />
      </div>
      <Card>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr style={{ borderBottom: "2px solid #e5e7eb" }}>
            <th style={{ padding: 8, textAlign: "left" }}>Data</th>
            <th style={{ padding: 8, textAlign: "left" }}>Tipo</th>
            <th style={{ padding: 8, textAlign: "left" }}>Edital</th>
            <th style={{ padding: 8, textAlign: "left" }}>Motivo</th>
            <th style={{ padding: 8, textAlign: "center" }}>Contra-Razão</th>
          </tr></thead>
          <tbody>{decisoes.map(d => (
            <tr key={d.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
              <td style={{ padding: 8 }}>{d.created_at ? new Date(d.created_at).toLocaleDateString("pt-BR") : "—"}</td>
              <td style={{ padding: 8 }}>
                <span style={{ padding: "2px 8px", borderRadius: 12, fontSize: 11, background: d.tipo === "perda" ? "#fee2e2" : "#fef3c7", color: d.tipo === "perda" ? "#991b1b" : "#92400e" }}>
                  {d.tipo === "perda" ? "Perda" : "Não Participação"}
                </span>
              </td>
              <td style={{ padding: 8, fontSize: 11 }}>{d.edital_id.substring(0, 8)}...</td>
              <td style={{ padding: 8 }}>{d.motivo_texto || "—"}</td>
              <td style={{ padding: 8, textAlign: "center" }}>{d.teve_contra_razao ? "✅" : "—"}</td>
            </tr>
          ))}
          {decisoes.length === 0 && <tr><td colSpan={5} style={{ padding: 20, textAlign: "center", color: "#9ca3af" }}>Nenhuma decisão registrada</td></tr>}
          </tbody>
        </table>
      </Card>
    </div>
  );

  // ─── TAB: Mapa (Leaflet/OSM real) — Sprint 7 UC-ME02 expandido ──────────────
  const ufColor = (editais: any[]) => {
    const val = editais.reduce((s: number, e: any) => s + (e.valor_referencia || 0), 0);
    if (val > 500000) return "#166534";
    if (val > 100000) return "#16a34a";
    if (val > 0) return "#eab308";
    return "#9ca3af";
  };
  const tabMapa = (
    <div>
      {/* Stat Cards SAM */}
      <div className="stats-row" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <div className="stat-icon success"><Target size={24} /></div>
          <div className="stat-content">
            <span className="stat-value">{mapaStatsSAM.maior_oportunidade || "N/A"}</span>
            <span className="stat-label">UF Maior Oportunidade</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon warning"><AlertTriangle size={24} /></div>
          <div className="stat-content">
            <span className="stat-value">{mapaStatsSAM.menor_participacao || "N/A"}</span>
            <span className="stat-label">UF Menor Participacao</span>
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-icon" style={{ background: "#fee2e2", color: "#dc2626" }}><AlertTriangle size={24} /></div>
          <div className="stat-content">
            <span className="stat-value">{mapaStatsSAM.sem_presenca || 0}</span>
            <span className="stat-label">UFs sem Presenca</span>
          </div>
        </div>
      </div>

      {/* Filtros Mapa */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <FormField label="Segmento">
          <SelectInput value={mapaSegmento} onChange={(v: string) => setMapaSegmento(v)} options={[
            { value: "", label: "Todos" }, { value: "hematologia", label: "Hematologia" },
            { value: "bioquimica", label: "Bioquimica" }, { value: "coagulacao", label: "Coagulacao" },
            { value: "imunologia", label: "Imunologia" }, { value: "biomol", label: "Biomol/PCR" },
          ]} />
        </FormField>
        <FormField label="Metrica">
          <SelectInput value={mapaMetrica} onChange={(v: string) => setMapaMetrica(v)} options={[
            { value: "quantidade", label: "Quantidade" }, { value: "valor", label: "Valor R$" },
          ]} />
        </FormField>
      </div>

      <h3 style={{ marginBottom: 16 }}>Distribuicao Geografica ({mapaUFs.reduce((s, u) => s + u.editais.length, 0)} editais)</h3>
      <div style={{ height: 500, borderRadius: 8, overflow: "hidden", border: "1px solid #e5e7eb" }}>
        {mapaUFs.length > 0 ? (
          <MapContainer center={[-15.78, -47.93]} zoom={4} style={{ height: "100%", width: "100%" }} scrollWheelZoom={true}>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {mapaUFs.map(uf => (
              <CircleMarker
                key={uf.uf}
                center={[uf.lat, uf.lon]}
                radius={Math.max(8, Math.min(35, uf.editais.length * 3))}
                pathOptions={{ color: ufColor(uf.editais), fillColor: ufColor(uf.editais), fillOpacity: 0.6, weight: 2 }}
              >
                <Popup>
                  <div style={{ minWidth: 180 }}>
                    <strong style={{ fontSize: 16 }}>{uf.uf}</strong>
                    <div style={{ fontSize: 22, fontWeight: 700, color: "#3b82f6", margin: "4px 0" }}>{uf.editais.length} editais</div>
                    <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 4 }}>
                      Valor: {fmt(uf.editais.reduce((s: number, e: any) => s + (e.valor_referencia || 0), 0))}
                    </div>
                    {Object.entries(uf.stages).map(([stage, count]) => (
                      <div key={stage} style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                        <span style={{ color: "#6b7280" }}>{String(stage).replace(/_/g, " ")}</span>
                        <span style={{ fontWeight: 600 }}>{String(count)}</span>
                      </div>
                    ))}
                  </div>
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
        ) : (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#9ca3af" }}>
            Nenhum edital com UF cadastrada
          </div>
        )}
      </div>

      {/* Ranking UFs */}
      {mapaRanking.length > 0 && (
        <Card title="Ranking de UFs" style={{ marginTop: 16 }}>
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>UF</th><th>Editais SAM</th><th>Valor</th><th>Participados</th><th>Taxa %</th><th>Gap</th>
                </tr>
              </thead>
              <tbody>
                {mapaRanking.slice(0, 15).map((r: any, i: number) => (
                  <tr key={i}>
                    <td><strong>{r.uf}</strong></td>
                    <td>{r.editais}</td>
                    <td>{fmt(r.valor)}</td>
                    <td>{r.participados}</td>
                    <td>
                      <span style={{ color: r.taxa > 50 ? "#16a34a" : r.taxa > 20 ? "#eab308" : "#dc2626", fontWeight: 600 }}>
                        {r.taxa}%
                      </span>
                    </td>
                    <td>{r.gap}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );

  // ─── TAB: Agenda ─────────────────────────────────────────────────────────────
  const urgencyColor = (u: string) => u === "critica" ? "#dc2626" : u === "alta" ? "#eab308" : u === "baixa" ? "#9ca3af" : "#3b82f6";
  const tabAgenda = (
    <div>
      <h3 style={{ marginBottom: 16 }}>Agenda de Compromissos ({agenda.length} itens)</h3>
      <Card>
        {agenda.map(it => (
          <div key={it.id} style={{ padding: 12, borderLeft: `4px solid ${urgencyColor(it.urgencia)}`, marginBottom: 8, background: "#f9fafb", borderRadius: 6 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600 }}>{it.titulo}</div>
                {it.descricao && <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>{it.descricao}</div>}
                {it.responsavel && <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 2 }}>👤 {it.responsavel}</div>}
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 12, color: urgencyColor(it.urgencia), fontWeight: 700 }}>{it.urgencia.toUpperCase()}</div>
                <div style={{ fontSize: 11, color: "#6b7280" }}>{it.data_limite ? new Date(it.data_limite).toLocaleDateString("pt-BR") : "—"}</div>
                <div style={{ fontSize: 10, color: "#9ca3af" }}>{it.origem === "auto" ? "automático" : "manual"}</div>
              </div>
            </div>
          </div>
        ))}
        {agenda.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "#9ca3af" }}>Nenhum item na agenda</div>}
      </Card>
    </div>
  );

  // ─── TAB: KPIs ───────────────────────────────────────────────────────────────
  const tabKPIs = !kpis ? <Loader2 className="animate-spin" /> : (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 20 }}>
        {[
          { label: "Total Editais", value: kpis.kpis.total_editais, color: "#3b82f6", icon: <Target size={24} /> },
          { label: "Analisados", value: kpis.kpis.analisados, color: "#8b5cf6", icon: <TrendingUp size={24} /> },
          { label: "Participados", value: kpis.kpis.participados, color: "#eab308", icon: <TrendingUp size={24} /> },
          { label: "Não Participados", value: kpis.kpis.nao_participados, color: "#6b7280", icon: <AlertTriangle size={24} /> },
          { label: "Ganhos", value: kpis.kpis.ganhos, color: "#16a34a", icon: <Award size={24} /> },
          { label: "Perdidos", value: kpis.kpis.perdidos, color: "#dc2626", icon: <AlertTriangle size={24} /> },
          { label: "Em Recurso", value: kpis.kpis.em_recurso, color: "#0891b2", icon: <TrendingUp size={24} /> },
          { label: "Em Contra-Razão", value: kpis.kpis.em_contra_razao, color: "#06b6d4", icon: <TrendingUp size={24} /> },
        ].map((s, i) => (
          <Card key={i}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ background: s.color + "20", color: s.color, borderRadius: 8, padding: 8 }}>{s.icon}</div>
              <div><div style={{ fontSize: 11, color: "#6b7280" }}>{s.label}</div><div style={{ fontSize: 22, fontWeight: 700 }}>{s.value}</div></div>
            </div>
          </Card>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 16 }}>
        <Card>
          <h4 style={{ marginBottom: 12 }}>Taxas de Conversão</h4>
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
              <span>Taxa Participação (Analisados)</span>
              <span style={{ fontWeight: 700 }}>{kpis.kpis.taxa_participacao_pct}%</span>
            </div>
            <div style={{ width: "100%", height: 8, background: "#e5e7eb", borderRadius: 4 }}>
              <div style={{ width: `${Math.min(kpis.kpis.taxa_participacao_pct, 100)}%`, height: "100%", borderRadius: 4, background: "#3b82f6" }} />
            </div>
          </div>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
              <span>Taxa Vitória (Participados)</span>
              <span style={{ fontWeight: 700 }}>{kpis.kpis.taxa_vitoria_pct}%</span>
            </div>
            <div style={{ width: "100%", height: 8, background: "#e5e7eb", borderRadius: 4 }}>
              <div style={{ width: `${Math.min(kpis.kpis.taxa_vitoria_pct, 100)}%`, height: "100%", borderRadius: 4, background: "#16a34a" }} />
            </div>
          </div>
        </Card>
        <Card>
          <h4 style={{ marginBottom: 12 }}>Valores e Tickets</h4>
          <div style={{ fontSize: 13, display: "grid", gap: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span>Valor Ganhos</span><span style={{ fontWeight: 700, color: "#16a34a" }}>{fmt(kpis.kpis.valor_ganhos)}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span>Valor Participados</span><span style={{ fontWeight: 700 }}>{fmt(kpis.kpis.valor_participados)}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span>Ticket Médio Ganhos</span><span style={{ fontWeight: 700 }}>{fmt(kpis.kpis.ticket_medio_ganhos)}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span>Ticket Médio Participados</span><span style={{ fontWeight: 700 }}>{fmt(kpis.kpis.ticket_medio_participados)}</span></div>
          </div>
        </Card>
      </div>
    </div>
  );

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 20, fontSize: 22, fontWeight: 700 }}>CRM — Gestão Comercial</h2>
      <TabPanel tabs={[
        { id: "pipeline", label: "Pipeline" },
        { id: "parametrizacoes", label: "Parametrizações" },
        { id: "mapa", label: "Mapa" },
        { id: "agenda", label: "Agenda" },
        { id: "kpis", label: "KPIs" },
        { id: "decisoes", label: "Decisões" },
      ]}>
        {(activeTab) => {
          if (activeTab === "pipeline") return tabPipeline;
          if (activeTab === "parametrizacoes") return tabParametrizacoes;
          if (activeTab === "mapa") return tabMapa;
          if (activeTab === "agenda") return tabAgenda;
          if (activeTab === "kpis") return tabKPIs;
          return tabDecisoes;
        }}
      </TabPanel>

      {showDecisaoModal && (
        <Modal title="Nova Decisão" onClose={() => setShowDecisaoModal(false)}>
          <FormField label="ID do Edital"><TextInput value={formDecisao.edital_id} onChange={v => setFormDecisao(p => ({ ...p, edital_id: v }))} /></FormField>
          <FormField label="Tipo"><SelectInput value={formDecisao.tipo} onChange={v => setFormDecisao(p => ({ ...p, tipo: v }))} options={[
            { value: "nao_participacao", label: "Não Participação" },
            { value: "perda", label: "Perda Definitiva" },
          ]} /></FormField>
          <FormField label="Motivo">
            <SelectInput
              value={formDecisao.motivo_texto}
              onChange={v => setFormDecisao(p => ({ ...p, motivo_texto: v }))}
              options={[{ value: "", label: "Selecione..." }, ...motivosDerrota.map(m => ({ value: m.valor, label: m.valor }))]}
            />
          </FormField>
          <FormField label="Justificativa"><TextArea value={formDecisao.justificativa} onChange={v => setFormDecisao(p => ({ ...p, justificativa: v }))} /></FormField>
          <FormField label="Teve Contra-Razão?">
            <SelectInput
              value={formDecisao.teve_contra_razao ? "sim" : "nao"}
              onChange={v => setFormDecisao(p => ({ ...p, teve_contra_razao: v === "sim" }))}
              options={[{ value: "nao", label: "Não" }, { value: "sim", label: "Sim" }]}
            />
          </FormField>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, marginTop: 16 }}>
            <ActionButton label="Cancelar" onClick={() => setShowDecisaoModal(false)} variant="secondary" />
            <ActionButton label="Salvar" onClick={handleCreateDecisao} />
          </div>
        </Modal>
      )}
    </div>
  );
}
