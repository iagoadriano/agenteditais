import { useState, useEffect, useCallback } from "react";
import type { PageProps } from "../types";
import { Search, Download, Loader2 } from "lucide-react";
import { Card, DataTable, ActionButton, FormField, TextInput, TextArea, SelectInput, Modal, TabPanel } from "../components/common";
import type { Column } from "../components/common";

// ─── Types ────────────────────────────────────────────────────────────────────

interface AtaResult {
  titulo: string;
  orgao: string;
  uf: string;
  url_pncp: string;
  data_publicacao?: string;
  data_vigencia_fim?: string;
}

interface AtaSalva {
  id: string;
  titulo: string;
  orgao: string;
  uf: string;
  url_pncp: string;
  data_publicacao: string | null;
  data_vigencia_inicio: string | null;
  data_vigencia_fim: string | null;
  created_at: string | null;
}

interface ExtractedItem {
  descricao: string;
  vencedor: string;
  valor_unitario: number;
  quantidade: number;
}

interface ARPSaldo {
  id: string;
  item_descricao: string;
  quantidade_registrada: number;
  consumido_participante: number;
  consumido_carona: number;
  saldo_disponivel: number;
  valor_unitario: number;
}

interface Carona {
  id: string;
  orgao_solicitante: string;
  quantidade_solicitada: number;
  status: string;
  data_solicitacao: string | null;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function AtasPage(_props?: PageProps) {
  const token = localStorage.getItem("editais_ia_access_token");
  const headers: Record<string, string> = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

  // Tab 1: Buscar
  const [termo, setTermo] = useState("");
  const [ufFiltro, setUfFiltro] = useState("");
  const [searchResults, setSearchResults] = useState<AtaResult[]>([]);
  const [searching, setSearching] = useState(false);

  // Tab 2: Extrair
  const [extractUrl, setExtractUrl] = useState("");
  const [extractTexto, setExtractTexto] = useState("");
  const [extractedItems, setExtractedItems] = useState<ExtractedItem[]>([]);
  const [extracting, setExtracting] = useState(false);

  // Tab 3: Minhas Atas
  const [minhasAtas, setMinhasAtas] = useState<AtaSalva[]>([]);
  const [atasStats, setAtasStats] = useState({ total: 0, vigentes: 0, vencidas: 0 });
  const [loadingAtas, setLoadingAtas] = useState(false);

  // Tab 4: Saldo ARP
  const [selectedAta, setSelectedAta] = useState("");
  const [saldos, setSaldos] = useState<ARPSaldo[]>([]);
  const [caronas, setCaronas] = useState<Carona[]>([]);
  const [showCaronaModal, setShowCaronaModal] = useState(false);
  const [selectedSaldo, setSelectedSaldo] = useState<ARPSaldo | null>(null);
  const [caronaOrgao, setCaronaOrgao] = useState("");
  const [caronaCnpj, setCaronaCnpj] = useState("");
  const [caronaQtd, setCaronaQtd] = useState("");
  const [caronaJustificativa, setCaronaJustificativa] = useState("");

  const fmt = (v: number | null | undefined) => v != null ? `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}` : "—";

  // Buscar atas
  const handleBuscar = async () => {
    if (termo.length < 3) return;
    setSearching(true);
    try {
      const params = new URLSearchParams({ termo });
      if (ufFiltro) params.append("uf", ufFiltro);
      const res = await fetch(`/api/atas/buscar?${params}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setSearchResults(data.atas || data.resultados || (Array.isArray(data) ? data : []));
      }
    } catch (e) { console.error(e); }
    setSearching(false);
  };

  const handleSalvarAta = async (ata: AtaResult) => {
    try {
      await fetch("/api/atas/salvar", { method: "POST", headers, body: JSON.stringify(ata) });
      fetchMinhasAtas();
    } catch (e) { console.error(e); }
  };

  // Extrair PDF
  const handleExtrair = async () => {
    setExtracting(true);
    try {
      const body: Record<string, string> = {};
      if (extractUrl) body.url = extractUrl;
      if (extractTexto) body.texto = extractTexto;
      const res = await fetch("/api/atas/extrair-pdf", { method: "POST", headers, body: JSON.stringify(body) });
      if (res.ok) {
        const data = await res.json();
        setExtractedItems(data.itens || data.items || []);
      }
    } catch (e) { console.error(e); }
    setExtracting(false);
  };

  // Minhas Atas
  const fetchMinhasAtas = useCallback(async () => {
    setLoadingAtas(true);
    try {
      const res = await fetch("/api/atas/minhas", { headers });
      if (res.ok) {
        const data = await res.json();
        setMinhasAtas(data.atas || []);
        setAtasStats(data.stats || { total: 0, vigentes: 0, vencidas: 0 });
      }
    } catch (e) { console.error(e); }
    setLoadingAtas(false);
  }, []);

  useEffect(() => { fetchMinhasAtas(); }, [fetchMinhasAtas]);

  // Saldo ARP
  const fetchSaldos = async (ataId: string) => {
    try {
      const res = await fetch(`/api/atas/${ataId}/saldos`, { headers });
      if (res.ok) setSaldos(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchCaronas = async (saldoId: string) => {
    if (!selectedAta) return;
    try {
      const res = await fetch(`/api/atas/${selectedAta}/saldos/${saldoId}/caronas`, { headers });
      if (res.ok) setCaronas(await res.json());
    } catch (e) { console.error(e); }
  };

  const handleSolicitarCarona = async () => {
    if (!selectedAta || !selectedSaldo) return;
    try {
      const res = await fetch(`/api/atas/${selectedAta}/saldos/${selectedSaldo.id}/caronas`, {
        method: "POST", headers,
        body: JSON.stringify({ orgao_solicitante: caronaOrgao, cnpj_solicitante: caronaCnpj, quantidade_solicitada: parseFloat(caronaQtd), justificativa: caronaJustificativa }),
      });
      if (res.ok) {
        setShowCaronaModal(false);
        fetchCaronas(selectedSaldo.id);
        fetchSaldos(selectedAta);
      } else {
        const err = await res.json();
        alert(err.error || "Erro ao solicitar carona");
      }
    } catch (e) { console.error(e); }
  };

  // UF options
  const ufs = ["", "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"];

  const searchCols: Column<AtaResult>[] = [
    { key: "titulo", header: "Título" },
    { key: "orgao", header: "Órgão" },
    { key: "uf", header: "UF" },
    { key: "data_publicacao", header: "Publicação" },
    { key: "url_pncp", header: "Ações", render: (r) => (
      <div style={{ display: "flex", gap: 8 }}>
        <ActionButton label="Salvar" onClick={() => handleSalvarAta(r)} size="sm" />
        <ActionButton label="Extrair" onClick={() => { setExtractUrl(r.url_pncp); }} size="sm" variant="secondary" />
      </div>
    )},
  ];

  const atasCols: Column<AtaSalva>[] = [
    { key: "titulo", header: "Título" },
    { key: "orgao", header: "Órgão" },
    { key: "uf", header: "UF" },
    { key: "data_vigencia_fim", header: "Vigência", render: (r) => {
      if (!r.data_vigencia_fim) return "—";
      const fim = new Date(r.data_vigencia_fim);
      const dias = Math.ceil((fim.getTime() - Date.now()) / 86400000);
      const vigente = dias > 0;
      return <span style={{ background: vigente ? "#dcfce7" : "#fee2e2", color: vigente ? "#166534" : "#991b1b", padding: "2px 10px", borderRadius: 12, fontSize: 12 }}>{vigente ? `${dias}d restantes` : `Vencida há ${Math.abs(dias)}d`}</span>;
    }},
  ];

  const saldoCols: Column<ARPSaldo>[] = [
    { key: "item_descricao", header: "Item" },
    { key: "quantidade_registrada", header: "Qtd Registrada" },
    { key: "consumido_participante", header: "Consumo Part." },
    { key: "consumido_carona", header: "Consumo Carona" },
    { key: "saldo_disponivel", header: "Saldo" },
    { key: "id", header: "% Consumido", render: (r) => {
      const pct = r.quantidade_registrada > 0 ? Math.round(((r.consumido_participante + r.consumido_carona) / r.quantidade_registrada) * 100) : 0;
      const color = pct < 70 ? "#16a34a" : pct < 90 ? "#eab308" : "#dc2626";
      return (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 80, height: 8, background: "#e5e7eb", borderRadius: 4 }}>
            <div style={{ width: `${Math.min(pct, 100)}%`, height: "100%", background: color, borderRadius: 4 }} />
          </div>
          <span style={{ fontSize: 12 }}>{pct}%</span>
        </div>
      );
    }},
    { key: "id", header: "Ação", render: (r) => (
      <ActionButton label="Carona" onClick={() => { setSelectedSaldo(r); fetchCaronas(r.id); setShowCaronaModal(true); }} size="sm" />
    )},
  ];

  // Tabs
  const tabBuscar = (
    <div>
      <Card>
        <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <FormField label="Termo de busca (mín. 3 caracteres)">
              <TextInput value={termo} onChange={setTermo} placeholder="Ex: reagentes, equipamentos..." />
            </FormField>
          </div>
          <div style={{ width: 100 }}>
            <FormField label="UF">
              <SelectInput value={ufFiltro} onChange={setUfFiltro} options={ufs.map(u => ({ value: u, label: u || "Todas" }))} />
            </FormField>
          </div>
          <ActionButton label={searching ? "Buscando..." : "Buscar"} onClick={handleBuscar} disabled={searching || termo.trim().length < 3} icon={<Search size={16} />} />
        </div>
      </Card>
      {searchResults.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Card><DataTable columns={searchCols} data={searchResults} /></Card>
        </div>
      )}
    </div>
  );

  const tabExtrair = (
    <div>
      <Card>
        <FormField label="URL da ata (PNCP ou PDF direto)">
          <TextInput value={extractUrl} onChange={setExtractUrl} placeholder="https://pncp.gov.br/..." />
        </FormField>
        <FormField label="Ou cole o texto da ata aqui">
          <TextArea value={extractTexto} onChange={setExtractTexto} placeholder="Cole o texto completo da ata..." />
        </FormField>
        <ActionButton label={extracting ? "Extraindo..." : "Extrair Dados"} onClick={handleExtrair} disabled={extracting || (!extractUrl && !extractTexto)} icon={extracting ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />} />
      </Card>
      {extractedItems.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Card>
            <h3 style={{ marginBottom: 12 }}>Itens Extraídos ({extractedItems.length})</h3>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                <th style={{ padding: 8, textAlign: "left" }}>Descrição</th>
                <th style={{ padding: 8, textAlign: "left" }}>Vencedor</th>
                <th style={{ padding: 8, textAlign: "right" }}>Valor Unit.</th>
                <th style={{ padding: 8, textAlign: "right" }}>Qtd</th>
              </tr></thead>
              <tbody>{extractedItems.map((item, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: 8 }}>{item.descricao}</td>
                  <td style={{ padding: 8 }}>{item.vencedor}</td>
                  <td style={{ padding: 8, textAlign: "right" }}>{fmt(item.valor_unitario)}</td>
                  <td style={{ padding: 8, textAlign: "right" }}>{item.quantidade}</td>
                </tr>
              ))}</tbody>
            </table>
          </Card>
        </div>
      )}
    </div>
  );

  const tabMinhasAtas = (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 20 }}>
        {[
          { label: "Total", value: atasStats.total, color: "#3b82f6" },
          { label: "Vigentes", value: atasStats.vigentes, color: "#16a34a" },
          { label: "Vencidas", value: atasStats.vencidas, color: "#dc2626" },
        ].map((s, i) => (
          <Card key={i}>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: 12, color: "#6b7280" }}>{s.label}</div>
              <div style={{ fontSize: 28, fontWeight: 700, color: s.color }}>{s.value}</div>
            </div>
          </Card>
        ))}
      </div>
      <Card>
        {loadingAtas ? <Loader2 className="animate-spin" /> : <DataTable columns={atasCols} data={minhasAtas} />}
      </Card>
    </div>
  );

  const tabSaldoARP = (
    <div>
      <Card>
        <FormField label="Selecione uma Ata">
          <SelectInput value={selectedAta} onChange={(v) => { setSelectedAta(v); if (v) fetchSaldos(v); }} options={[
            { value: "", label: "Selecione..." },
            ...minhasAtas.map(a => ({ value: a.id, label: `${a.titulo} — ${a.orgao}` })),
          ]} />
        </FormField>
      </Card>
      {saldos.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Card>
            <h3 style={{ marginBottom: 12 }}>Saldos por Item</h3>
            <DataTable columns={saldoCols} data={saldos} />
          </Card>
        </div>
      )}
      {caronas.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Card>
            <h3 style={{ marginBottom: 12 }}>Solicitações de Carona</h3>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                <th style={{ padding: 8, textAlign: "left" }}>Órgão</th>
                <th style={{ padding: 8, textAlign: "right" }}>Quantidade</th>
                <th style={{ padding: 8, textAlign: "center" }}>Status</th>
                <th style={{ padding: 8, textAlign: "left" }}>Data</th>
              </tr></thead>
              <tbody>{caronas.map((c, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: 8 }}>{c.orgao_solicitante}</td>
                  <td style={{ padding: 8, textAlign: "right" }}>{c.quantidade_solicitada}</td>
                  <td style={{ padding: 8, textAlign: "center" }}>
                    <span style={{ padding: "2px 10px", borderRadius: 12, fontSize: 12, background: c.status === "aprovada" ? "#dcfce7" : c.status === "recusada" ? "#fee2e2" : "#fef3c7", color: c.status === "aprovada" ? "#166534" : c.status === "recusada" ? "#991b1b" : "#92400e" }}>{c.status}</span>
                  </td>
                  <td style={{ padding: 8 }}>{c.data_solicitacao ? new Date(c.data_solicitacao).toLocaleDateString("pt-BR") : "—"}</td>
                </tr>
              ))}</tbody>
            </table>
          </Card>
        </div>
      )}

      {showCaronaModal && selectedSaldo && (
        <Modal title={`Nova Solicitação de Carona — ${selectedSaldo.item_descricao}`} onClose={() => setShowCaronaModal(false)}>
          <FormField label="Órgão Solicitante">
            <TextInput value={caronaOrgao} onChange={setCaronaOrgao} placeholder="Nome do órgão" />
          </FormField>
          <FormField label="CNPJ">
            <TextInput value={caronaCnpj} onChange={setCaronaCnpj} placeholder="00.000.000/0001-00" />
          </FormField>
          <FormField label="Quantidade">
            <TextInput value={caronaQtd} onChange={setCaronaQtd} placeholder="0" />
          </FormField>
          <FormField label="Justificativa">
            <TextArea value={caronaJustificativa} onChange={setCaronaJustificativa} placeholder="Justificativa da adesão..." />
          </FormField>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, marginTop: 16 }}>
            <ActionButton label="Cancelar" onClick={() => setShowCaronaModal(false)} variant="secondary" />
            <ActionButton label="Solicitar" onClick={handleSolicitarCarona} />
          </div>
        </Modal>
      )}
    </div>
  );

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 20, fontSize: 22, fontWeight: 700 }}>Atas de Pregão</h2>
      <TabPanel tabs={[
        { id: "buscar", label: "Buscar" },
        { id: "extrair", label: "Extrair" },
        { id: "minhas", label: "Minhas Atas" },
        { id: "saldo", label: "Saldo ARP" },
      ]}>
        {(activeTab) => {
          if (activeTab === "buscar") return tabBuscar;
          if (activeTab === "extrair") return tabExtrair;
          if (activeTab === "minhas") return tabMinhasAtas;
          return tabSaldoARP;
        }}
      </TabPanel>
    </div>
  );
}
