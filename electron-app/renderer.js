/**
 * 欧菲斯工具工具箱 — 渲染进程
 * 前端 UI 逻辑，通过 window.opheceAPI 调用后端 REST API。
 */

const API = window.opheceAPI;
let scanResults = {};
let itemChecked = {};        // {分类id: Set(已勾选的子项索引)}
let selectedBackupIdx = -1;

// ═══════════════════════════════════════════════════════════════════
// 初始化
// ═══════════════════════════════════════════════════════════════════

window.addEventListener('DOMContentLoaded', async () => {
  setupTabs();
  await connectServer();
});

async function connectServer() {
  const el = document.getElementById('serverStatus');
  try {
    const r = await API.ping();
    el.textContent = `● 后端已连接 (v${r.version})`;
    el.className = 'server-status connected';
    setStatus('就绪 — 后端已连接');
    refreshOverview();
  } catch (e) {
    el.textContent = '● 后端未连接';
    el.className = 'server-status error';
    setStatus('后端连接失败 — 请确认 mz_server.py 已启动');
  }
}

// ═══════════════════════════════════════════════════════════════════
// 标签切换
// ═══════════════════════════════════════════════════════════════════

function setupTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    });
  });
}

// ═══════════════════════════════════════════════════════════════════
// 工具函数
// ═══════════════════════════════════════════════════════════════════

function humanSize(n) {
  n = Number(n);
  for (const u of ['B', 'KB', 'MB', 'GB', 'TB']) {
    if (n < 1024 || u === 'TB') return u === 'B' ? `${Math.round(n)} B` : `${n.toFixed(1)} ${u}`;
    n /= 1024;
  }
}

function showSpinner(id) { document.getElementById(id)?.classList.remove('hidden'); }
function hideSpinner(id) { document.getElementById(id)?.classList.add('hidden'); }

function setStatus(msg) {
  document.getElementById('statusText').textContent = msg;
}

function progress(on) {
  const pb = document.getElementById('progressBar');
  pb.className = 'progress-bar' + (on ? ' active' : '');
}

function barColor(pct) {
  if (pct > 80) return '#e74c3c';
  if (pct > 60) return '#f39c12';
  return '#4a6cf7';
}

// ═══════════════════════════════════════════════════════════════════
// Tab 1: 系统概览
// ═══════════════════════════════════════════════════════════════════

async function refreshOverview() {
  setStatus('加载磁盘信息...');
  progress(true);
  try {
    const data = await API.diskInfo();
    renderDiskCards(data.drives || []);
    setStatus('磁盘信息已刷新');
  } catch (e) {
    setStatus('磁盘信息获取失败: ' + e.message);
  }
  progress(false);
}

function renderDiskCards(drives) {
  const container = document.getElementById('diskCards');
  if (!drives.length) {
    container.innerHTML = '<div class="loading">无磁盘数据</div>';
    return;
  }
  container.innerHTML = drives.map(d => `
    <div class="disk-card">
      <div class="disk-header">
        <span class="disk-letter">${d.letter} 盘</span>
        <span class="disk-percent" style="color:${barColor(d.percent)}">${d.percent}%</span>
      </div>
      <div class="disk-bar-bg">
        <div class="disk-bar-fill" style="width:${Math.min(d.percent,100)}%;background:${barColor(d.percent)}"></div>
      </div>
      <div class="disk-detail">总 ${humanSize(d.total)} &nbsp; 已用 ${humanSize(d.used)} &nbsp; 可用 ${humanSize(d.free)}</div>
    </div>
  `).join('');
}

// ═══════════════════════════════════════════════════════════════════
// Tab 2: 基础清理
// ═══════════════════════════════════════════════════════════════════

