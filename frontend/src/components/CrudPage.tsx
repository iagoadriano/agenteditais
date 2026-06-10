import { useState, useEffect, useCallback, useRef, Fragment } from "react";
import { Search, Plus, Save, Trash2, X, Database, ChevronLeft, Eye, EyeOff, Building, Pencil } from "lucide-react";
import { crudList, crudGet, crudCreate, crudUpdate, crudDelete, getCrudSchema } from "../api/crud";
import type { CrudColumnSchema } from "../api/crud";
import { useAuth } from "../contexts/AuthContext";

// ─── Field configuration for each CRUD table ──────────────────────────────────

export interface FieldConfig {
  name: string;
  label: string;
  type: "text" | "number" | "email" | "date" | "datetime" | "textarea" | "select" | "boolean" | "json" | "decimal" | "readonly" | "password" | "fk";
  required?: boolean;
  options?: { value: string; label: string }[];
  placeholder?: string;
  width?: "full" | "half" | "third" | "quarter";
  hidden?: boolean;
  fkTable?: string;
  fkLabel?: string;
  confirmField?: string; // name of the confirmation field (for password)
  renderCustom?: (value: unknown, onChange: (val: unknown) => void) => React.ReactNode;
}

export interface CrudPageConfig {
  table: string;
  title: string;
  icon?: React.ReactNode;
  fields: FieldConfig[];
  searchPlaceholder?: string;
  parentFk?: string;
  parentTable?: string;
  parentLabelField?: string;
  parentLabelFn?: (item: Record<string, unknown>) => string;
  /** Optional grandparent filter — adds a second dropdown that filters the parent dropdown */
  grandparentTable?: string;
  grandparentFk?: string;        // FK column on the parent table pointing to grandparent
  grandparentLabelField?: string;
  /** Custom component that replaces the default form when creating a new record.
   *  Receives onSaved (call after successful save to reload list) and onCancel. */
  renderCreateForm?: (props: { onSaved: () => void; onCancel: () => void }) => React.ReactNode;
  /** Custom component that replaces the default form when editing.
   *  Receives the item data, onSaved and onCancel. */
  renderEditForm?: (props: { item: Record<string, unknown>; onSaved: () => void; onCancel: () => void }) => React.ReactNode;
}

interface CrudPageProps {
  config: CrudPageConfig;
}

// ─── Format field labels from column names ─────────────────────────────────────

function formatLabel(name: string): string {
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bId\b/g, "ID")
    .replace(/\bUf\b/g, "UF")
    .replace(/\bCnpj\b/g, "CNPJ")
    .replace(/\bCep\b/g, "CEP")
    .replace(/\bCpf\b/g, "CPF")
    .replace(/\bNcm\b/g, "NCM")
    .replace(/\bUrl\b/g, "URL");
}

// ─── Auto-generate field config from schema ────────────────────────────────────

export function generateFieldsFromSchema(columns: CrudColumnSchema[]): FieldConfig[] {
  return columns
    .filter((col) => !["id", "user_id", "created_at", "updated_at"].includes(col.name))
    .map((col) => {
      const field: FieldConfig = {
        name: col.name,
        label: formatLabel(col.name),
        type: "text",
        required: col.required,
        width: "half",
      };

      if (col.options && col.options.length > 0) {
        field.type = "select";
        field.options = col.options.map((o) => ({ value: o, label: formatLabel(o) }));
      } else if (col.type === "BOOLEAN") {
        field.type = "boolean";
        field.width = "half";
      } else if (col.type === "DECIMAL" || col.type === "NUMERIC") {
        field.type = "decimal";
      } else if (col.type === "INTEGER" || col.type === "INT") {
        field.type = "number";
      } else if (col.type === "DATE") {
        field.type = "date";
      } else if (col.type === "DATETIME") {
        field.type = "datetime";
      } else if (col.type === "TEXT" || col.type === "LONGTEXT") {
        field.type = "textarea";
        field.width = "full";
      } else if (col.type === "JSON") {
        field.type = "json";
        field.width = "full";
      }

      // FK fields
      if (col.fk) {
        field.type = "text";
        field.placeholder = `ID de ${col.fk.split(".")[0]}`;
      }

      return field;
    });
}

