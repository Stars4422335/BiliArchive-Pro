import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw, RotateCcw, Terminal } from "lucide-react";
import { ApiError, api } from "../api/client";
import { ErrorState, LoadingState, StatusBadge } from "../components/ui";

const COMMAND_LABELS = {
  trigger_scan: "触发即时巡检",
  redownload_asset: "重新下载资产",
  restart: "提示重启核心",
};

const STATUS_LABELS = {
  pending: "等待核心消费",
  running: "核心处理中",
  done: "已完成",
  failed: "失败",
};

export default function OperationsView({ requireAuthentication }) {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState("");
  const [feedback, setFeedback] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const polling = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setSnapshot(await api.getCommands());
    } catch (loadError) {
      if (loadError instanceof ApiError && loadError.status === 401) {
        requireAuthentication();
      } else {
        setError(loadError?.message || "命令通道状态加载失败。");
      }
    } finally {
      setLoading(false);
    }
  }, [requireAuthentication]);

  useEffect(() => { load(); }, [load]);

  // 队列里有待处理命令时轻量轮询，直到核心回执完毕。
  useEffect(() => {
    const hasPending = (snapshot?.pending?.length || 0) > 0
      || (snapshot?.history || []).some((item) => item.status === "pending" || item.status === "running");
    if (!hasPending || polling.current) return undefined;
    polling.current = true;
    const timer = setInterval(() => {
      api.getCommands().then(setSnapshot).catch(() => {});
    }, 3000);
    return () => { clearInterval(timer); polling.current = false; };
  }, [snapshot]);

  async function submit(body, key) {
    setSubmitting(key);
    setFeedback(null);
    try {
      const record = await api.postCommand(body);
      setFeedback({ tone: "success", message: `已下发「${COMMAND_LABELS[body.command] || body.command}」，核心将在下个轮询周期处理。` });
      setConfirming(null);
      await load();
      return record;
    } catch (submitError) {
      if (submitError instanceof ApiError && submitError.status === 401) {
        requireAuthentication();
      }
      setFeedback({ tone: "danger", message: submitError?.message || "命令下发失败。" });
      return null;
    } finally {
      setSubmitting("");
    }
  }

  const history = [...(snapshot?.history || [])].reverse();

  return <div className="view-stack">
    <header className="page-header">
      <div>
        <p className="page-kicker">运维操作</p>
        <h1>操作与审计</h1>
        <p className="page-description">向核心引擎下发指令并查看执行回执。删除本地资产始终不在此开放。</p>
      </div>
      <div className="header-actions">
        <button className="button button-secondary" type="button" onClick={load} disabled={loading}>
          <RefreshCw size={16} />刷新
        </button>
      </div>
    </header>

    {loading && !snapshot && <LoadingState label="正在加载命令通道" />}
    {error && <ErrorState message={error} onRetry={load} />}
    {feedback && <div className={`state-block ${feedback.tone === "danger" ? "state-error" : "state-success"}`} role="status">{feedback.message}</div>}

    {snapshot && <>
      <section className="settings-section">
        <div className="settings-section-heading">
          <div><h2>可执行操作</h2><p>指令写入本地命令通道，由核心引擎轮询消费，无需直连守护进程。</p></div>
        </div>
        <div className="command-grid">
          <CommandCard
            icon={RefreshCw}
            title="立即巡检"
            description="跳过剩余休眠时间，提前开始下一轮全量巡检。正在进行的下载不会被中断。"
            actionLabel="触发巡检"
            busy={submitting === "trigger_scan"}
            disabled={Boolean(submitting)}
            onRun={() => submit({ command: "trigger_scan" }, "trigger_scan")}
          />
          <CommandCard
            icon={RotateCcw}
            title="重启核心"
            description="核心在当前轮次结束后安全退出并关闭数据库，由 systemd / Docker 重新拉起。"
            actionLabel="提示重启"
            tone="warning"
            confirmTitle="确认提示核心重启？"
            confirmBody="核心引擎将在当前轮次完成后安全退出。若由 Docker 或 systemd 托管，它会自动重新拉起；否则需要你手动重启。"
            confirmLabel="我已了解，发送指令"
            busy={submitting === "restart"}
            disabled={Boolean(submitting)}
            confirming={confirming === "restart"}
            onAsk={() => setConfirming("restart")}
            onCancel={() => setConfirming(null)}
            onRun={() => submit({ command: "restart" }, "restart")}
          />
          <RedownloadCard
            busy={submitting === "redownload"}
            disabled={Boolean(submitting)}
            confirming={confirming?.kind === "redownload" ? confirming.assetId : null}
            onAsk={(assetId) => setConfirming({ kind: "redownload", assetId })}
            onCancel={() => setConfirming(null)}
            onRun={(assetId) => submit({ command: "redownload_asset", payload: { asset_id: assetId } }, "redownload")}
          />
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-heading">
          <div><h2>待处理队列</h2><p>已下发但尚未被核心引擎消费的命令。</p></div>
        </div>
        {snapshot.pending.length === 0
          ? <p className="inline-empty">队列为空。</p>
          : <ul className="command-list">{snapshot.pending.map((item) => <CommandRow key={item.id} item={item} />)}</ul>}
      </section>

      <section className="settings-section">
        <div className="settings-section-heading">
          <div><h2>执行审计</h2><p>最近 {history.length} 条命令的执行回执，最多保留 50 条。</p></div>
        </div>
        {history.length === 0
          ? <p className="inline-empty">暂无执行记录。</p>
          : <ul className="command-list">{history.map((item) => <CommandRow key={item.id} item={item} />)}</ul>}
      </section>
    </>}
  </div>;
}