const CATEGORIES = [
  ['temp', '临时文件'], ['recycle', '回收站'], ['browser', '浏览器缓存'],
  ['logs', '系统日志'], ['updates', 'Windows更新缓存'], ['thumbnails', '缩略图缓存'],
  ['prefetch', '预读取文件'], ['old_windows', '旧版Windows'], ['error_reports', '错误报告'],
  ['service_packs', '服务包备份'], ['hibernation', '休眠文件'], ['memory_dumps', '内存转储'],
  ['delivery_opt', '传递优化缓存'], ['font_cache', '字体缓存'], ['installer_cache', '安装程序缓存'],
  ['disk_cleanup', '磁盘清理备份'], ['app_cache', '应用程序缓存'], ['media_cache', '媒体缓存'],
  ['search_index', '搜索索引'], ['backup_temp', '备份临时文件'], ['update_temp', '更新临时文件'],
  ['driver_backup', '驱动备份'], ['app_crash', '应用崩溃转储'], ['app_logs', '应用程序日志'],
  ['recent_items', '最近项目'], ['notification', '通知缓存'], ['dns_cache', 'DNS缓存'],
  ['network_cache', '网络缓存'], ['printer_temp', '打印机临时'], ['device_temp', '设备临时'],
  ['windows_defender', 'Defender缓存'], ['store_cache', 'Store缓存'], ['onedrive_cache', 'OneDrive缓存'],
  ['downloads', '下载临时文件'], ['large_files', 'C盘大文件(>100MB)'],
  ['registry', '注册表历史(MUICache)'], ['assembly_temp', '程序集临时(.NET GAC)'],
  ['mozhen_system', '磨针系统日志(41条原始路径)'], ['packages_cache', 'Packages应用缓存'],
  ['c_root_temp', 'C盘根目录残留'], ['office_history', 'Office使用记录'],
];

// ── 清理风险等级 ─────────────────────────────────────────────────
// safe    = 可放心清理, 系统会自动重建
// caution = 注意, 清理后需重新缓存或失去回滚能力
// high    = 高风险, 涉及用户文件或系统功能, 默认不勾选
const RISK = {
  temp: 'safe', recycle: 'caution', browser: 'caution', logs: 'safe',
  updates: 'caution', thumbnails: 'safe', prefetch: 'safe', old_windows: 'caution',
  error_reports: 'safe', service_packs: 'caution', hibernation: 'high',
  memory_dumps: 'caution', delivery_opt: 'safe', font_cache: 'safe',
  installer_cache: 'caution', disk_cleanup: 'safe', app_cache: 'caution',
  media_cache: 'caution', search_index: 'caution', backup_temp: 'caution',
  update_temp: 'caution', driver_backup: 'high', app_crash: 'safe',
  app_logs: 'safe', recent_items: 'safe', notification: 'safe', dns_cache: 'safe',
  network_cache: 'safe', printer_temp: 'safe', device_temp: 'safe',
  windows_defender: 'caution', store_cache: 'caution', onedrive_cache: 'caution',
  downloads: 'high', large_files: 'high', registry: 'safe', assembly_temp: 'safe',
  mozhen_system: 'safe', packages_cache: 'caution', c_root_temp: 'caution',
  office_history: 'safe',
};
const RISK_LABEL = { safe: '安全', caution: '注意', high: '高风险' };
const RISK_HINT = {
  safe: '系统缓存/日志, 删除后自动重建, 可放心清理',
  caution: '清理后可能需重新下载缓存, 或失去系统回滚能力',
  high: '涉及用户文件或系统功能, 请逐项确认后再清理',
};
// 默认不勾选的分类 (高风险)
const DEFAULT_UNCHECKED = new Set(['large_files', 'downloads', 'hibernation', 'driver_backup']);

const CATEGORY_NAME = Object.fromEntries(CATEGORIES.map(([cid, name]) => [cid, name]));

/** 扫描中的居中提示 */
function showScanning() {
  const container = document.getElementById('catList');
  container.innerHTML = `
    <div class="scan-overlay">
      <div class="scan-spinner"></div>
      <div class="scan-title">正在扫描中…</div>
      <div class="scan-sub">正在遍历 ${CATEGORIES.length} 个清理分类，请稍候</div>
    </div>`;
}

