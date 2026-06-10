import type { ReactNode } from "react";

interface FormFieldProps {
  label: string;
  required?: boolean;
  error?: string;
  hint?: string;
  children: ReactNode;
}

export function FormField({ label, required, error, hint, children }: FormFieldProps) {
  return (
    <div className={`form-field ${error ? "form-field-error" : ""}`}>
      <label className="form-field-label">
        {label}
        {required && <span className="form-field-required">*</span>}
      </label>
      {children}
      {hint && !error && <span className="form-field-hint">{hint}</span>}
      {error && <span className="form-field-error-msg">{error}</span>}
    </div>
  );
}

interface TextInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: "text" | "email" | "password" | "number" | "url";
  disabled?: boolean;
  prefix?: ReactNode;
  suffix?: ReactNode;
}

export function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
  disabled = false,
  prefix,
  suffix,
}: TextInputProps) {
  return (
    <div className="text-input-wrapper">
      {prefix && <span className="text-input-prefix">{prefix}</span>}
      <input
        type={type}
        className="text-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
      />
      {suffix && <span className="text-input-suffix">{suffix}</span>}
    </div>
  );
}

interface SelectInputProps {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
  disabled?: boolean;
}

export function SelectInput({
  value,
  onChange,
  options,
  placeholder,
  disabled = false,
}: SelectInputProps) {
  return (
    <select
      className="select-input"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
    >
      {placeholder && (
        <option value="" disabled>
          {placeholder}
        </option>
      )}
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}

interface TextAreaProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
}

export function TextArea({
  value,
  onChange,
  placeholder,
  rows = 4,
  disabled = false,
}: TextAreaProps) {
  return (
    <textarea
      className="textarea-input"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={rows}
      disabled={disabled}
    />
  );
}

interface CheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}

export function Checkbox({ checked, onChange, label, disabled = false }: CheckboxProps) {
  return (
    <label className="checkbox-wrapper">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
      />
      <span className="checkbox-label">{label}</span>
    </label>
  );
}

interface RadioGroupProps {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  name: string;
  disabled?: boolean;
}

export function RadioGroup({ value, onChange, options, name, disabled = false }: RadioGroupProps) {
  return (
    <div className="radio-group">
      {options.map((opt) => (
        <label key={opt.value} className="radio-wrapper">
          <input
            type="radio"
            name={name}
            value={opt.value}
            checked={value === opt.value}
            onChange={(e) => onChange(e.target.value)}
            disabled={disabled}
          />
          <span className="radio-label">{opt.label}</span>
        </label>
      ))}
    </div>
  );
}
