import {element, pretty} from './client.js';

const labels = {READY:'通过', MISMATCH:'差异待复核', PENDING:'待复核', APPROVED:'已签发', HELD:'已暂缓'};
const headers = ['业务分组', '输入行', '计算值', '参考值', '判定'];
const decisions = {SIGN_NOW_COMPLETE:'按时签发 · 已齐', SIGN_NOW_CARRY:'按时签发 · 结转', BLOCKED:'暂不能签发'};
const sources = {CARRY:'结转下批', BLOCK:'阻断', INTAKE:'采信隔离'};
const kinds = {upsert:'写入', delete:'删除', watermark:'水位', expected:'参考'};

export function badge(status) {
  return element('span', labels[status] || status, {class:'badge', 'data-result':status, title: status});
}

export function snapshot(report, selected, stage) {
  const stats = report.intake;
  document.querySelector('[data-metric="input"]').textContent = stats.input;
  document.querySelector('[data-metric="accepted"]').textContent = stats.accepted;
  document.querySelector('[data-metric="isolated"]').textContent = stats.rejected;
  document.querySelector('[data-metric="cases"]').textContent = report.cases?.length ?? '—';
  const table = document.querySelector('#rows');
  table.replaceChildren();
  const head = element('tr');
  const body = table.createTBody();
  if (stage === 'intake') {
    head.append(...['源行', '记录键', '业务分组', '原因码'].map(title => element('th', title, {scope:'col'})));
    for (const item of stats.isolation) {
      const tr = body.insertRow();
      tr.append(...[item.line,item.record,item.case,item.reason].map(value=>element('td',value)));
    }
    if (!stats.isolation.length) body.insertRow().insertCell().textContent = '当前文件没有隔离行';
  } else {
    head.append(...headers.map(title => element('th', title, {scope:'col'})));
    for (const row of report.cases || []) {
      const tr = body.insertRow();
      const button = element('button',row.case,{type:'button','data-case':row.case,'aria-pressed':String(row.case===selected)});
      tr.insertCell().append(button);
      [row.records.length, row.measure?.value ?? '—', row.measure?.expected ?? '—'].forEach(value=>tr.insertCell().textContent=value);
      tr.insertCell().append(badge(row.status));
    }
  }
  table.createTHead().append(head);
  const picked = report.cases?.find(row=>row.case===selected);
  document.querySelector('#detail-title').textContent = picked ? `分组 ${picked.case}` : '采信摘要';
  const shown = picked ? picked.measure?.evidence ?? picked.prep?.details ?? {原因:picked.status} : stats.reasons;
  document.querySelector('#detail').textContent = pretty(shown);
  document.querySelector('#counts').textContent = report.balance ? `行数 ${report.balance.accounted}/${report.balance.input} · ${report.balance.ready} 组通过` : `采信 ${stats.accepted} 行 · 隔离 ${stats.rejected} 行`;
  handover(report);
  scopeTable(report);
}

function scopeTable(report) {
  const target = document.querySelector('#scope');
  const label = document.querySelector('#scope-counts');
  target.replaceChildren();
  const data = report.scope;
  if (!data) { label.textContent = '—'; return; }
  label.textContent = `已签 ${data.counts.signed} 条 · 阻断 ${data.counts.blocked} 条 · 水位 ${Object.entries(data.cutoff).map(([p,c])=>`P${p}≤${c}`).join(' ') || '—'}`;
  const head = element('tr');
  head.append(...['业务分组', '记录键', '来源行', '分区', '实体', '序号', '事件', '数量'].map(title => element('th', title, {scope:'col'})));
  const body = target.createTBody();
  for (const item of [...data.items, ...data.blocked]) {
    const tr = body.insertRow();
    if (item.blocked) tr.dataset.blocked = 'true';
    [item.case, item.record, item.line ?? '—', item.partition, item.entity, item.seq, kinds[item.kind] || item.kind, item.quantity]
      .forEach(value => tr.insertCell().textContent = value);
  }
  if (!data.items.length && !data.blocked.length) body.insertRow().insertCell().textContent = '本次没有已签记录';
  target.createTHead().append(head);
}

function handover(report) {
  const trade = report.handover;
  const decision = document.querySelector('#handover-decision');
  const note = document.querySelector('#handover-note');
  const table = document.querySelector('#pending');
  table.replaceChildren();
  if (!trade) { decision.textContent = '—'; note.textContent = ''; return; }
  decision.textContent = decisions[trade.decision] || trade.decision;
  decision.dataset.result = trade.signable ? 'READY' : 'BLOCKED';
  note.textContent = `${trade.note} · 本次签发 ${trade.signed} 条 · 水位 ${Object.entries(trade.cutoff).map(([p,c])=>`P${p}≤${c}`).join(' ') || '—'}`;
  const head = element('tr');
  head.append(...['来源', '业务分组', '记录键', '源行', '原因码'].map(title => element('th', title, {scope:'col'})));
  const body = table.createTBody();
  for (const item of report.pending?.items || []) {
    const tr = body.insertRow();
    tr.append(
      element('td', sources[item.source] || item.source),
      element('td', item.case),
      element('td', item.record ?? '整组'),
      element('td', item.line ?? '—'),
      element('td', item.reason),
    );
  }
  if (!report.pending?.items?.length) body.insertRow().insertCell().textContent = '没有待处理记录';
  table.createTHead().append(head);
}

export function prior(summary) {
  const panel = document.querySelector('#prior');
  const list = document.querySelector('#prior-runs');
  const groups = document.querySelector('#prior-groups');
  list.replaceChildren();
  if (!summary || !summary.runs.length) { panel.hidden = true; return; }
  panel.hidden = false;
  for (const run of summary.runs) {
    const item = element('li');
    item.append(element('span', `${run.id.slice(0,10)} · `), badge(run.status));
    item.append(element('span', ` ${run.cases.join('/')} · r${run.revision} · ${run.note || '无意见'}`));
    list.append(item);
  }
  groups.textContent = pretty(summary.groups);
}

export function history(items, active) {
  const target = document.querySelector('#history');
  target.replaceChildren();
  for (const run of items) {
    const button = element('button', run.id.slice(0,10), {'data-run':run.id,'aria-pressed':String(run.id===active),type:'button'});
    const item = element('li');
    item.append(button, badge(run.status));
    target.append(item);
  }
  if (!items.length) target.append(element('li','尚无执行批次'));
}
