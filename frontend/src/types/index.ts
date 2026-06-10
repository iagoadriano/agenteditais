export interface Source {
  source: string;
  doc_type: string;
  page: number;
  article?: string | null;
  // Campos para jurisprudência (quando doc_type === "jurisprudencia")
  tribunal?: string;
  numero_processo?: string;
  classe?: string;
  orgao_julgador?: string;
  data?: string;
}

export interface PageProps {
  onSendToChat?: (message: string, file?: File) => void;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[] | null;
  created_at?: string;
  action_type?: string;
  resultado?: Record<string, unknown>;
}

export interface Session {
  session_id: string;
  /** Alias opcional retornado por alguns endpoints no lugar de session_id */
  id?: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface ChatResponse {
  response: string;
  sources: Source[];
  session_id: string;
}

export interface Edital {
  id?: string;
  numero: string;
  orgao: string;
  orgao_tipo?: string;
  uf?: string;
  cidade?: string;
  objeto: string;
  modalidade?: string;
  categoria?: string;
  valor_referencia?: number;
  data_publicacao?: string;
  data_abertura?: string;
  status?: string;
  fonte: string;
  fonte_tipo?: 'api' | 'scraper';
  url?: string;
  pdf_url?: string;
  pdf_titulo?: string;
  dados_completos?: boolean;
  cnpj_orgao?: string;
  ano_compra?: number;
  seq_compra?: number;
  itens?: EditalItem[];
  total_itens?: number;
}

export interface EditalItem {
  numero?: number;
  descricao: string;
  quantidade?: number;
  unidade?: string;
  valor_unitario?: number;
  valor_total?: number;
}
