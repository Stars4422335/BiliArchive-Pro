import { ChevronLeft, ChevronRight, FileSearch, Filter, Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { assetTitle, assetType, formatDate } from "../data/normalize";
import { EmptyState, ErrorState, IconButton, LoadingState, StatusBadge } from "../components/ui";
import { PosterImage, Thumb } from "./OverviewView";

const PAGE_SIZE = 10;
const statusLabels = { active: "已归档", completed: "已归档", missing: "源端缺失", tombstone: "墓碑记录", tombstoned: "失效墓碑", protected: "源端已删保护", pending: "待处理", failed: "失败" };

function statusLabel(status) { return statusLabels[status] || status || "未知"; }

export default function AssetsView({ assets, loading, error, onLoad }) {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState(null);
  const parameters = useMemo(() => ({
    query: query.trim(),
    type: typeFilter,
    status: statusFilter,
    page,
    page_size: PAGE_SIZE,
  }), [page, query, statusFilter, typeFilter]);
  const refresh = useCallback(() => onLoad(parameters), [onLoad, parameters]);
  const currentItems = assets?.items || [];
  const pages = Math.max(1, Math.ceil((assets?.total || 0) / PAGE_SIZE));

  useEffect(() => {
    const timer = window.setTimeout(refresh, query.trim() ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [query, refresh]);

  useEffect(() => {
    if (assets && page > pages) setPage(pages);
  }, [assets, page, pages]);

  function updateFilter(setter, value) { setter(value); setPage(1); }

  return (
    <div className="view-stack">
      <header className="page-header"><div><p className="page-kicker">本地媒体库</p><h1>资产</h1><p className="page-description">浏览已归档视频、专栏和源端失效记录。</p></div></header>
      <section className="content-section assets-section" aria-labelledby="assets-list-title">
        <div className="section-heading"><div><h2 id="assets-list-title">资产列表</h2><p>{assets ? `共 ${assets.total} 条匹配记录` : "正在读取资产数据"}</p></div><span className="table-count"><FileSearch size={15} />{assets?.total ?? 0} 条</span></div>
        <div className="toolbar">
          <label className="search-field"><Search size={16} /><span className="sr-only">搜索资产</span><input value={query} onChange={(event) => updateFilter(setQuery, event.target.value)} placeholder="搜索标题、BV 号或 UP 主" /></label>
          <label className="select-field"><Filter size={15} /><span className="sr-only">资产类型</span><select value={typeFilter} onChange={(event) => updateFilter(setTypeFilter, event.target.value)}><option value="all">全部类型</option><option value="video">视频</option><option value="article">专栏</option></select></label>
          <label className="select-field"><span className="sr-only">资产状态</span><select value={statusFilter} onChange={(event) => updateFilter(setStatusFilter, event.target.value)}><option value="all">全部状态</option><option value="active">已归档</option><option value="tombstoned">失效墓碑</option><option value="protected">源端已删保护</option></select></label>
        </div>
        {loading && !assets && <LoadingState label="正在加载资产" />}
        {error && <ErrorState message={error} onRetry={refresh} />}
        {!loading && !error && assets && currentItems.length === 0 && <EmptyState title={query || typeFilter !== "all" || statusFilter !== "all" ? "没有匹配资产" : "暂无资产"} description="尝试调整搜索或筛选条件。" />}
        {currentItems.length > 0 && <AssetTable assets={currentItems} onSelect={setSelected} />}
        {assets && assets.total > 0 && <Pagination page={page} pages={pages} onPageChange={setPage} />}
      </section>
      {selected && <AssetDrawer asset={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function AssetTable({ assets, onSelect }) {
  return <div className="table-wrap"><table className="assets-table"><thead><tr><th>资产</th><th>类型</th><th>分集</th><th>状态</th><th>最近检查</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{assets.map((asset, index) => <tr key={asset.id || asset.bvid || `${assetTitle(asset)}-${index}`} onClick={() => onSelect(asset)} tabIndex="0" onKeyDown={(event) => { if (event.key === "Enter") onSelect(asset); }}><td><div className="asset-cell"><Thumb asset={asset} /><div><strong className="truncate">{assetTitle(asset)}</strong><span className="muted-text">{asset.bvid || asset.id || "无标识"}</span></div></div></td><td>{assetType(asset) === "article" ? "专栏" : "视频"}</td><td className="muted-text">{asset.p_count || 1}</td><td><StatusBadge status={asset.status}>{statusLabel(asset.status)}</StatusBadge></td><td className="muted-text">{formatDate(asset.updated_at)}</td><td><button className="row-action" type="button" onClick={(event) => { event.stopPropagation(); onSelect(asset); }}>详情</button></td></tr>)}</tbody></table></div>;
}

function Pagination({ page, pages, onPageChange }) {
  return <div className="pagination"><span>第 {page} / {pages} 页</span><div><IconButton label="上一页" onClick={() => onPageChange(Math.max(1, page - 1))} disabled={page <= 1}><ChevronLeft size={16} /></IconButton><IconButton label="下一页" onClick={() => onPageChange(Math.min(pages, page + 1))} disabled={page >= pages}><ChevronRight size={16} /></IconButton></div></div>;
}

function AssetDrawer({ asset, onClose }) {
  useEffect(() => {
    const closeOnEscape = (event) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><aside className="detail-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title"><div className="drawer-header"><div><p className="page-kicker">资产详情</p><h2 id="drawer-title">{assetTitle(asset)}</h2></div><IconButton label="关闭详情" onClick={onClose}><X size={18} /></IconButton></div><PosterImage asset={asset} className="drawer-poster" /><dl className="detail-list"><Detail label="类型" value={assetType(asset) === "article" ? "专栏" : "视频"} /><Detail label="BV 号 / ID" value={asset.bvid || asset.id || "-"} /><Detail label="分集数" value={asset.p_count || 1} /><Detail label="状态" value={statusLabel(asset.status)} /><Detail label="本地路径" value={asset.local_path || asset.path || "-"} /><Detail label="最近检查" value={formatDate(asset.updated_at)} /></dl>{asset.description && <div className="detail-description"><h3>简介</h3><p>{asset.description}</p></div>}</aside></div>;
}

function Detail({ label, value }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
