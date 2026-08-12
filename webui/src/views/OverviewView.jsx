import { ArrowRight, Clock3, Database, HardDrive, RefreshCw, ScanLine } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { assetTitle, assetType, formatDate } from "../data/normalize";
import { EmptyState, ErrorState, IconButton, LoadingState, StatusBadge } from "../components/ui";

const scanLabels = { idle: "等待扫描", starting: "启动中", scanning: "扫描中", running: "扫描中", stopped: "已停止", completed: "已完成", error: "扫描异常", failed: "扫描异常" };

function assetStatusLabel(status) {
  const labels = { active: "已归档", completed: "已归档", missing: "源端缺失", tombstone: "墓碑记录", tombstoned: "失效墓碑", protected: "源端已删保护", pending: "待处理", failed: "失败" };
  return labels[status] || status || "未知";
}

function OverviewMetric({ label, value, icon: Icon, tone = "neutral" }) {
  return <div className={`metric-item metric-${tone}`}><Icon size={18} aria-hidden="true" /><div><span>{label}</span><strong>{value}</strong></div></div>;
}

export default function OverviewView({ dashboard, loading, error, onRetry, onRefresh, onOpenAssets }) {
  return (
    <div className="view-stack">
      <header className="page-header">
        <div><p className="page-kicker">运行概况</p><h1>概览</h1><p className="page-description">查看扫描进度、本地库存和最近归档。</p></div>
        <IconButton label="刷新概览" onClick={onRefresh} disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} /></IconButton>
      </header>

      {loading && !dashboard && <LoadingState label="正在加载概览" />}
      {error && <ErrorState message={error} onRetry={onRetry} />}
      {dashboard && (
        <>
          <section className="scan-status-section" aria-labelledby="scan-status-title">
            <div className="section-heading"><div><h2 id="scan-status-title">扫描状态</h2><p>{dashboard.scan.message || "后台扫描任务的最近一次状态。"}</p></div><StatusBadge status={dashboard.scan.status}>{scanLabels[dashboard.scan.status] || dashboard.scan.status}</StatusBadge></div>
            <div className="scan-status-grid">
              <div><span>最近扫描</span><strong>{formatDate(dashboard.scan.last_scan_at)}</strong></div>
              <div><span>下次扫描</span><strong>{formatDate(dashboard.scan.next_scan_at)}</strong></div>
              <div><span>当前来源</span><strong>{dashboard.scan.current_source || "无"}</strong></div>
              <div><span>本轮归档</span><strong>{dashboard.scan.current}</strong></div>
            </div>
          </section>

          <section className="metrics-strip" aria-label="资产统计">
            <OverviewMetric label="资产总数" value={dashboard.stats.total_assets} icon={Database} />
            <OverviewMetric label="视频" value={dashboard.stats.videos} icon={ScanLine} tone="pink" />
            <OverviewMetric label="专栏" value={dashboard.stats.articles} icon={Clock3} tone="success" />
            <OverviewMetric label="磁盘可用" value={dashboard.stats.storage_free} icon={HardDrive} tone="amber" />
          </section>

          <section className="content-section" aria-labelledby="recent-title">
            <div className="section-heading"><div><h2 id="recent-title">近期资产</h2><p>最近写入或更新的本地记录。</p></div><button className="text-button with-icon" type="button" onClick={onOpenAssets}>查看全部<ArrowRight size={15} /></button></div>
            {dashboard.recent_assets.length === 0 ? <EmptyState title="还没有近期资产" description="完成一次扫描后，最近归档会出现在这里。" /> : <AssetPreviewTable assets={dashboard.recent_assets} />}
          </section>
        </>
      )}
    </div>
  );
}

function AssetPreviewTable({ assets }) {
  return <div className="table-wrap"><table className="preview-table"><thead><tr><th>资产</th><th>类型</th><th>状态</th><th>最近检查</th></tr></thead><tbody>{assets.slice(0, 6).map((asset) => <tr key={asset.id || asset.bvid || assetTitle(asset)}><td><div className="asset-cell"><Thumb asset={asset} /><div><span className="truncate">{assetTitle(asset)}</span><span className="mobile-asset-meta">{assetType(asset) === "article" ? "专栏" : "视频"} · {assetStatusLabel(asset.status)} · {formatDate(asset.updated_at)}</span></div></div></td><td>{assetType(asset) === "article" ? "专栏" : "视频"}</td><td><StatusBadge status={asset.status}>{assetStatusLabel(asset.status)}</StatusBadge></td><td className="muted-text">{formatDate(asset.updated_at)}</td></tr>)}</tbody></table></div>;
}

export function Thumb({ asset }) {
  return <PosterImage asset={asset} className="poster-thumb" />;
}

export function PosterImage({ asset, className }) {
  const [source, setSource] = useState("");
  const [broken, setBroken] = useState(false);
  const assetId = asset.id || asset.bvid;

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    setSource("");
    setBroken(false);
    if (!assetId || !asset.poster_available) return undefined;

    api.getAssetPoster(assetId)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        if (active) setSource(objectUrl);
        else URL.revokeObjectURL(objectUrl);
      })
      .catch(() => { if (active) setBroken(true); });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [asset.poster_available, assetId]);

  if (!assetId || !asset.poster_available || broken) return <div className={`${className} poster-empty`} aria-label="无封面">无图</div>;
  if (!source) return <div className={`${className} poster-empty poster-loading`} aria-label="封面加载中" />;
  return <img className={className} src={source} alt="" onError={() => setBroken(true)} />;
}
