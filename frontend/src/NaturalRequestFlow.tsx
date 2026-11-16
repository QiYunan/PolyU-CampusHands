import { FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  clarifyAgentDraft, confirmAgentDraft, createAgentDraft, getAgentDraft, itemTypes,
  substitutionPolicyLabels, type AgentDraft, type CampusLocation, type ItemType, type RequestCategory, type SubstitutionPolicy,
} from "./api";
import SystemStatus, { providerLabel } from "./SystemStatus";

function localDateTime(iso: string | null) {
  if (!iso) return "";
  const date = new Date(iso);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export default function NaturalRequestFlow({ locations }: { locations: CampusLocation[] }) {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [reply, setReply] = useState("");
  const [draft, setDraft] = useState<AgentDraft | null>(null);
  const [category, setCategory] = useState<RequestCategory>("borrow");
  const [needSummary, setNeedSummary] = useState("");
  const [itemType, setItemType] = useState<ItemType>("scientific_calculator");
  const [location, setLocation] = useState("");
  const [deadline, setDeadline] = useState("");
  const [urgency, setUrgency] = useState<"normal" | "high">("normal");
  const [preferredBrand, setPreferredBrand] = useState("");
  const [preferredModel, setPreferredModel] = useState("");
  const [substitutionPolicy, setSubstitutionPolicy] = useState<SubstitutionPolicy>("equivalent_ok");
  const policyTouched = useRef(false);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [busyAction, setBusyAction] = useState("");
  const [statusRefreshToken, setStatusRefreshToken] = useState(0);
  const [error, setError] = useState("");

  function updatePreference(kind: "brand" | "model", value: string) {
    if (kind === "brand") setPreferredBrand(value);
    else setPreferredModel(value);
    if (!policyTouched.current) setSubstitutionPolicy(value.trim() || (kind === "brand" ? preferredModel : preferredBrand).trim() ? "ask_before_substitute" : "equivalent_ok");
  }

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
    getAgentDraft(Number(saved)).then((result) => {
      if (active && result.status !== "confirmed") {
        const defaultPolicy = result.preferred_brand || result.preferred_model ? "ask_before_substitute" : "equivalent_ok";
        policyTouched.current = sessionStorage.getItem("agentDraftPolicyTouched") === saved || result.substitution_policy !== defaultPolicy;
        setDraft(result);
      }
    })
      .catch(() => { if (active) sessionStorage.removeItem("agentDraftId"); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!draft) return;
    setCategory(draft.category);
    setNeedSummary(draft.need_summary ?? "");
    setItemType(draft.category === "service" ? "other" : draft.item_type ?? "other");
    setLocation(draft.location ?? "");
    setDeadline(localDateTime(draft.deadline));
    setUrgency(draft.urgency ?? "normal");
    setPreferredBrand(draft.preferred_brand ?? "");
    setPreferredModel(draft.preferred_model ?? "");
    setSubstitutionPolicy(draft.substitution_policy ?? (draft.preferred_brand || draft.preferred_model ? "ask_before_substitute" : "equivalent_ok"));
  }, [draft]);

  async function submit(event: FormEvent) {
    event.preventDefault(); if (!begin("正在解析需求…")) return;
    try {
      const result = await createAgentDraft(text);
      policyTouched.current = false;
      sessionStorage.removeItem("agentDraftPolicyTouched");
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

  async function confirm(event: FormEvent) {
    event.preventDefault();
    if (!draft || !begin("正在创建请求…")) return;
    try {
      const request = await confirmAgentDraft(draft.id, {
        category,
        need_summary: needSummary.trim(),
        item_type: category === "service" ? "other" : itemType,
        location: location.trim() || null,
        deadline: deadline ? new Date(deadline).toISOString() : null,
        urgency,
        preferred_brand: category === "borrow" ? preferredBrand.trim() || null : null,
        preferred_model: category === "borrow" ? preferredModel.trim() || null : null,
        substitution_policy: category === "borrow" ? substitutionPolicy : "equivalent_ok",
      });
      sessionStorage.removeItem("agentDraftId");
      sessionStorage.removeItem("agentDraftPolicyTouched");
      sessionStorage.setItem("lastRequestId", String(request.id));
      navigate(`/requests/${request.id}`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "确认失败，请重试。"); }
    finally { end(); }
  }

  return <section className="natural-flow">
    <SystemStatus refreshToken={statusRefreshToken} />
    <form className="card" onSubmit={(event) => void submit(event)}>
      <h2>用自然语言描述需求</h2>
      <label htmlFor="natural-input">描述你的需求</label>
      <textarea id="natural-input" value={text} onChange={(event) => setText(event.target.value)} maxLength={1000} rows={3} placeholder="例如：30分钟后在Z栋借Casio计算器；或20分钟后在Z栋有偿搬运实验器材" required />
      <button type="submit" disabled={busy}>{busyAction === "正在解析需求…" ? busyAction : "解析需求"}</button>
    </form>
    {error && <p role="alert" className="error card">{error}</p>}
    {draft && <section className="card" aria-label="解析结果">
      <h2>解析结果</h2>
      <p>状态：{draft.status === "ready" ? "等待你确认" : "待补充信息"}；来源：{providerLabel(draft.provider)}{draft.fallback_active ? "（本地备用模型）" : ""}</p>
      <p>需求类型：{draft.category === "borrow" ? "借用物品" : "寻求服务"}；需求摘要：{draft.need_summary ?? "待补充"}</p>
      {draft.matching_issue === "unknown_location" && <p className="matching-note" role="status">交接地点尚未收录。请在下方更正地点，或提供新的地点描述。</p>}
      {draft.public_question && <p role="status">{draft.public_question}</p>}
      {draft.status === "collecting_details" && <form onSubmit={(event) => void clarify(event)}>
        <label htmlFor="clarification">补充缺失信息</label>
        <input id="clarification" value={reply} onChange={(event) => setReply(event.target.value)} required />
        <button type="submit" disabled={busy}>{busyAction === "正在处理补充信息…" ? busyAction : "提交补充"}</button>
      </form>}
      <form onSubmit={(event) => void confirm(event)} className="edit-fields">
        <label htmlFor="parsed-category">需求类型</label>
        <select id="parsed-category" value={category} onChange={(event) => {
          const next = event.target.value as RequestCategory;
          setCategory(next);
          if (next === "service") setItemType("other");
        }}><option value="borrow">借用物品</option><option value="service">寻求服务</option></select>
        <label htmlFor="parsed-summary">需求摘要</label>
        <input id="parsed-summary" value={needSummary} onChange={(event) => setNeedSummary(event.target.value)} maxLength={200} required />
        {category === "borrow" && <>
          <label htmlFor="parsed-item">物品</label>
          <select id="parsed-item" value={itemType} onChange={(event) => setItemType(event.target.value as ItemType)}>{Object.entries(itemTypes).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
        </>}
        <label htmlFor="parsed-location">交接地点</label>
        <input id="parsed-location" list="draft-locations" value={location} onChange={(event) => setLocation(event.target.value)} maxLength={80} required />
        <datalist id="draft-locations">{locations.map((place) => <option key={place.code} value={place.code} label={`${place.label_zh} · ${place.label_en}`} />)}</datalist>
        <label htmlFor="parsed-deadline">最晚需要时间</label>
        <input id="parsed-deadline" type="datetime-local" value={deadline} onChange={(event) => setDeadline(event.target.value)} required />
        {category === "borrow" && <>
          <label htmlFor="parsed-brand">优先品牌（可选）</label>
          <input id="parsed-brand" value={preferredBrand} onChange={(event) => updatePreference("brand", event.target.value)} maxLength={80} />
          <label htmlFor="parsed-model">优先型号（可选）</label>
          <input id="parsed-model" value={preferredModel} onChange={(event) => updatePreference("model", event.target.value)} maxLength={80} />
          <label htmlFor="parsed-substitution-policy">替代品规则</label>
          <select id="parsed-substitution-policy" value={substitutionPolicy} onChange={(event) => { policyTouched.current = true; sessionStorage.setItem("agentDraftPolicyTouched", String(draft.id)); setSubstitutionPolicy(event.target.value as SubstitutionPolicy); }}>
            {Object.entries(substitutionPolicyLabels).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
          <p className="subtle">有品牌或型号偏好时，默认先征求你对替代品的同意。</p>
        </>}
        <label htmlFor="parsed-urgency">紧急程度</label>
        <select id="parsed-urgency" value={urgency} onChange={(event) => setUrgency(event.target.value as "normal" | "high")}><option value="normal">普通</option><option value="high">紧急</option></select>
        <button type="submit" disabled={busy || !needSummary.trim() || !location.trim() || !deadline}>{busyAction === "正在创建请求…" ? busyAction : "确认并创建请求"}</button>
      </form>
    </section>}
  </section>;
}