// ─── Component ─────────────────────────────────────────────────────────────────

export function CrudPage({ config }: CrudPageProps) {
  const { table, title, icon, fields, searchPlaceholder, parentFk, parentTable, parentLabelField, parentLabelFn, grandparentTable, grandparentFk, grandparentLabelField, renderCreateForm, renderEditForm } = config;
  const { empresa } = useAuth();

  const [items, setItems] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [formData, setFormData] = useState<Record<string, unknown>>({});
  const [isNew, setIsNew] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [passwordVisible, setPasswordVisible] = useState<Record<string, boolean>>({});
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [isEmpresaScopedFromSchema, setIsEmpresaScopedFromSchema] = useState(false);

  // Load empresa_scoped flag from schema
  useEffect(() => {
    getCrudSchema().then((schema) => {
      const tableSchema = schema[table];
      if (tableSchema?.empresa_scoped) {
        setIsEmpresaScopedFromSchema(true);
      }
    }).catch(() => {});
  }, [table]);

  // ─── Parent selector state (for child tables) ────────────────────────────
  const isChildTable = Boolean(parentFk && parentTable);
  const [parentItems, setParentItems] = useState<Record<string, unknown>[]>([]);
  const [selectedParentId, setSelectedParentId] = useState<string | null>(null);
  const [parentLoading, setParentLoading] = useState(false);

  // ─── Grandparent selector state (optional, e.g. Área → Classe → Subclasse)
  const hasGrandparent = Boolean(grandparentTable && grandparentFk);
  const [grandparentItems, setGrandparentItems] = useState<Record<string, unknown>[]>([]);
  const [selectedGrandparentId, setSelectedGrandparentId] = useState<string | null>(null);
  const [grandparentLoading, setGrandparentLoading] = useState(false);

  // FK field options: { [fieldName]: { value, label }[] }
  const [fkOptions, setFkOptions] = useState<Record<string, { value: string; label: string }[]>>({});

  const getParentLabel = useCallback((item: Record<string, unknown>): string => {
    if (parentLabelFn) return parentLabelFn(item);
    if (parentLabelField) {
      const val = item[parentLabelField];
      return val ? String(val) : String(item.id).slice(0, 8);
    }
    // Auto-detect: try nome, razao_social, numero, titulo, termo, orgao, then first string
    for (const key of ["nome", "razao_social", "numero", "titulo", "termo", "orgao", "numero_contrato"]) {
      if (item[key]) return String(item[key]);
    }
    return String(item.id).slice(0, 8);
  }, [parentLabelField, parentLabelFn]);

  // ─── Load parent items ─────────────────────────────────────────────────────

  const loadParentItems = useCallback(async (query?: string) => {
    if (!parentTable) return;
    setParentLoading(true);
    try {
      const result = await crudList(parentTable, { q: query || undefined, limit: 100 });
      setParentItems(result.items);
    } catch {
      // Silently fail — parent list not critical
    } finally {
      setParentLoading(false);
    }
  }, [parentTable]);

  useEffect(() => {
    if (isChildTable && !hasGrandparent) {
      loadParentItems();
    }
  }, [isChildTable, hasGrandparent, loadParentItems]);

  // ─── Load grandparent items ─────────────────────────────────────────────────
  useEffect(() => {
    if (!hasGrandparent || !grandparentTable) return;
    setGrandparentLoading(true);
    crudList(grandparentTable, { limit: 200 })
      .then((res) => setGrandparentItems(res.items))
      .catch(() => {})
      .finally(() => setGrandparentLoading(false));
  }, [hasGrandparent, grandparentTable]);

  // When grandparent changes, reload parent items filtered by grandparent
  useEffect(() => {
    if (!hasGrandparent || !parentTable || !grandparentFk) return;
    if (!selectedGrandparentId) {
      setParentItems([]);
      setSelectedParentId(null);
      return;
    }
    setParentLoading(true);
    crudList(parentTable, { parent_id: selectedGrandparentId, limit: 200 })
      .then((res) => {
        setParentItems(res.items);
        setSelectedParentId(null);
        setSelectedId(null);
        setIsNew(false);
        setFormData({});
      })
      .catch(() => {})
      .finally(() => setParentLoading(false));
  }, [hasGrandparent, parentTable, grandparentFk, selectedGrandparentId]);

  // Load FK options for fk-type fields
  useEffect(() => {
    const fkFields = fields.filter(f => f.type === "fk" && f.fkTable && f.fkLabel);
    if (fkFields.length === 0) return;
    (async () => {
      const opts: Record<string, { value: string; label: string }[]> = {};
      for (const f of fkFields) {
        try {
          const res = await crudList(f.fkTable!, { limit: 200 });
          opts[f.name] = res.items.map(item => ({
            value: String(item.id),
            label: String(item[f.fkLabel!] || item.nome || item.id),
          }));
        } catch { /* silent */ }
      }
      setFkOptions(opts);
    })();
  }, [fields]);

  // ─── Load items ────────────────────────────────────────────────────────────

  const loadItems = useCallback(async (query?: string) => {
    setLoading(true);
    setError(null);
    try {
      const params: { q?: string; parent_id?: string; limit?: number } = { q: query || undefined, limit: 200 };
      if (isChildTable && selectedParentId) {
        params.parent_id = selectedParentId;
      }
      const result = await crudList(table, params);
      setItems(result.items);
      setTotal(result.total);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [table, isChildTable, selectedParentId]);

  useEffect(() => {
    if (isChildTable && !selectedParentId) {
      // Don't load child items until a parent is selected
      setItems([]);
      setTotal(0);
      return;
    }
    loadItems();
  }, [loadItems, isChildTable, selectedParentId]);

  // ─── Debounced search ──────────────────────────────────────────────────────

  const handleSearchChange = (value: string) => {
    setSearchTerm(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      loadItems(value);
    }, 300);
  };

  // ─── Search Enter → load record ───────────────────────────────────────────

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && items.length > 0) {
      e.preventDefault();
      const firstItem = items[0];
      handleSelectItem(firstItem);
    }
  };

  // ─── Select item for editing ──────────────────────────────────────────────

  const handleSelectItem = async (item: Record<string, unknown>) => {
    const id = String(item.id);
    setSelectedId(id);
    setIsNew(false);
    setError(null);
    setSuccessMsg(null);
    try {
      const full = await crudGet(table, id);
      // Initialize confirm field for password
      fields.forEach((f) => {
        if (f.type === "password") {
          if (!full[f.name]) full[f.name] = "";
          if (f.confirmField) full[f.confirmField] = full[f.name] || "";
        }
      });
      setFormData(full);
    } catch (err) {
      fields.forEach((f) => {
        if (f.type === "password") {
          if (!item[f.name]) item[f.name] = "";
          if (f.confirmField) item[f.confirmField] = item[f.name] || "";
        }
      });
      setFormData(item);
    }
  };

  // ─── New record ───────────────────────────────────────────────────────────

  const handleNew = () => {
    setSelectedId(null);
    setIsNew(true);
    setError(null);
    setSuccessMsg(null);
    const emptyForm: Record<string, unknown> = {};
    fields.forEach((f) => {
      if (f.type === "boolean") {
        // Campo "ativo" (e flags semelhantes de visibilidade) deve nascer TRUE.
        // Antes, todos os booleans nasciam false, fazendo CRUD criar empresa
        // com ativo=0 (sumia da listagem em telas que filtram por ativo=1).
        const nomeLower = f.name.toLowerCase();
        if (nomeLower === "ativo" || nomeLower === "active" || nomeLower === "is_active") {
          emptyForm[f.name] = true;
        } else {
          emptyForm[f.name] = false;
        }
      } else {
        emptyForm[f.name] = "";
      }
    });
    // Auto-fill parent FK when creating child record
    if (parentFk && selectedParentId) {
      emptyForm[parentFk] = selectedParentId;
    }
    setFormData(emptyForm);
  };

  // ─── Save ─────────────────────────────────────────────────────────────────

  const handleSave = async () => {
    // Validate password confirmation
    const pwFields = fields.filter((f) => f.type === "password");
    for (const pf of pwFields) {
      const pw = String(formData[pf.name] ?? "");
      const confirmName = pf.confirmField || `${pf.name}_confirm`;
      const confirm = String(formData[confirmName] ?? "");
      if (pw || confirm) {
        if (pw !== confirm) {
          setPasswordError("As senhas não coincidem");
          return;
        }
        if (pw.length < 4) {
          setPasswordError("A senha deve ter pelo menos 4 caracteres");
          return;
        }
      }
      if (isNew && pf.required && !pw) {
        setPasswordError("A senha é obrigatória para novos registros");
        return;
      }
    }
    setPasswordError(null);

    // Strip confirm fields before sending
    const dataToSend = { ...formData };
    for (const pf of pwFields) {
      const confirmName = pf.confirmField || `${pf.name}_confirm`;
      delete dataToSend[confirmName];
      // Don't send empty password on update (means "keep current")
      if (!isNew && !dataToSend[pf.name]) {
        delete dataToSend[pf.name];
      }
    }

    setSaving(true);
    setError(null);
    setSuccessMsg(null);
    try {
      if (isNew) {
        const created = await crudCreate(table, dataToSend);
        setSelectedId(String(created.id));
        setFormData(created);
        setIsNew(false);
        setSuccessMsg("Registro criado com sucesso!");
      } else if (selectedId) {
        const updated = await crudUpdate(table, selectedId, dataToSend);
        setFormData(updated);
        setSuccessMsg("Registro atualizado com sucesso!");
      }
      loadItems(searchTerm);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
      setTimeout(() => setSuccessMsg(null), 3000);
    }
  };

  // ─── Delete ───────────────────────────────────────────────────────────────

  const handleDelete = async () => {
    if (!selectedId) return;
    if (!confirm("Tem certeza que deseja excluir este registro?")) return;

    setError(null);
    try {
      await crudDelete(table, selectedId);
      setSelectedId(null);
      setIsNew(false);
      setFormData({});
      setSuccessMsg("Registro excluído com sucesso!");
      loadItems(searchTerm);
    } catch (err) {
      setError((err as Error).message);
    }
    setTimeout(() => setSuccessMsg(null), 3000);
  };

  // ─── Cancel / Back to list ────────────────────────────────────────────────

  const handleCancel = () => {
    setSelectedId(null);
    setIsNew(false);
    setFormData({});
    setError(null);
    setSuccessMsg(null);
  };

  // ─── Update form field ────────────────────────────────────────────────────

  const updateField = (name: string, value: unknown) => {
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  // ─── Render field input ───────────────────────────────────────────────────

  const renderField = (field: FieldConfig, inputId?: string) => {
    if (field.hidden) return null;
    const value = formData[field.name] ?? "";

    if (field.renderCustom) {
      return field.renderCustom(value, (val) => updateField(field.name, val));
    }

    switch (field.type) {
      case "select":
        return (
          <select
            id={inputId}
            className="select-input"
            value={String(value)}
            onChange={(e) => updateField(field.name, e.target.value)}
          >
            <option value="">Selecione...</option>
            {field.options?.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        );
      case "boolean":
        return (
          <label className="checkbox-wrapper">
            <input
              id={inputId}
              type="checkbox"
              checked={Boolean(value)}
              onChange={(e) => updateField(field.name, e.target.checked)}
            />
            <span className="checkbox-label">{value ? "Sim" : "Não"}</span>
          </label>
        );
      case "textarea":
        return (
          <textarea
            id={inputId}
            className="textarea-input"
            value={String(value)}
            onChange={(e) => updateField(field.name, e.target.value)}
            placeholder={field.placeholder}
            rows={4}
          />
        );
      case "json":
        return (
          <textarea
            id={inputId}
            className="textarea-input"
            value={typeof value === "object" ? JSON.stringify(value, null, 2) : String(value)}
            onChange={(e) => {
              try {
                updateField(field.name, JSON.parse(e.target.value));
              } catch {
                updateField(field.name, e.target.value);
              }
            }}
            placeholder="JSON..."
            rows={4}
          />
        );
      case "date":
        return (
          <input
            id={inputId}
            type="date"
            className="text-input"
            value={String(value).slice(0, 10)}
            onChange={(e) => updateField(field.name, e.target.value)}
          />
        );
      case "datetime":
        return (
          <input
            id={inputId}
            type="datetime-local"
            className="text-input"
            value={String(value).slice(0, 16)}
            onChange={(e) => updateField(field.name, e.target.value)}
          />
        );
      case "readonly":
        return (
          <input
            id={inputId}
            type="text"
            className="text-input"
            value={String(value)}
            disabled
          />
        );
      case "password": {
        const isVisible = passwordVisible[field.name] || false;
        const confirmName = field.confirmField || `${field.name}_confirm`;
        const confirmValue = formData[confirmName] ?? "";
        const hasExisting = Boolean(formData["has_password"]);
        return (
          <div className="password-field-group">
            <div className="password-input-wrapper">
              <input
                id={inputId}
                type={isVisible ? "text" : "password"}
                className="text-input"
                value={String(value)}
                onChange={(e) => {
                  updateField(field.name, e.target.value);
                  setPasswordError(null);
                }}
                placeholder={hasExisting && !isNew ? "Deixe em branco para manter a atual" : field.placeholder || "Digite a senha"}
                autoComplete="new-password"
              />
              <button
                type="button"
                className="password-toggle-btn"
                onClick={() => setPasswordVisible((prev) => ({ ...prev, [field.name]: !prev[field.name] }))}
                title={isVisible ? "Ocultar senha" : "Mostrar senha"}
              >
                {isVisible ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            <div className="password-input-wrapper" style={{ marginTop: "8px" }}>
              <input
                type={isVisible ? "text" : "password"}
                className="text-input"
                value={String(confirmValue)}
                onChange={(e) => {
                  updateField(confirmName, e.target.value);
                  setPasswordError(null);
                }}
                placeholder="Confirme a senha"
                autoComplete="new-password"
              />
            </div>
            {passwordError && (
              <div className="password-error">{passwordError}</div>
            )}
            {hasExisting && !isNew && !String(value) && (
              <div className="password-hint">Senha ja cadastrada. Preencha apenas para alterar.</div>
            )}
          </div>
        );
      }
      case "fk": {
        const options = fkOptions[field.name] || [];
        return (
          <select
            id={inputId}
            className="select-input"
            value={String(value || "")}
            onChange={(e) => updateField(field.name, e.target.value || null)}
          >
            <option value="">Selecione...</option>
            {options.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        );
      }
      default:
        return (
          <input
            id={inputId}
            type={field.type === "decimal" ? "number" : field.type}
            className="text-input"
            value={String(value)}
            onChange={(e) => updateField(field.name, e.target.value)}
            placeholder={field.placeholder}
            step={field.type === "decimal" ? "0.01" : undefined}
          />
        );
    }
  };

  // ─── Display value in table list ──────────────────────────────────────────

  const getDisplayValue = (item: Record<string, unknown>, field: FieldConfig): string => {
    if (field.type === "password") {
      return item[field.name] ? String(item[field.name]) : (item["has_password"] ? "***" : "-");
    }
    const val = item[field.name];
    if (val === null || val === undefined) return "-";
    if (field.type === "boolean") return val ? "Sim" : "Não";
    if (field.type === "json") return typeof val === "object" ? JSON.stringify(val) : String(val);
    if (field.type === "select" && field.options) {
      const opt = field.options.find((o) => o.value === String(val));
      return opt ? opt.label : String(val);
    }
    if (field.type === "fk" && fkOptions[field.name]) {
      const opt = fkOptions[field.name].find((o) => o.value === String(val));
      return opt ? opt.label : String(val).slice(0, 8);
    }
    const s = String(val);
    return s.length > 50 ? s.slice(0, 50) + "..." : s;
  };

  // ─── Visible fields for table columns (first 6 non-hidden, skip parent FK) ─

  const tableFields = fields
    .filter((f) => !f.hidden && f.type !== "json" && f.type !== "textarea" && !(isChildTable && f.name === parentFk))
    .slice(0, 6);
  const formFields = fields.filter((f) => !(isChildTable && f.name === parentFk));
  const showForm = isNew || selectedId !== null;

  // Show empresa field for empresa_scoped tables (from schema)
  const hasEmpresaField = fields.some((f) => f.name === "empresa_id");
  const showEmpresaField = !hasEmpresaField && empresa && isEmpresaScopedFromSchema;

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-left">
          {icon || <Database size={24} />}
          <div>
            <h1>{title}</h1>
            <p>
              {isChildTable && !selectedParentId
                ? "Use os filtros abaixo para listar registros"
                : `${total} registro${total !== 1 ? "s" : ""}`}
            </p>
          </div>
        </div>
      </div>

      <div className="page-content">
        {/* Parent selector for child tables — dropdown(s) */}
        {isChildTable && (
          <div className="card crud-parent-selector" style={{ marginBottom: "1rem" }}>
            <div className="card-content" style={{ padding: "0.75rem 1rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
                {/* Grandparent dropdown (optional, e.g. Área) */}
                {hasGrandparent && (
                  <>
                    <label className="form-field-label" style={{ margin: 0, whiteSpace: "nowrap", fontWeight: 600 }}>
                      {grandparentLabelField ? grandparentLabelField.charAt(0).toUpperCase() + grandparentLabelField.slice(1) : "Filtrar"}:
                    </label>
                    {grandparentLoading ? (
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}><div className="loading-spinner small" /> Carregando...</div>
                    ) : (
                      <select
                        className="form-input"
                        style={{ flex: 1, maxWidth: "300px" }}
                        value={selectedGrandparentId || ""}
                        onChange={(e) => { setSelectedGrandparentId(e.target.value || null); }}
                      >
                        <option value="">— Selecione —</option>
                        {grandparentItems.map((item) => (
                          <option key={String(item.id)} value={String(item.id)}>
                            {String(item.nome || item.razao_social || item.titulo || item.id)}
                          </option>
                        ))}
                      </select>
                    )}
                  </>
                )}
                <label className="form-field-label" style={{ margin: 0, whiteSpace: "nowrap", fontWeight: 600 }}>
                  {hasGrandparent ? (parentFk ? parentFk.replace(/_id$/, "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : "Filtrar") : "Filtrar por"}:
                </label>
                {parentLoading ? (
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}><div className="loading-spinner small" /> Carregando...</div>
                ) : (
                  <select
                    className="form-input"
                    style={{ flex: 1, maxWidth: hasGrandparent ? "300px" : "400px" }}
                    value={selectedParentId || ""}
                    onChange={(e) => { const v = e.target.value; setSelectedParentId(v || null); setSelectedId(null); setIsNew(false); setFormData({}); }}
                    disabled={hasGrandparent && !selectedGrandparentId}
                  >
                    <option value="">— Selecione —</option>
                    {parentItems.map((item) => (
                      <option key={String(item.id)} value={String(item.id)}>
                        {getParentLabel(item)}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Search bar + New button */}
        <div className="crud-toolbar" style={isChildTable && !selectedParentId ? { opacity: 0.5, pointerEvents: "none" } : {}}>
          <div className="crud-search-box">
            <Search size={16} />
            <input
              ref={searchRef}
              type="text"
              placeholder={searchPlaceholder || `Buscar ${title.toLowerCase()}...`}
              value={searchTerm}
              onChange={(e) => handleSearchChange(e.target.value)}
              onKeyDown={handleSearchKeyDown}
            />
            {searchTerm && (
              <button className="crud-search-clear" onClick={() => { setSearchTerm(""); loadItems(); }}>
                <X size={14} />
              </button>
            )}
          </div>
          <button className="action-button action-button-primary" onClick={handleNew} data-testid="crud-btn-novo">
            <Plus size={16} />
            <span>Novo</span>
          </button>
        </div>

        {/* Messages */}
        {error && <div className="crud-message crud-message-error">{error}</div>}
        {successMsg && <div className="crud-message crud-message-success">{successMsg}</div>}

        {/* Table list — logo abaixo da busca */}
        <div className="card">
          <div className="card-content" style={{ padding: 0 }}>
            <div className="data-table-wrapper">
              <table className="data-table">
                <thead>
                  <tr>
                    {tableFields.map((f) => (
                      <th key={f.name}>{f.label}</th>
                    ))}
                    <th style={{ width: 80, textAlign: "center" }}>Ações</th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr>
                      <td colSpan={tableFields.length + 1} className="data-table-loading">
                        <div className="loading-spinner small" />
                        Carregando...
                      </td>
                    </tr>
                  ) : items.length === 0 ? (
                    <tr>
                      <td colSpan={tableFields.length + 1} className="data-table-empty">
                        Nenhum registro encontrado
                      </td>
                    </tr>
                  ) : (
                    items.map((item) => (
                      <tr
                        key={String(item.id)}
                        className={`clickable ${selectedId === String(item.id) ? "selected" : ""}`}
                        onClick={() => handleSelectItem(item)}
                        data-testid={`crud-row-${item.id}`}
                      >
                        {tableFields.map((f) => (
                          <td key={f.name}>{getDisplayValue(item, f)}</td>
                        ))}
                        <td style={{ textAlign: "center" }} onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            className="action-button action-button-icon"
                            onClick={() => handleSelectItem(item)}
                            title="Editar"
                            aria-label={`Editar ${item.nome || item.id}`}
                            data-testid={`crud-btn-editar-${item.id}`}
                            style={{ padding: "4px 8px" }}
                          >
                            <Pencil size={14} />
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Custom create form (replaces default form on new) */}
        {isNew && renderCreateForm && (
          renderCreateForm({
            onSaved: () => { setIsNew(false); loadItems(); },
            onCancel: () => { setIsNew(false); setError(null); },
          })
        )}

        {/* Custom edit form (replaces default form on edit) */}
        {!isNew && selectedId && renderEditForm && Boolean(formData.id) && (
          <Fragment key={String(formData.id)}>
            {renderEditForm({
              item: formData,
              onSaved: () => { setSelectedId(null); loadItems(); },
              onCancel: () => { setSelectedId(null); setError(null); },
            })}
          </Fragment>
        )}

        {/* Form area (default — used when no custom form applies) */}
        {showForm && !(isNew && renderCreateForm) && !(!isNew && selectedId && renderEditForm) && (
          <div className="card">
            <div className="card-header">
              <div className="card-header-left">
                <button className="crud-back-btn" onClick={handleCancel} title="Voltar à lista">
                  <ChevronLeft size={18} />
                </button>
                <h3 className="card-title">{isNew ? `Novo ${title}` : `Editar ${title}`}</h3>
              </div>
              <div className="card-header-right">
                <button
                  className="action-button action-button-primary"
                  onClick={handleSave}
                  disabled={saving}
                >
                  {saving ? <span className="loading-spinner small" /> : <Save size={16} />}
                  <span>Salvar</span>
                </button>
                {selectedId && !isNew && (
                  <button className="action-button action-button-danger" onClick={handleDelete}>
                    <Trash2 size={16} />
                    <span>Excluir</span>
                  </button>
                )}
                <button className="action-button action-button-secondary" onClick={handleCancel}>
                  <X size={16} />
                  <span>Cancelar</span>
                </button>
              </div>
            </div>
            <div className="card-content">
              <div className="form-grid form-grid-2">
                {showEmpresaField && empresa && (
                  <div className="form-field">
                    <label className="form-field-label">
                      <Building size={14} style={{ display: "inline", marginRight: 4, verticalAlign: "middle" }} />
                      Empresa
                    </label>
                    <input
                      type="text"
                      className="text-input"
                      value={empresa.razao_social || empresa.nome_fantasia || ""}
                      readOnly
                      style={{ backgroundColor: "var(--bg-tertiary)", cursor: "default" }}
                    />
                  </div>
                )}
                {formFields.filter((f) => !f.hidden).map((field) => {
                  const inputId = `crud-field-${field.name}`;
                  return (
                  <div
                    key={field.name}
                    className={`form-field ${field.width === "full" ? "form-field-full" : ""}`}
                    data-testid={`crud-field-${field.name}`}
                  >
                    <label className="form-field-label" htmlFor={inputId}>
                      {field.label}
                      {field.required && <span className="form-field-required">*</span>}
                    </label>
                    {renderField(field, inputId)}
                  </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
