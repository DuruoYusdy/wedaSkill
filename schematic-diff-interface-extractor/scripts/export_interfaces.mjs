// 从 interface_workbook.py export 的数据模型导出 XLSX。依赖 @oai/artifact-tool。
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [input, outputDir, previewRoot] = process.argv.slice(2);
if (!input || !outputDir || outputDir.endsWith('.xlsx')) throw new Error('用法: node export_interfaces.mjs model.json output-directory [preview-directory]；生成原始/修改后两个独立文件');
// 可显式设置 ARTIFACT_TOOL_MODULE 为已有安装的公开入口路径；不下载或修改全局依赖。
const moduleName = process.env.ARTIFACT_TOOL_MODULE;
const { Workbook, SpreadsheetFile } = await import(moduleName ? pathToFileURL(moduleName).href : '@oai/artifact-tool');
const data = JSON.parse(await fs.readFile(input, 'utf8'));
if (data.schema_version !== 4) throw new Error('需要v4数据模型：先绑定当前框图JSON并生成逐信号变更记录再导出');
for (const [version, label] of [['before', '原始信号接口'], ['after', '修改后信号接口'], ['changes', '信号接口变更清单']]) {
const output = path.join(outputDir, `${label}.xlsx`);
const previewDir = previewRoot ? path.join(previewRoot, version) : null;
const wb = Workbook.create();
const literal = v => typeof v === 'string' && /^[=+@-]/.test(v) ? "'" + v : v;
let seq = 0;
const previews = [];
function col(n) { let s = ''; for (n++; n; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s; return s; }
function base(name, title) {
  const sh = wb.worksheets.add(name);
  sh.showGridLines = false;
  sh.getRange('A2').values = [[literal(title)]];
  sh.getRange('A2').format.font = { name: 'Arial', size: 15, bold: true, color: '#20354D' };
  sh.getRange('A3:U3').format.borders = { bottom: { style: 'thin', color: '#BAC6D3' } };
  return sh;
}
function table(sh, start, headers, rows, kind) {
  const end = start + Math.max(rows.length, 1);
  const last = col(headers.length - 1);
  const range = sh.getRange(`A${start}:${last}${end}`);
  range.values = [headers, ...(rows.length ? rows : [headers.map((_, i) => i === 0 ? '无接口记录' : '')])].map(r => r.map(literal));
  range.format.font = { name: 'Arial', size: 10, color: '#25364A' };
  range.format.verticalAlignment = 'center';
  range.format.rowHeight = 32;
  range.format.wrapText = true;
  const tbl = sh.tables.add(`A${start}:${last}${end}`, true, `Interfaces${++seq}`);
  tbl.showFilterButton = true;
  const head = sh.getRange(`A${start}:${last}${start}`);
  head.format.fill = kind === 'before' ? '#566779' : '#294F70';
  head.format.font = { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' };
  head.format.horizontalAlignment = 'center';
  head.format.rowHeight = 34;
  for (let c = 0; c < headers.length; c++) sh.getRange(`${col(c)}${start}:${col(c)}${end}`).format.columnWidth = 20;
  if (headers === data.columns) {
    sh.getRange(`G${start}:G${end}`).format.columnWidth = 42;
    sh.getRange(`H${start}:H${end}`).format.columnWidth = 50;
    sh.getRange(`I${start + 1}:I${end}`).setNumberFormat('0.0%');
    sh.getRange(`J${start}:J${end}`).format.columnWidth = 27;
    sh.getRange(`S${start}:U${end}`).format.columnWidth = 44;
    sh.getRange(`K${start}:M${end}`).format.columnWidth = 15;
    sh.getRange(`P${start}:R${end}`).format.columnWidth = 25;
    for (const [text, fill] of [['新增','#E2F0D9'], ['删除','#FCE4D6'], ['修改','#FFF2CC']]) {
      sh.getRange(`N${start + 1}:N${end}`).conditionalFormats.add('containsText', {text, format:{fill, font:{bold:true}}});
    }
    sh.getRange(`U${start + 1}:U${end}`).conditionalFormats.add('notContainsText', {
      text: '[]', format: { fill: '#FFF1D6', font: { color: '#8B4C11' } }
    });
    // 每条信号可包含支路证据；按内容适当增高，不能裁掉长说明。
    rows.forEach((r, index) => {
      const lines = Math.max(1, ...r.map((v, c) => Math.ceil(String(v ?? '').length / ([6, 7, 18, 19, 20].includes(c) ? 35 : 17))));
      sh.getRange(`A${start + index + 1}:${last}${start + index + 1}`).format.rowHeight = Math.max(32, lines * 15);
    });
  } else if (headers === data.change_columns) {
    sh.getRange(`A${start}:F${end}`).format.columnWidth = 21;
    sh.getRange(`G${start}:G${end}`).format.columnWidth = 26;
    sh.getRange(`H${start}:H${end}`).format.columnWidth = 52;
    sh.getRange(`I${start + 1}:I${end}`).setNumberFormat('0.0%');
    sh.getRange(`J${start}:K${end}`).format.columnWidth = 28;
    sh.getRange(`L${start}:L${end}`).format.columnWidth = 12;
    for (const [text, fill] of [['新增','#E2F0D9'], ['删除','#FCE4D6'], ['修改','#FFF2CC']]) {
      sh.getRange(`L${start + 1}:L${end}`).conditionalFormats.add('containsText', {text, format:{fill, font:{bold:true}}});
    }
    rows.forEach((r, index) => {
      const lines = Math.max(1, ...r.map((v, c) => Math.ceil(String(v ?? '').length / ([7, 9, 10].includes(c) ? 35 : 18))));
      sh.getRange(`A${start + index + 1}:${last}${start + index + 1}`).format.rowHeight = Math.max(32, lines * 15);
    });
  }
  return end;
}
const summary = base('BLOCK_INFO', `${label}（${data.title}）`);
summary.tabColor = '#20354D';
summary.getRange('A4').values = [[literal(`原理图：${data.source}；目标框图：${data.target}`)]];
const summaryHeaders = version === 'changes'
  ? ['位号', 'code', '类型', 'block标识', 'block名称', '目标位号', '目标code', '器件页签', '分析说明']
  : ['位号', 'code', '操作', 'block标识', 'block名称', '目标位号', '目标code', '原始接口数', '修改后接口数', '待确认行数', '目标缺项数', '原始覆盖', '器件页签', '分析说明'];
const summaryRows = version === 'changes'
  ? data.devices.map(d => [d.refdes || d.target_refdes || '待分配', d.code || d.target_code || '未提供',
      ({ADD:'新增',CHANGE:'变更',DELETE:'删除'})[d.action], d.block_id || '', d.block_name || '',
      d.target_refdes || '', d.target_code || '', d.action === 'DELETE' ? '不创建器件页' : d.sheet, d.reason])
  : data.devices.map(d => [d.refdes || '待分配', d.code || '未提供',
      ({ADD:'新增',CHANGE:'变更',DELETE:'删除'})[d.action], d.block_id || '', d.block_name || '',
      d.target_refdes || '', d.target_code || '', d.before.length, d.after.length, d.pending_count,
      d.target_pending, d.coverage, d.action === 'DELETE' && version === 'after' ? '仅见原始表' : d.sheet, d.reason]);
table(summary, 6, summaryHeaders, summaryRows, 'after');
summary.getRange(`${version === 'changes' ? 'I' : 'N'}6:${version === 'changes' ? 'I' : 'N'}${7 + data.devices.length}`).format.columnWidth = 55;
summary.getRange('A4').format.font = { name: 'Arial', size: 10, color: '#566779' };
previews.push({ name: 'BLOCK_INFO', ranges: ['A1:G10', 'H6:N10'] });
let deletion;
let deletionRow = 6;
for (const d of data.devices) {
  if (version === 'changes') {
    if (d.action === 'DELETE') continue;
    const sh = base(d.sheet, `${d.refdes || d.target_refdes || d.id}  ${d.block_name || ''}  信号接口变更`);
    sh.getRange('A4').values = [['仅列新增、修改、删除的信号接口；原理图pin脚列只显示源端Pin名称']];
    const end = table(sh, 6, data.change_columns, d.changes, 'after');
    sh.freezePanes.freezeRows(6);
    previews.push({name:d.sheet, ranges:[`A4:L${Math.min(end, 12)}`]});
    continue;
  }
  if (d.action === 'DELETE') {
    if (version === 'after') continue;
    if (!deletion) deletion = base('原始接口_删除', '删除器件的原始接口留档');
    deletion.getRange(`A${deletionRow - 1}`).values = [[`${d.refdes}  ${d.code || ''}  ${d.reason}`]];
    const end = table(deletion, deletionRow, data.columns, d.before, 'before');
    previews.push({ name: deletion.name, ranges: [`A${deletionRow - 1}:J${Math.min(end, deletionRow + 3)}`] });
    deletionRow = end + 4;
    continue;
  }
  const sh = base(d.sheet, `${d.refdes || d.id}  ${d.block_name || ''}  ${label}`);
  sh.getRange('A4').values = [[version === 'before' ? '原始接口事实；block标识和名称由当前框图JSON映射' : '修改后设计提案；PROPOSED不代表已经修改原理图']];
  const end = table(sh, 6, data.columns, d[version], version);
  sh.freezePanes.freezeRows(6);
  previews.push({name:d.sheet, ranges:[`A4:J${Math.min(end, 11)}`, `K6:U${Math.min(end, 11)}`]});
}
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:`BLOCK_INFO!A6:${version === 'changes' ? 'I' : 'N'}10`,include:'values,formulas',tableMaxRows:5,tableMaxCols:14,maxChars:3000})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:20},maxChars:1000})).ndjson);
if (previewDir) {
  await fs.mkdir(previewDir, {recursive:true});
  for (const p of previews) for (let i = 0; i < p.ranges.length; i++) {
    const blob = await wb.render({sheetName:p.name,range:p.ranges[i],scale:1,format:'png'});
    await fs.writeFile(path.join(previewDir, `${p.name}-${i}.png`), new Uint8Array(await blob.arrayBuffer()));
  }
}
await fs.mkdir(path.dirname(output), {recursive:true});
await (await SpreadsheetFile.exportXlsx(wb)).save(output);
console.log(JSON.stringify({output, sheets: ['BLOCK_INFO', ...new Set(data.devices.filter(d=>version==='before'||d.action!=='DELETE').map(d=>d.sheet))], pending:data.pending.length}));
}
