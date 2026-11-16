import { useCallback, useEffect, useState } from "react";

import {
  acceptInvitation,
  confirmInvitationCompletion,
  declineInvitation,
  getDailyAvailability,
  getHelperProfile,
  getInvitations,
  proposeSubstitute,
} from "./api";
import type { DailyAvailability, HelperProfile, Invitation, InvitationInbox } from "./types";
import { useInvitationRealtime } from "./useInvitationRealtime";
import "./helperHall.css";


const reasonLabels = {
  exact_model: "准确型号匹配",
  exact_brand: "品牌匹配",
  compatible: "同类替代品",
  service_exact: "服务能力匹配",
} as const;

function displayTime(value: string): string {
  return new Intl.DateTimeFormat("zh-HK", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}

function InvitationSummary({ invitation }: { invitation: Invitation }) {
  return <>
    <div className="helper-invitation__top">
      <span className={`helper-urgency helper-urgency--${invitation.urgency}`}>{invitation.urgency === "high" ? "紧急" : "普通"}</span>
      <span>{reasonLabels[invitation.match_reason]}</span>
    </div>
    <h3>{invitation.need_summary}</h3>
    <dl className="helper-facts">
      <dt>Requester</dt><dd>{invitation.requester_name}</dd>
      <dt>交接地点</dt><dd>{invitation.location}</dd>
      <dt>最晚时间</dt><dd>{displayTime(invitation.deadline)}</dd>
      {(invitation.item_name || invitation.service_name) && <><dt>邀请能力</dt><dd>{invitation.item_name ?? invitation.service_name}</dd></>}
    </dl>
  </>;
}

export function InvitationInboxPanel({ actorId }: { actorId: number }) {
  const [inbox, setInbox] = useState<InvitationInbox | null>(null);
  const [profile, setProfile] = useState<HelperProfile | null>(null);
  const [daily, setDaily] = useState<DailyAvailability | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [substituteByInvitation, setSubstituteByInvitation] = useState<Record<number, number>>({});
  const [noteByInvitation, setNoteByInvitation] = useState<Record<number, string>>({});

  const refresh = useCallback(async () => {
    try {
      const [nextInbox, nextProfile, nextDaily] = await Promise.all([
        getInvitations(actorId),
        getHelperProfile(actorId),
        getDailyAvailability(actorId),
      ]);
      setInbox(nextInbox);
      setProfile(nextProfile);
      setDaily(nextDaily);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取邀请失败");
    }
  }, [actorId]);
  const connectionMode = useInvitationRealtime(actorId, refresh);

  useEffect(() => {
    setInbox(null);
    setNotice("");
  }, [actorId]);

  async function run(invitationId: number, operation: () => Promise<unknown>, success: string) {
    if (pendingId !== null) return;
    setPendingId(invitationId);
    setError("");
    setNotice("");
    try {
      await operation();
      setNotice(success);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "操作失败，请重试。");
      await refresh();
    } finally {
      setPendingId(null);
    }
  }

  const todayItemIds = new Set(daily?.availability?.item_ids ?? []);
  const activeItems = profile?.items.filter((item) => (
    item.active && item.available && todayItemIds.has(item.id)
  )) ?? [];
  return <section className="helper-panel" aria-label="收到的邀请">
    <header className="helper-panel__header">
      <div><span className="helper-kicker">TARGETED INVITATIONS</span><h2>收到的邀请</h2></div>
      <span className="helper-connection">{connectionMode === "live" ? "实时连接" : "轮询模式 · 每 2 秒"}</span>
    </header>
    <p className="helper-intro">这里只出现系统定向发送给你的请求，不需要浏览公开求助帖。</p>
    {error && <p role="alert" className="helper-alert helper-alert--error">{error}</p>}
    {notice && <p role="status" className="helper-alert helper-alert--success">{notice}</p>}
    {!inbox && !error && <p className="helper-card">正在读取邀请…</p>}

    {inbox && <>
      <div className="helper-section-title"><h3>待处理</h3><span>{inbox.pending.length} 条</span></div>
      {inbox.pending.length === 0 ? <p className="helper-empty">当前没有待处理邀请。</p> : inbox.pending.map((invitation) => <article className="helper-card helper-invitation" key={invitation.id} aria-label={`邀请 ${invitation.id}`}>
        <InvitationSummary invitation={invitation} />
        {invitation.status === "proposed" ? <p className="helper-alert">替代方案已发送，等待 Requester 确认。</p> : <>
          {invitation.category === "borrow" && activeItems.some((item) => item.item_type === invitation.request_item_type) && <div className="helper-substitute">
            <label>改提替代物品<select aria-label={`替代物品 ${invitation.id}`} value={substituteByInvitation[invitation.id] ?? ""} onChange={(event) => setSubstituteByInvitation((current) => ({ ...current, [invitation.id]: Number(event.target.value) }))}>
              <option value="">选择物品</option>{activeItems.filter((item) => item.item_type === invitation.request_item_type).map((item) => <option key={item.id} value={item.id}>{item.item_name}</option>)}
            </select></label>
            <input aria-label={`替代说明 ${invitation.id}`} placeholder="替代说明（可选）" value={noteByInvitation[invitation.id] ?? ""} onChange={(event) => setNoteByInvitation((current) => ({ ...current, [invitation.id]: event.target.value }))} />
            <button type="button" className="helper-secondary" disabled={pendingId !== null || !substituteByInvitation[invitation.id]} onClick={() => void run(
              invitation.id,
              () => proposeSubstitute(actorId, invitation.id, substituteByInvitation[invitation.id], noteByInvitation[invitation.id] ?? ""),
              "替代物品已提交。",
            )}>提出替代物品</button>
          </div>}
          <div className="helper-actions">
            <button type="button" disabled={pendingId !== null} onClick={() => void run(invitation.id, () => acceptInvitation(actorId, invitation.id), "已接受邀请。")}>接受</button>
            <button type="button" className="helper-secondary" disabled={pendingId !== null} onClick={() => void run(invitation.id, () => declineInvitation(actorId, invitation.id, "declined"), "已拒绝邀请。")}>拒绝</button>
            <button type="button" className="helper-secondary" disabled={pendingId !== null} onClick={() => void run(invitation.id, () => declineInvitation(actorId, invitation.id, "cannot_arrive"), "已告知 Requester 无法按时到达。")}>无法按时到达</button>
          </div>
        </>}
      </article>)}

      <div className="helper-section-title"><h3>正在进行</h3><span>{inbox.active.length} 条</span></div>
      {inbox.active.length === 0 ? <p className="helper-empty">当前没有进行中的任务。</p> : inbox.active.map((invitation) => <article className="helper-card helper-invitation" key={invitation.id} aria-label={`进行中任务 ${invitation.id}`}>
        <InvitationSummary invitation={invitation} />
        <p>当前状态：{invitation.request_status}</p>
        {invitation.request_status === "in_progress" && invitation.offer_id && !invitation.helper_confirmed && <button type="button" disabled={pendingId !== null} onClick={() => void run(
          invitation.id,
          () => confirmInvitationCompletion(actorId, invitation.offer_id as number),
          "你已确认交接完成。",
        )}>确认交接完成</button>}
      </article>)}

      {inbox.history.length > 0 && <details className="helper-card helper-history"><summary>历史邀请（{inbox.history.length}）</summary>
        <ul>{inbox.history.map((invitation) => <li key={invitation.id}><span>{invitation.need_summary}</span><span>{invitation.status}</span></li>)}</ul>
      </details>}
    </>}
  </section>;
}