async function scanBasic() {
  const container = document.getElementById('catList');
  const totalEl = document.getElementById('basicTotal');
  setStatus('正在扫描基础清理...');
  showScanning();
  if (totalEl) totalEl.innerHTML = '<span class="t-scan">扫描中…</span>';
  progress(true); showSpinner('basicSpinner');
  try {
    const data = await API.scan('basic');
    scanResults = data.results || {};
    itemChecked = {};
    renderCatList(scanResults);
    const total = Object.values(scanResults).reduce((s, items) => s + items.reduce((a, i) => a + i.size, 0), 0);
    setStatus(`扫描完成 — 发现 ${humanSize(total)} 可清理内容`);
  } catch (e) {
    setStatus('扫描失败: ' + e.message);
    container.innerHTML = `<div class="scan-overlay"><div class="scan-title scan-fail">扫描失败</div><div class="scan-sub">${e.message}</div></div>`;
    if (totalEl) totalEl.textContent = '';
  }
  progress(false); hideSpinner('basicSpinner');
}

function renderCatList(results) {
  const container = document.getElementById('catList');
  itemChecked = {};

  const rows = CATEGORIES.map(([cid, name]) => {
    const items = results[cid] || [];
    const sz = items.reduce((s, i) => s + (i.size || 0), 0);
    const cnt = items.reduce((s, i) => s + (i.count || 0), 0);

    const risk = RISK[cid] || 'caution';
    // 高风险分类默认不勾选
    const defaultOn = items.length > 0 && !DEFAULT_UNCHECKED.has(cid);
    itemChecked[cid] = defaultOn ? new Set(items.map((_, i) => i)) : new Set();

    let detailHtml = '';
    if (items.length > 0) {
      const itemRows = items.map((it, idx) => {
        const pathStr = (it.path || '').replace(/\\/g, ' \u203A ');
        const on = defaultOn ? 'checked' : '';
        return `<div class="cat-detail ${on}" data-cid="${cid}" data-idx="${idx}"
                     onclick="event.stopPropagation(); toggleItem('${cid}', ${idx})">
          <div class="cat-check item-check ${on}">${defaultOn ? '✓' : ''}</div>
          <div class="cat-name" title="${it.path || ''}">├ ${pathStr}</div>
          <div class="cat-size">${it.size ? humanSize(it.size) : ''}</div>
          <div class="cat-count">${it.count ? it.count + '项' : ''}</div>
        </div>`;
      }).join('');
      detailHtml = `<div class="cat-details" id="details-${cid}" style="display:none">${itemRows}</div>`;
    }

    return `<div class="cat-row ${defaultOn ? 'checked' : ''}" data-cid="${cid}" onclick="toggleCat(this, '${cid}')">
      <div class="cat-check">${defaultOn ? '✓' : ''}</div>
      <div class="cat-name">${name}</div>
      <div class="cat-risk risk-${risk}" title="${RISK_HINT[risk]}">${RISK_LABEL[risk]}</div>
      <div class="cat-size">${sz ? humanSize(sz) : ''}</div>
      <div class="cat-count">${cnt || ''}</div>
      <div class="cat-expand" data-cid="${cid}" onclick="event.stopPropagation(); toggleDetails('${cid}')">${items.length ? '&#9654;' : ''}</div>
    </div>${detailHtml}`;
  }).join('');

  container.innerHTML = rows;
  updateTotals();
}

