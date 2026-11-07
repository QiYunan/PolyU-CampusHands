import { FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { clarifyAgentDraft, confirmAgentDraft, createAgentDraft, editAgentDraft, getAgentDraft, itemTypes, type AgentDraft, type ItemType } from "./api";
import SystemStatus, { providerLabel } from "./SystemStatus";

function localDateTime(iso: string | null) {
  if (!iso) return "";
  const date = new Date(iso);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export default function NaturalRequestFlow() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [reply, setReply] = useState("");
  const [draft, setDraft] = useState<AgentDraft | null>(null);
  const [itemType, setItemType] = useState<ItemType>("scientific_calculator");
  const [location, setLocation] = useState("");
  const [deadline, setDeadline] = useState("");
  const [urgency, setUrgency] = useState<"normal" | "high">("normal");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [busyAction, setBusyAction] = useState("");
  const [statusRefreshToken, setStatusRefreshToken] = useState(0);
  const [error, setError] = useState("");

  function begin(action: string): boolean {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(true);
    setBusyAction(action);
    setError("");
    return true;
  }

  function end(refreshProvider = false) {
    busyRef.current = false;
    setBusy(false);
    setBusyAction("");
    if (refreshProvider) setStatusRefreshToken((value) => value + 1);
  }

  useEffect(() => {
    const saved = sessionStorage.getItem("agentDraftId");
    if (!saved) return;
    let active = true;
    getAgentDraft(Number(saved)).then((result) => { if (active && result.status !== "confirmed") setDraft(result); })
      .catch(() => { if (active) sessionStorage.removeItem("agentDraftId"); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!draft) return;
    setItemType(draft.item_type ?? "scientific_calculator");
    setLocation(draft.location ?? "");
    setDeadline(localDateTime(draft.deadline));
    setUrgency(draft.urgency ?? "normal");
  }, [draft]);

  async function submit(event: FormEvent) {
    event.preventDefault(); if (!begin("正在解析需求…")) return;
    try {
      const result = await createAgentDraft(text);
      sessionStorage.setItem("agentDraftId", String(result.id));
      setDraft(result);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "解析失败，请重试。"); }
    finally { end(true); }
  }

  async function clarify(event: FormEvent) {
    event.preventDefault(); if (!draft || !begin("正在处理补充信息…")) return;
    try { setDraft(await clarifyAgentDraft(draft.id, reply)); setReply(""); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "澄清失败，请重试。"); }
    finally { end(true); }
  }

  async function saveEdits(event: FormEvent) {
    event.preventDefault(); if (!draft || !begin("正在保存修改…")) return;
    try { setDraft(await editAgentDraft(draft.id, { item_type: itemType, location, deadline: deadline ? new Date(deadline).toISOString() : null, urgency })); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "修改失败，请重试。"); }
    finally { end(); }
  }

  async function confirm() {
    if (!draft || draft.status !== "ready" || !begin("正在确认草稿…")) return;
    try {
      const request = await confirmAgentDraft(draft.id);
      sessionStorage.removeItem("agentDraftId");
      sessionStorage.setItem("lastRequestId", String(request.id));
      navigate(`/requests/${request.id}`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "确认失败，请重试。"); }
    finally { end(); }
  }

  return <section className="natural-flow">
    <SystemStatus refreshToken={statusRefreshToken} />
    <form className="card" onSubmit={(event) => void submit(event)}>
      <h2>用自然语言描述需求</h2>
      <label htmlFor="natural-input">借物请求</label>
      <textarea id="natural-input" value={text} onChange={(event) => setText(event.target.value)} maxLength={1000} rows={3} placeholder="我20分钟后在VA考试，想借一部科学计算器" required />
      <button type="submit" disabled={busy}>{busyAction === "正在解析需求…" ? busyAction : "解析需求"}</button>
    </form>
    {error && <p role="alert" className="error card">{error}</p>}
    {draft && <section className="card" aria-label="解析结果">
      <h2>解析结果</h2>
      <p>状态：{draft.status === "ready" ? "等待你确认" : "待补充信息"}；来源：{providerLabel(draft.provider)}{draft.fallback_active ? "（本地备用模型）" : ""}</p>
      {draft.public_question && <p role="status">{draft.public_question}</p>}
      {draft.status === "collecting_details" && <form onSubmit={(event) => void clarify(event)}>
        <label htmlFor="clarification">补充缺失信息</label>
        <input id="clarification" value={reply} onChange={(event) => setReply(event.target.value)} required />
        <button type="submit" disabled={busy}>{busyAction === "正在处理补充信息…" ? busyAction : "提交补充"}</button>
      </form>}
      <form onSubmit={(event) => void saveEdits(event)} className="edit-fields">
        <label htmlFor="parsed-item">物品</label>
        <select id="parsed-item" value={itemType} onChange={(event) => setItemType(event.target.value as ItemType)}>{Object.entries(itemTypes).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
        <label htmlFor="parsed-location">交接地点</label>
        <input id="parsed-location" value={location} onChange={(event) => setLocation(event.target.value)} maxLength={80} />
        <label htmlFor="parsed-deadline">最晚需要时间</label>
        <input id="parsed-deadline" type="datetime-local" value={deadline} onChange={(event) => setDeadline(event.target.value)} />
        <label htmlFor="parsed-urgency">紧急程度</label>
        <select id="parsed-urgency" value={urgency} onChange={(event) => setUrgency(event.target.value as "normal" | "high")}><option value="normal">普通</option><option value="high">紧急</option></select>
        <button type="submit" className="secondary" disabled={busy}>{busyAction === "正在保存修改…" ? busyAction : "保存修改"}</button>
      </form>
      <button type="button" onClick={() => void confirm()} disabled={busy || draft.status !== "ready"}>{busyAction === "正在确认草稿…" ? busyAction : "确认并保存草稿"}</button>
    </section>}
  </section>;
}
