import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import {
  actOnOffer, actOnRequest, agentObserve, agentSearch, createHelpRequest, getHelpRequest, getHelperOffers,
  itemTypes, type AgentRun, type HelpOffer, type HelpRequest, type ItemType, type OfferAction,
  type RequestAction,
} from "./api";
import NaturalRequestFlow from "./NaturalRequestFlow";
import { useRealtimeSnapshot } from "./realtime";
import SystemStatus, { providerLabel } from "./SystemStatus";

const people: Record<number, string> = { 1: "Alice · Requester", 2: "Bob · Helper", 3: "Carol · Helper", 4: "David · Helper" };
const statusLabels: Record<HelpRequest["status"], string> = {
  draft: "草稿",
  searching: "寻找帮助者中",
  awaiting_response: "等待帮助者回复",
  matched: "匹配成功",
  in_progress: "交接中",
  completed: "已完成",
  cancelled: "已取消",
  expired: "已过期",
  failed: "未找到帮助者",
};

function displayTime(value: string) {
  return new Date(value).toLocaleString();
}

function DemoRoleSwitcher({ actorId, onChange }: { actorId: number; onChange: (id: number) => void }) {
  return <div className="demo-bar">
    <strong>Demo Mode</strong>
    <label htmlFor="demo-role">当前角色</label>
    <select id="demo-role" value={actorId} onChange={(event) => onChange(Number(event.target.value))}>
      {Object.entries(people).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
    </select>
  </div>;
}

function RequestFormPage() {
  const navigate = useNavigate();
  const [itemType, setItemType] = useState<ItemType>("scientific_calculator");
  const [location, setLocation] = useState("");
  const [deadline, setDeadline] = useState("");
  const [description, setDescription] = useState("");
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingRef.current) return;
    pendingRef.current = true;
    setError("");
    setPending(true);
    try {
      const created = await createHelpRequest({
        item_type: itemType,
        location,
        deadline: new Date(deadline).toISOString(),
        raw_text: description,
      });
      sessionStorage.setItem("lastRequestId", String(created.id));
      navigate(`/requests/${created.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建请求失败，请重试。");
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  }

  return <main className="shell">
    <div className="eyebrow">CAMPUSHANDS · BORROWLOOP</div>
    <h1>创建借物请求</h1>
    <p className="lead">以 Alice 的演示身份描述需求；确认解析结果后，再开始寻找帮助者。</p>
    <NaturalRequestFlow />
    <h2>结构化表单 · Demo / 调试入口</h2>
    <form onSubmit={submit} className="card">
      <label htmlFor="item-type">需要借什么？</label>
      <select id="item-type" value={itemType} onChange={(event) => setItemType(event.target.value as ItemType)}>
        {Object.entries(itemTypes).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
      </select>
      <label htmlFor="location">交接地点</label>
      <input id="location" value={location} onChange={(event) => setLocation(event.target.value)} maxLength={80} placeholder="例如 VA" required />
      <label htmlFor="deadline">最晚需要时间</label>
      <input id="deadline" type="datetime-local" value={deadline} onChange={(event) => setDeadline(event.target.value)} required />
      <label htmlFor="description">补充说明（可选）</label>
      <textarea id="description" value={description} onChange={(event) => setDescription(event.target.value)} maxLength={1000} rows={4} placeholder="例如：20 分钟后要考试" />
      {error && <p role="alert" className="error">{error}</p>}
      <button type="submit" data-action="create" disabled={pending}>{pending ? "正在保存…" : "保存请求"}</button>
    </form>
  </main>;
}

function RequestDetailPage() {
  const { id } = useParams();
  const [request, setRequest] = useState<HelpRequest | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const [agentOutcome, setAgentOutcome] = useState<AgentRun | null>(null);
  const [statusRefreshToken, setStatusRefreshToken] = useState(0);

  function beginAction(): boolean {
    if (pendingRef.current) return false;
    pendingRef.current = true;
    setPending(true);
    setError("");
    return true;
  }

  function endAction(refreshProvider = false) {
    pendingRef.current = false;
    setPending(false);
    if (refreshProvider) setStatusRefreshToken((value) => value + 1);
  }

  useEffect(() => {
    if (!id) return;
    sessionStorage.setItem("lastRequestId", id);
    setRequest(null);
    setAgentOutcome(null);
  }, [id]);

  const realtime = useRealtimeSnapshot<HelpRequest>({
    kind: "request", id: id ? Number(id) : null, actorId: 1,
    load: () => getHelpRequest(id ?? ""),
    onSnapshot: (snapshot) => {
      const unique = new Map((snapshot.events ?? []).map((event) => [event.id, event]));
      setRequest({ ...snapshot, events: [...unique.values()].sort((left, right) => left.id - right.id) });
    },
    onError: setError,
    snapshotEventId: (snapshot) => Math.max(0, ...(snapshot.events ?? []).map((event) => event.id)),
  });

  async function action(kind: RequestAction) {
    if (!id || !beginAction()) return;
    try {
      realtime.applyAuthoritative(await actOnRequest(id, kind));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "操作失败，请重试");
    } finally {
      endAction();
    }
  }

  async function runAgent() {
    if (!id || !beginAction()) return;
    setAgentOutcome(null);
    try {
      const outcome = await agentSearch(id);
      setAgentOutcome(outcome);
      realtime.applyAuthoritative(await getHelpRequest(id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Agent 暂不可用，请重试。");
      void realtime.refresh();
    } finally { endAction(true); }
  }

  async function observeAgent() {
    if (!id || !beginAction()) return;
    setAgentOutcome(null);
    try {
      const outcome = await agentObserve(id);
      setAgentOutcome(outcome);
      realtime.applyAuthoritative(await getHelpRequest(id));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Agent 暂不可用，请重试。"); }
    finally { endAction(true); }
  }

  return <main className="shell">
    <div className="eyebrow">CAMPUSHANDS · REQUEST #{id}</div>
    <h1>请求详情</h1>
    <SystemStatus refreshToken={statusRefreshToken} />
    <p className="connection-mode" aria-label="连接状态">{realtime.mode === "live" ? "实时连接" : "轮询模式 · 每 2 秒更新"}</p>
    {error && <p role="alert" className="error card">{error}</p>}
    {pending && <p role="status">正在处理，请稍候…</p>}
    {agentOutcome && <section className="card agent-outcome" aria-label="Agent 操作结果" role="status">
      <strong>本次 Agent 操作记录</strong>
      <p>当时结果：{agentOutcome.message}；当前阶段见下方请求状态。</p>
      <p>来源：{providerLabel(agentOutcome.provider)}{agentOutcome.fallback_active ? " · 本地备用" : ""}</p>
      <p>已验证并交给服务的工具：{agentOutcome.validated_actions?.length ? agentOutcome.validated_actions.join(" → ") : "无"}</p>
      <p>{agentOutcome.action_committed ? "服务已提交操作" : "未提交业务操作"}</p>
    </section>}
    {!request && !error && <p role="status">正在读取请求…</p>}
    {request && <>
      <section className="card" aria-label="请求信息">
        <div className="status">状态：{statusLabels[request.status]}（{request.status}）</div>
        <dl>
          <dt>物品</dt><dd>{itemTypes[request.item_type]}</dd>
          <dt>地点</dt><dd>{request.location}</dd>
          <dt>最晚需要时间</dt><dd>{displayTime(request.deadline)}</dd>
          {request.raw_text && <><dt>补充说明</dt><dd>{request.raw_text}</dd></>}
          {request.matched_helper && <><dt>帮助者</dt><dd>{request.matched_helper}</dd></>}
          {request.handoff_location && <><dt>交接地点</dt><dd>{request.handoff_location}</dd></>}
        </dl>
        <div className="actions">
          {request.status === "draft" && (request.events ?? []).some((event) => event.event_type === "request_parsed") ?
            <button data-action="agent-search" disabled={pending} onClick={() => void runAgent()}>Agent 开始匹配</button> :
            request.status === "draft" && <button data-action="search" disabled={pending} onClick={() => void action("search")}>开始匹配</button>}
          {(request.events ?? []).some((event) => event.event_type === "request_parsed") && request.status !== "draft" &&
            <button className="secondary" data-action="agent-observe" disabled={pending} onClick={() => void observeAgent()}>Agent 查看下一步</button>}
          {request.status === "matched" && <button data-action="start" disabled={pending} onClick={() => void action("start")}>开始交接</button>}
          {request.status === "in_progress" && !request.requester_confirmed && <button data-action="complete" disabled={pending} onClick={() => void action("complete")}>确认完成</button>}
          {["draft", "searching", "awaiting_response", "matched", "in_progress"].includes(request.status) &&
            <button className="secondary" data-action="cancel" disabled={pending} onClick={() => void action("cancel")}>取消请求</button>}
        </div>
        {request.status === "in_progress" && request.requester_confirmed && <p className="subtle">你已确认，等待帮助者确认。</p>}
      </section>
      <section className="card timeline" aria-label="公开操作时间线">
        <h2>操作时间线</h2>
        {(request.events ?? []).length === 0 ? <p className="subtle">尚无操作事件。</p> :
          <ol>{(request.events ?? []).map((event) => <li key={event.id}><span>{event.public_message}</span><time>{displayTime(event.created_at)}</time></li>)}</ol>}
      </section>
    </>}
    <Link className="back" to="/">创建另一条请求</Link>
  </main>;
}

function HelperInboxPage({ actorId }: { actorId: number }) {
  const [offers, setOffers] = useState<HelpOffer[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [pendingId, setPendingId] = useState<number | null>(null);
  const pendingRef = useRef(false);

  const realtime = useRealtimeSnapshot<HelpOffer[]>({
    kind: "helper", id: actorId === 1 ? null : actorId, actorId,
    load: () => getHelperOffers(actorId), onSnapshot: (snapshot) => { setOffers(snapshot); setLoaded(true); }, onError: setError,
  });

  async function action(offer: HelpOffer, kind: OfferAction) {
    if (pendingRef.current) return;
    pendingRef.current = true;
    setPendingId(offer.id);
    setError("");
    try {
      await actOnOffer(offer.id, actorId, kind);
      await realtime.refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "操作失败，请重试");
    } finally {
      pendingRef.current = false;
      setPendingId(null);
    }
  }

  return <main className="shell">
    <div className="eyebrow">CAMPUSHANDS · HELPER INBOX</div>
    <h1>{people[actorId]?.split(" · ")[0]} 的邀请</h1>
    <p className="connection-mode" aria-label="连接状态">{realtime.mode === "live" ? "实时连接" : "轮询模式 · 每 2 秒更新"}</p>
    <p className="lead">这里仅显示当前演示角色收到的站内借物请求。</p>
    {error && <p role="alert" className="error card">{error}</p>}
    {!loaded && !error && <p role="status" className="card">正在读取邀请…</p>}
    {pendingId !== null && <p role="status">正在更新邀请…</p>}
    {loaded && offers.length === 0 && !error && <p className="card">目前没有邀请。</p>}
    {offers.map((offer) => <section className="card offer" key={offer.id} aria-label={`邀请 ${offer.id}`}>
      <div className="status">{offer.item_name} · {offer.status}</div>
      <dl>
        <dt>物品</dt><dd>{itemTypes[offer.item_type]}</dd>
        {offer.message && <><dt>邀请说明</dt><dd>{offer.message}</dd></>}
        <dt>交接地点</dt><dd>{offer.location}</dd>
        <dt>最晚需要时间</dt><dd>{displayTime(offer.deadline)}</dd>
        <dt>邀请有效至</dt><dd>{displayTime(offer.expires_at)}</dd>
      </dl>
      {offer.status === "pending" && <div className="actions">
        <button data-action="accept" disabled={pendingId !== null} onClick={() => void action(offer, "accept")}>接受</button>
        <button className="secondary" data-action="decline" disabled={pendingId !== null} onClick={() => void action(offer, "decline")}>拒绝</button>
      </div>}
      {offer.status === "accepted" && offer.request_status === "in_progress" && !offer.helper_confirmed &&
        <button data-action="confirm-completion" disabled={pendingId !== null} onClick={() => void action(offer, "confirm-completion")}>确认交接完成</button>}
    </section>)}
  </main>;
}

export default function App() {
  const navigate = useNavigate();
  const [actorId, setActorId] = useState(() => Number(sessionStorage.getItem("demoActorId")) || 1);

  function switchRole(id: number) {
    setActorId(id);
    sessionStorage.setItem("demoActorId", String(id));
    const lastRequestId = sessionStorage.getItem("lastRequestId");
    navigate(id === 1 ? (lastRequestId ? `/requests/${lastRequestId}` : "/") : `/helpers/${id}/offers`);
  }

  return <>
    <DemoRoleSwitcher actorId={actorId} onChange={switchRole} />
    <Routes>
      <Route path="/" element={actorId === 1 ? <RequestFormPage /> : <HelperInboxPage key={actorId} actorId={actorId} />} />
      <Route path="/requests/:id" element={actorId === 1 ? <RequestDetailPage /> : <HelperInboxPage key={actorId} actorId={actorId} />} />
      <Route path="/helpers/:id/offers" element={actorId === 1 ? <main className="shell"><p>请选择 Helper 角色查看 Inbox。</p></main> : <HelperInboxPage key={actorId} actorId={actorId} />} />
      <Route path="*" element={<main className="shell"><h1>页面不存在</h1><Link to="/">返回首页</Link></main>} />
    </Routes>
  </>;
}
