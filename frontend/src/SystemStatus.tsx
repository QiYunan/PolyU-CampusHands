import { useEffect, useState } from "react";
import { getLLMStatus, type LLMStatus } from "./api";

export function providerLabel(provider: string | null): string {
  if (provider === "mock") return "Mock Recovery Mode（离线模拟）";
  if (provider === "deepseek") return "DeepSeek";
  if (provider === "ollama") return "Ollama";
  return provider ?? "无";
}

function stateLabel(state: string | null): string {
  switch (state) {
    case "available": return "上次调用成功";
    case "unavailable": return "上次调用失败";
    case "unconfigured": return "未配置";
    case "unknown": return "尚未调用，可用性未知";
    default: return "无";
  }
}

export default function SystemStatus({ refreshToken = 0 }: { refreshToken?: number }) {
  const [status, setStatus] = useState<LLMStatus | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    const load = () => getLLMStatus().then((value) => { if (active) { setStatus(value); setError(false); } })
      .catch(() => { if (active) setError(true); });
    void load();
    const timer = window.setInterval(() => { void load(); }, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, [refreshToken]);
  return <section className="system-status card" aria-label="System Status">
    <h2>System Status</h2>
    {error ? <p>模型状态暂不可读取；可重试或使用结构化表单。</p> : status ? <>
      {status.primary === "mock" && <p className="mock-label">Mock Recovery Mode：离线模拟，不代表真实模型结果。</p>}
      <p>主模型：{providerLabel(status.primary)}（{stateLabel(status.primary_status)}）</p>
      {status.fallback && status.fallback !== status.primary &&
        <p>备用：{providerLabel(status.fallback)}（{stateLabel(status.fallback_status)}）</p>}
      {status.active && <p>最近成功使用：{providerLabel(status.active)}{status.fallback_active ? " · 已切换本地备用" : ""}</p>}
    </> : <p>正在读取模型状态…</p>}
  </section>;
}
