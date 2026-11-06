import { useEffect, useState } from "react";
import { getLLMStatus, type LLMStatus } from "./api";

export default function SystemStatus() {
  const [status, setStatus] = useState<LLMStatus | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    const load = () => getLLMStatus().then((value) => { if (active) { setStatus(value); setError(false); } })
      .catch(() => { if (active) setError(true); });
    void load();
    const timer = window.setInterval(() => { void load(); }, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  return <section className="system-status card" aria-label="System Status">
    <h2>System Status</h2>
    {error ? <p>模型状态暂不可读取；可重试或使用结构化表单。</p> : status ? <p>
      主模型：{status.primary}（{status.primary_status}）；备用：{status.fallback ?? "无"}（{status.fallback_status ?? "无"}）
      {status.fallback_active && <strong> · 当前使用本地备用模型</strong>}
    </p> : <p>正在读取模型状态…</p>}
  </section>;
}