/** 计算并刷新: 全部 / 已选 的大小与项数 */
function updateTotals() {
  let allSize = 0, allCount = 0;
  let selSize = 0, selCount = 0;
  let selCats = 0, totalCats = 0;
  let highSize = 0, highCount = 0;

  CATEGORIES.forEach(([cid]) => {
    const items = scanResults[cid] || [];
    if (items.length === 0) return;
    totalCats++;
    const checked = itemChecked[cid] || new Set();
    const isHigh = RISK[cid] === 'high';
    items.forEach((it, i) => {
      const s = it.size || 0, c = it.count || 0;
      allSize += s; allCount += c;
      if (checked.has(i)) {
        selSize += s; selCount += c;
        if (isHigh) { highSize += s; highCount += c; }
      }
    });
    if (checked.size === items.length) selCats++;
  });

  const el = document.getElementById('basicTotal');
  if (el) {
    let html =
      `<span class="t-all">全部 ${humanSize(allSize)} (${allCount.toLocaleString()} 项)</span>` +
      `<span class="t-sep">|</span>` +
      `<span class="t-sel">已选 ${humanSize(selSize)} (${selCount.toLocaleString()} 项)</span>` +
      `<span class="t-sep">|</span>` +
      `<span class="t-cat">${selCats}/${totalCats} 分类</span>`;
    if (highCount > 0) {
      html += `<span class="t-sep">|</span>` +
              `<span class="t-risk" title="高风险项涉及用户文件或系统功能">⚠ 高风险 ${humanSize(highSize)}</span>`;
    }
    el.innerHTML = html;
  }
  window._selTotal = { size: selSize, count: selCount, highSize, highCount };
}

/** 同步某个分类行的复选框状态 (全选 / 半选 / 未选) */
function syncCatRow(cid) {
  const items = scanResults[cid] || [];
  const checked = itemChecked[cid] || new Set();
  const row = document.querySelector(`.cat-row[data-cid="${cid}"]`);
  if (!row || items.length === 0) return;
  const box = row.querySelector('.cat-check');
  row.classList.remove('checked', 'partial');
  if (checked.size === 0) {
    box.textContent = '';
  } else if (checked.size === items.length) {
    row.classList.add('checked');
    box.textContent = '✓';
  } else {
    row.classList.add('partial');
    box.textContent = '−';
  }
}

/** 展开/收起时同步内部子项的勾选样式 */
function renderItemChecks(cid) {
  const items = scanResults[cid] || [];
  const checked = itemChecked[cid] || new Set();
  const wrap = document.getElementById('details-' + cid);
  if (!wrap) return;
  wrap.querySelectorAll('.cat-detail').forEach((el, idx) => {
    const on = checked.has(idx);
    const box = el.querySelector('.item-check');
    el.classList.toggle('checked', on);
    if (box) box.textContent = on ? '✓' : '';
  });
}

function toggleDetails(cid) {
  const el = document.getElementById('details-' + cid);
  const arrow = document.querySelector(`.cat-expand[data-cid="${cid}"]`);
  if (!el) return;
  if (el.style.display === 'none') {
    el.style.display = 'block';
    if (arrow) arrow.innerHTML = '&#9660;';
  } else {
    el.style.display = 'none';
    if (arrow) arrow.innerHTML = '&#9654;';
  }
}

/** 单项勾选 */
function toggleItem(cid, idx) {
  const items = scanResults[cid] || [];
  const checked = itemChecked[cid] || (itemChecked[cid] = new Set());
  if (checked.has(idx)) checked.delete(idx); else checked.add(idx);
  renderItemChecks(cid);
  syncCatRow(cid);
  updateTotals();
}

/** 分类级勾选: 全选 <-> 全不选 */
function toggleCat(el, cid) {
  const items = scanResults[cid] || [];
  const checked = itemChecked[cid] || (itemChecked[cid] = new Set());
  if (checked.size === items.length) {
    checked.clear();
  } else {
    items.forEach((_, i) => checked.add(i));
  }
  renderItemChecks(cid);
  syncCatRow(cid);
  updateTotals();
}

function toggleAllCats(checked) {
  CATEGORIES.forEach(([cid]) => {
    const items = scanResults[cid] || [];
    itemChecked[cid] = checked ? new Set(items.map((_, i) => i)) : new Set();
    renderItemChecks(cid);
    syncCatRow(cid);
  });
  updateTotals();
}

/** 展开全部明细 */
function expandAllDetails(open) {
  CATEGORIES.forEach(([cid]) => {
    const el = document.getElementById('details-' + cid);
    const arrow = document.querySelector(`.cat-expand[data-cid="${cid}"]`);
    if (!el) return;
    el.style.display = open ? 'block' : 'none';
    if (arrow && arrow.innerHTML.trim()) arrow.innerHTML = open ? '&#9660;' : '&#9654;';
  });
}