function CommandCard({ icon: Icon, title, description, actionLabel, busy, disabled, tone = "primary", onRun, onAsk, onCancel, confirming, confirmTitle, confirmBody, confirmLabel }) {
  if (confirming) {
    return <div className="command-card command-card-confirm">
      <h3>{confirmTitle}</h3>
      <p>{confirmBody}</p>
      <div className="command-card-actions">
        <button className="button button-secondary button-compact" type="button" onClick={onCancel} disabled={busy}>取消</button>
        <button className={`button button-${tone} button-compact`} type="button" onClick={onRun} disabled={busy}>{busy ? "发送中…" : confirmLabel}</button>
      </div>
    </div>;
  }
  return <div className="command-card">
    <div className="command-card-icon"><Icon size={18} aria-hidden="true" /></div>
    <h3>{title}</h3>
    <p>{description}</p>
    <div className="command-card-actions">
      <button className={`button button-${tone} button-compact`} type="button" onClick={onAsk || onRun} disabled={disabled}>
        {busy ? "处理中…" : actionLabel}
      </button>
    </div>
  </div>;
}

function RedownloadCard({ busy, disabled, confirming, onAsk, onCancel, onRun }) {
  const [assetId, setAssetId] = useState("");
  const trimmed = assetId.trim();

  // confirming 直接是待确认的资产编号（字符串）或 null。
  if (confirming) {
    return <div className="command-card command-card-confirm">
      <h3>确认重新下载该资产？</h3>
      <p>将重新抓取 <code>{confirming}</code>。已有本地文件不会被删除，下载结果按原目录规则覆盖写入，并计入本轮下载量。</p>
      <div className="command-card-actions">
        <button className="button button-secondary button-compact" type="button" onClick={onCancel} disabled={busy}>取消</button>
        <button className="button button-warning button-compact" type="button" onClick={() => onRun(confirming)} disabled={busy}>{busy ? "发送中…" : "确认重下"}</button>
      </div>
    </div>;
  }

  return <div className="command-card">
    <div className="command-card-icon"><Terminal size={18} aria-hidden="true" /></div>
    <h3>重新下载资产</h3>
    <p>按 BV / av 编号重新抓取单个视频。资产需仍在源端存在，否则请改用即时巡检让核心自行判定。</p>
    <label className="field">
      <span>资产编号</span>
      <input value={assetId} onChange={(event) => setAssetId(event.target.value)} placeholder="BV1GJ411x7h7" maxLength={32} />
    </label>
    <div className="command-card-actions">
      <button
        className="button button-warning button-compact"
        type="button"
        disabled={disabled || !/^(BV[0-9A-Za-z]{8,12}|av[0-9]{1,20})$/.test(trimmed)}
        onClick={() => onAsk(trimmed)}
      >
        {busy ? "处理中…" : "重新下载"}
      </button>
    </div>
  </div>;
}

function CommandRow({ item }) {
  const payload = item.payload || {};
  const target = payload.asset_id ? ` · ${payload.asset_id}` : "";
  return <li className="command-row">
    <div className="command-row-main">
      <strong>{COMMAND_LABELS[item.command] || item.command}{target}</strong>
      <span>{item.note || item.result || "等待核心引擎回执"}</span>
    </div>
    <div className="command-row-meta">
      <StatusBadge status={item.status}>{STATUS_LABELS[item.status] || item.status}</StatusBadge>
      <time dateTime={item.finished_at || item.queued_at}>{item.finished_at || item.queued_at || ""}</time>
    </div>
  </li>;
}