/** 收集所有已勾选的子项 (精确到单个路径) */
function collectSelectedItems() {
  const out = [];
  CATEGORIES.forEach(([cid]) => {
    const items = scanResults[cid] || [];
    const checked = itemChecked[cid] || new Set();
    checked.forEach(idx => {
      const it = items[idx];
      if (it) out.push({ cid, path: it.path, size: it.size || 0, count: it.count || 1 });
    });
  });
  return out;
}

async function cleanBasic() {
  const items = collectSelectedItems();
  if (!items.length) return alert('请先勾选要清理的内容');
  const total = items.reduce((s, i) => s + i.size, 0);
  const cats = [...new Set(items.map(i => i.cid))];

  // 高风险项单独提示
  const highItems = items.filter(i => RISK[i.cid] === 'high');
  const highCats = [...new Set(highItems.map(i => i.cid))];
  let msg = `已勾选 ${items.length} 项 (${cats.length} 个分类)\n预计释放约 ${humanSize(total)}\n`;
  if (highItems.length) {
    const highSize = highItems.reduce((s, i) => s + i.size, 0);
    msg += `\n⚠ 含高风险 ${highItems.length} 项 (${humanSize(highSize)}):\n` +
           highCats.map(c => `   · ${CATEGORY_NAME[c] || c}`).join('\n') +
           `\n这些涉及用户文件或系统功能, 删除后不可恢复!\n`;
  }
  if (!confirm(msg + '\n确认继续?')) return;

  setStatus(`正在清理 ${items.length} 项...`);
  progress(true); showSpinner('basicSpinner');
  try {
    const r = await API.clean({
      mode: 'basic', category_ids: cats, items,
      system_tasks: [], simulate: false, backup: true,
    });
    alert(`清理完成!\n释放空间: ${humanSize(r.freed)}\n删除项目: ${r.deleted}\n失败: ${r.failed}`);
    setStatus(`清理完成 — 释放 ${humanSize(r.freed)}`);
    scanBasic();  // 重新扫描
  } catch (e) {
    setStatus('清理失败: ' + e.message);
  }
  progress(false); hideSpinner('basicSpinner');
}

async function previewBasic() {
  const items = collectSelectedItems();
  if (!items.length) return alert('请先勾选要预览的内容');
  setStatus('预览中(模拟)...');
  progress(true);
  try {
    const r = await API.clean({
      mode: 'basic', category_ids: [...new Set(items.map(i => i.cid))],
      items, system_tasks: [], simulate: true, backup: false,
    });
    alert(`[模拟模式] 未删除任何文件\n预计释放: ${humanSize(r.freed)}\n涉及 ${r.deleted} 项`);
    setStatus('预览完成');
  } catch (e) {
    setStatus('预览失败: ' + e.message);
  }
  progress(false);
}

// ═══════════════════════════════════════════════════════════════════
// Tab 3: 系统清理
// ═══════════════════════════════════════════════════════════════════

async function scanSystem() {
  setStatus('正在扫描系统清理项...');
  progress(true); showSpinner('sysSpinner');
  try {
    const data = await API.scan('system');
    const info = data.system_info || {};
    const items = [];
    if (info.winsxs) items.push(`WinSxS可回收: ${humanSize(info.winsxs)}`);
    if (info.hiberfil) { items.push(`休眠文件: ${humanSize(info.hiberfil)}`); document.getElementById('sys-hibernate').checked = true; }
    if (info.memory_dmp) items.push(`内存转储: ${humanSize(info.memory_dmp)}`);
    if (info.pagefile) items.push(`C盘虚拟内存: ${humanSize(info.pagefile)}`);
    if (info.winsxs) document.getElementById('sys-dism').checked = true;
    document.getElementById('sysScanInfo').innerHTML = items.length
      ? '📊 ' + items.join(' &nbsp;|&nbsp; ')
      : '需要管理员权限才能完整扫描系统清理项';
    setStatus('系统扫描完成');
  } catch (e) {
    setStatus('系统扫描失败: ' + e.message);
  }
  progress(false); hideSpinner('sysSpinner');
}

const SYS_TASK_MAP = {
  'sys-dism': 'dism', 'sys-usn': 'usn', 'sys-restore': 'restore',
  'sys-hibernate': 'hibernate', 'sys-vmem': 'vmem', 'sys-eventlog': 'eventlog',
  'sys-psclean': 'psclean', 'sys-browser-sqlite': 'browser_sqlite',
  'sys-memreduct': 'memreduct', 'sys-prefetch': 'prefetch',
  'sys-appcache': 'appcache', 'sys-croottmp': 'croottmp',
  'sys-recycle-force': 'recycle_force',
};

async function cleanSystem() {
  const tasks = Object.entries(SYS_TASK_MAP)
    .filter(([elId]) => document.getElementById(elId)?.checked)
    .map(([, tid]) => tid);

  if (!tasks.length) return alert('请先勾选要执行的系统清理项');
  if (!confirm(`以下系统级操作将执行:\n\n${tasks.join('\n')}\n\n确认继续?`)) return;

  setStatus('正在执行系统清理...');
  progress(true); showSpinner('sysSpinner');
  try {
    const r = await API.clean({ mode: 'system', system_tasks: tasks, simulate: false, backup: false });
    const lines = Object.values(r.system_results || {}).map(v =>
      `  ${v.ok ? '✓' : '✗'} ${v.name}: ${(v.msg || '').slice(0, 60)}`
    ).join('\n');
    alert('执行结果:\n' + lines + '\n\n建议重启电脑。');
    setStatus('系统清理完成 — 建议重启');
  } catch (e) {
    setStatus('系统清理失败: ' + e.message);
  }
  progress(false); hideSpinner('sysSpinner');
}

// ═══════════════════════════════════════════════════════════════════
// Tab 4: 备份管理
// ═══════════════════════════════════════════════════════════════════

async function refreshBackups() {
  setStatus('加载备份列表...');
  progress(true);
  try {
    const data = await API.backups();
    const backups = data.backups || [];
    const tbody = document.querySelector('#backupTable tbody');
    if (backups.length === 0) {
      tbody.innerHTML = '<tr><td colspan="3" class="loading">无备份记录</td></tr>';
    } else {
      tbody.innerHTML = backups.map((b, i) =>
        `<tr class="${selectedBackupIdx === i ? 'selected' : ''}" data-idx="${i}" onclick="selectBackup(${i}, this)">
          <td>${b.name}</td>
          <td>${humanSize(b.size)}</td>
          <td>${b.time}</td>
        </tr>`
      ).join('');
    }
    document.getElementById('backupInfo').textContent = backups.length ? `共 ${backups.length} 个备份` : '';
    setStatus('备份列表已刷新');
  } catch (e) {
    setStatus('加载备份失败: ' + e.message);
  }
  progress(false);
}

function selectBackup(idx, row) {
  selectedBackupIdx = idx;
  document.querySelectorAll('#backupTable tbody tr').forEach(r => r.classList.remove('selected'));
  row.classList.add('selected');
}

async function restoreBackup() {
  if (selectedBackupIdx < 0) return alert('请先在列表中选择一个备份');
  const name = document.querySelector('#backupTable tbody tr.selected td')?.textContent || '';
  if (!confirm(`将恢复备份: ${name}\n文件将被还原到原始位置。确认?`)) return;

  setStatus(`正在恢复 ${name}...`);
  progress(true);
  try {
    const r = await API.restore(selectedBackupIdx);
    alert(`已恢复 ${r.restored} 个文件`);
    setStatus(`恢复完成 — ${r.restored} 个文件`);
    refreshBackups();
  } catch (e) {
    setStatus('恢复失败: ' + e.message);
  }
  progress(false);
}