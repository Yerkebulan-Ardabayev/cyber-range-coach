const app = document.querySelector('#app');
const LAB_ID = 'lab-1-2-service-enumeration';
const esc = value => String(value || '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
let lab, phaseIndex = 0, attemptId = null, range = 'не проверен', parsedFacts, mentorFeedback, playbookMode = 'guided', playbookPhase = 0;

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Ошибка сервера');
  return data;
}
const post = (url, body) => api(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});

function setActive(route) { document.querySelectorAll('nav a').forEach(link => link.classList.toggle('active', link.href.endsWith('#' + route))); }
function context() { return `<aside class="lab-context"><h2>МИССИЯ</h2><p>${esc(lab.mission)}</p><h2>СОХРАНЁННАЯ ГИПОТЕЗА</h2><p>${attemptId ? 'Сохранена для текущей открытой попытки.' : 'Пока не сохранена.'}</p><h2>ПОЛИГОН</h2><p>${esc(range)}</p><nav class="context-links" aria-label="Материалы лабы"><a href="#playbooks">Playbook</a><a href="#notes">Заметки</a></nav></aside>`; }
function header() { return `<header class="runner-header"><div class="header-primary"><span class="role">● RED TEAM</span><span class="breadcrumb">Web Pentest <b>›</b> Recon <b>›</b> Service Enumeration</span></div><div class="header-meta"><span>Шаг ${phaseIndex + 1} из ${lab.steps.length}</span><span class="assist">Помощь: серверный уровень</span></div></header>`; }
function help() { return `<details class="help"><summary>Нужна помощь</summary><button id="hint">Запросить подсказку 1 из 3</button><button id="solution">Раскрыть solution</button><div id="help-result"></div></details>`; }
function feedback() { return !mentorFeedback ? '' : `<section class="feedback"><h2>РАЗБОР НАСТАВНИКА</h2><p>Названо: ${esc(mentorFeedback.named.join(', ') || 'ничего')}</p><p>Пропущено: ${esc(mentorFeedback.missed.join(', ') || 'ничего')}</p><p>Гипотеза как факт: ${esc(mentorFeedback.flagged_as_fact.join(', ') || 'не отмечено')}</p><p>${esc(mentorFeedback.question)}</p></section>`; }

function factsTable() {
  if (!parsedFacts) return '<p>Факты будут показаны после разбора вывода.</p>';
  const labels = {port: 'порт', state: 'состояние', service: 'сервис', version: 'версия'};
  const rows = parsedFacts.facts.map(fact => `<tr><td>${esc(fact.text)}</td><td>${esc(labels[fact.kind] || fact.kind)}</td><td class="source-line">стр. ${esc(fact.line)}</td></tr>`).join('');
  const leftovers = (parsedFacts.unparsed || []).map(item => `<li><span>стр. ${esc(item.line)}</span><code>${esc(item.text)}</code></li>`).join('');
  return `<table class="facts-table"><thead><tr><th>Значение</th><th>Вид</th><th>Исходная строка</th></tr></thead><tbody>${rows}</tbody></table><div class="unparsed"><span>не разобрано: ${(parsedFacts.unparsed || []).length} строк</span><button type="button" id="toggle-unparsed" aria-expanded="false">Показать</button><ul id="unparsed-lines" hidden>${leftovers}</ul></div>`;
}
function phaseBody(step) {
  if (step.kind === 'think') return `<p>${esc(step.prompt)}</p><h2>ТВОЯ ГИПОТЕЗА</h2><textarea id="hypothesis" placeholder="Что именно ты рассчитываешь узнать?"></textarea><button id="save-hypothesis">Сохранить гипотезу и открыть шаг</button><p class="muted">Команда откроется только после гипотезы.</p>`;
  if (step.kind === 'execute') { const command = step.command ? `<div class="command-block"><pre>${esc(step.command)}</pre><button type="button" id="copy-command">Копировать</button></div>` : `<button id="reveal-command">Раскрыть команду</button>`; return `<h2>ВЫПОЛНИ У СЕБЯ В TERMINAL</h2>${command}<details><summary>Разбор команды</summary>${(step.command_anatomy || []).map(item => `<p>${esc(item)}</p>`).join('')}</details><h2>ВСТАВЬ РЕАЛЬНЫЙ ВЫВОД</h2><textarea id="raw-output"></textarea><button id="parse-output">Разобрать вывод</button>${help()}`; }
  if (step.kind === 'analyse') return `<h2>ЧТО ТЫ ВИДИШЬ</h2>${factsTable()}<textarea id="conclusion" placeholder="Твой вывод, сначала ты, потом система"></textarea><button id="send-conclusion">Отправить вывод</button>${help()}`;
  if (step.kind === 'decide') return `${feedback()}<h2>РЕШЕНИЕ ЗА ТОБОЙ</h2><p>${esc(step.prompt)}</p>${(step.decision_options || []).map(option => `<label><input type="radio" name="choice" value="${esc(option)}"> ${esc(option)}</label>`).join('')}<button id="choose">Выбрать и получить разбор</button>`;
  return `<h2>DEBRIEF</h2><p>${esc(step.prompt)}</p><button id="close-step">Закрыть шаг</button>`;
}

async function openAttempt(step, hypothesis) { attemptId = (await post('/api/attempt', {lab_id: lab.id, step_id: step.id, hypothesis})).attempt_id; }
async function runner() {
  setActive('lab-runner');
  try { range = (await api('/api/range/health')).verdict; } catch (_) { range = 'не проверен'; }
  lab = await api('/api/lab/' + LAB_ID + (attemptId ? '?attempt_id=' + attemptId : ''));
  const step = lab.steps[phaseIndex];
  app.innerHTML = `<div class="lab-layout">${context()}<main class="lab-main">${header()}<section class="runner"><p class="phase">${esc(step.kind.toUpperCase())}</p>${phaseBody(step)}</section></main></div>`;
  bind(step);
}
function bind(step) {
  const copy = document.querySelector('#copy-command');
  if (copy) copy.onclick = async () => { try { await navigator.clipboard.writeText(step.command); copy.textContent = 'Скопировано'; } catch (_) { copy.textContent = 'Не удалось скопировать'; } };
  const revealCommand = document.querySelector('#reveal-command');
  if (revealCommand) revealCommand.onclick = async () => { lab = await api('/api/lab/' + LAB_ID + '?attempt_id=' + attemptId + '&reveal=command'); await runner(); };
  const toggleUnparsed = document.querySelector('#toggle-unparsed');
  if (toggleUnparsed) toggleUnparsed.onclick = () => { const lines = document.querySelector('#unparsed-lines'); const shown = !lines.hidden; lines.hidden = shown; toggleUnparsed.textContent = shown ? 'Показать' : 'Скрыть'; toggleUnparsed.setAttribute('aria-expanded', String(!shown)); };
  const save = document.querySelector('#save-hypothesis');
  if (save) save.onclick = async () => { try { await openAttempt(lab.steps[1], document.querySelector('#hypothesis').value); phaseIndex = 1; await runner(); } catch (error) { alert(error.message); } };
  const parse = document.querySelector('#parse-output');
  if (parse) parse.onclick = async () => { try { parsedFacts = await post('/api/attempt/' + attemptId + '/output', {raw: document.querySelector('#raw-output').value}); await openAttempt(lab.steps[2], 'Разобрать факты из собственного вывода.'); phaseIndex = 2; await runner(); } catch (error) { alert(error.message); } };
  const conclude = document.querySelector('#send-conclusion');
  if (conclude) conclude.onclick = async () => { try { mentorFeedback = await post('/api/attempt/' + attemptId + '/conclusion', {text: document.querySelector('#conclusion').value}); await openAttempt(lab.steps[3], 'Выбрать следующий шаг по подтверждённым фактам.'); phaseIndex = 3; await runner(); } catch (error) { alert(error.message); } };
  const choose = document.querySelector('#choose');
  if (choose) choose.onclick = async () => { const selected = document.querySelector('input[name=choice]:checked'); if (!selected) return; try { alert((await post('/api/attempt/' + attemptId + '/decision', {choice: selected.value})).why); await openAttempt(lab.steps[4], 'Закрепить принцип перечисления до оценки риска.'); phaseIndex = 4; await runner(); } catch (error) { alert(error.message); } };
  const close = document.querySelector('#close-step');
  if (close) close.onclick = async () => { try { await post('/api/attempt/' + attemptId + '/debrief', {verdict: 'completed'}); alert('Шаг закрыт.'); } catch (error) { alert(error.message); } };
  const hint = document.querySelector('#hint');
  if (hint) hint.onclick = async () => { try { document.querySelector('#help-result').textContent = (await api('/api/hint/' + lab.id + '/' + step.id + '?level=1&attempt_id=' + attemptId)).hint; } catch (error) { alert(error.message); } };
  const solution = document.querySelector('#solution');
  if (solution) solution.onclick = async () => { if (!confirm('Раскрыть solution? Это сохранится в попытке.')) return; try { document.querySelector('#help-result').textContent = (await post('/api/attempt/' + attemptId + '/solution', {confirm: true})).solution; } catch (error) { alert(error.message); } };
}
async function today() { setActive('today'); const data = await api('/api/today'); app.innerHTML = `<section class="page"><h1>Today</h1><div class="cards"><article><p>Продолжить лабу</p><h2>Service Enumeration</h2><p>Шаг: ${esc(data.step)}</p><button id="go">Продолжить</button></article><article><p>Повторить навык</p><h2>${data.review_due.length ? esc(data.review_due[0].skill_id) : 'Повторов пока нет'}</h2><p>Одна карточка повтора на сессию.</p></article></div></section>`; document.querySelector('#go').onclick = () => { location.hash = 'lab-runner'; }; }
async function rangePage() { setActive('range'); const data = await api('/api/range/health'); app.innerHTML = `<section class="page"><h1>Range</h1><p>Статус: ${esc(data.verdict)}</p><p>Приложение не выполняет сканирование, атаки или команды по цели.</p></section>`; }
function other(name) { setActive(name); app.innerHTML = `<section class="page"><h1>${esc(name)}</h1><p>Раздел планируется на следующих этапах.</p></section>`; }
async function notes() { setActive('notes'); const items = await api('/api/notes'); app.innerHTML = `<section class="page"><h1>Notes</h1>${items.map(item => `<article class="note"><h2>${esc(item.date)} · ${esc(item.goal)}</h2><p><b>Гипотеза:</b> ${esc(item.hypothesis)}</p><p><b>Команды:</b> ${esc(item.commands)}</p><p><b>Результаты:</b> ${esc(item.results)}</p><p><b>Вывод:</b> ${esc(item.conclusion)}</p><textarea data-note="${item.id}" placeholder="Один абзац от руки">${esc(item.manual_paragraph)}</textarea><button data-save-note="${item.id}">Сохранить абзац</button></article>`).join('') || '<p>Закройте шаг, чтобы появилась первая Field Note.</p>'}</section>`; document.querySelectorAll('[data-save-note]').forEach(button => button.onclick = async () => { const id = button.dataset.saveNote; await post('/api/note/' + id + '/paragraph', {paragraph: document.querySelector('[data-note="' + id + '"]').value}); button.textContent = 'Сохранено'; }); }
async function progress() { setActive('progress'); const data = await api('/api/progress'); const metric = data.closed_without_hints_2_3; app.innerHTML = `<section class="page"><h1>Progress</h1><p>Шагов закрыто без подсказок 2 и 3: ${metric.without_hints} из ${metric.closed}</p><table class="facts-table"><thead><tr><th>Навык</th><th>Уровень</th><th>Помощь</th><th>Повтор</th><th>Доступ</th></tr></thead><tbody>${data.skills.map(skill => `<tr><td>${esc(skill.title)}</td><td>${skill.level}</td><td>L${skill.assistance_level}</td><td>${esc(skill.next_review || 'нет')}</td><td>${skill.available ? 'доступен' : 'Сначала: ' + esc(skill.unlock_first.join(', '))}</td></tr>`).join('')}</tbody></table></section>`; }
function renderPlaybook(playbook) { if (playbookMode === 'field') return `<section class="playbook-field" data-render="field"><h2>${esc(playbook.title)}</h2>${playbook.phases.map(phase => `<article><h3>${esc(phase.title)}</h3><ul>${phase.checks.map(check => `<li>${esc(check)}</li>`).join('')}</ul></article>`).join('')}</section>`; const phase = playbook.phases[playbookPhase]; return `<section class="playbook-guided" data-render="guided"><p>Фаза ${playbookPhase + 1} из ${playbook.phases.length}</p><h2>${esc(phase.title)}</h2><p>Зачем: сначала проверьте эти наблюдаемые условия, затем отвечайте на вопрос.</p><ul>${phase.checks.map(check => `<li>${esc(check)}</li>`).join('')}</ul><p>${esc(phase.decision.question)}</p>${phase.decision.branches.map(branch => `<button data-next="${esc(branch.next)}">${esc(branch.answer)}</button>`).join('')}</section>`; }
async function playbooks() { setActive('playbooks'); const list = await api('/api/content/playbooks'); let selected = list[0]; app.innerHTML = `<section class="page"><h1>Playbooks</h1><select id="playbook-select">${list.map(book => `<option value="${esc(book.id)}">${esc(book.role)}: ${esc(book.title)}</option>`).join('')}</select><button id="guided-mode">Guided Mode</button><button id="field-mode">Field Mode</button><div id="playbook-render">${renderPlaybook(selected)}</div></section>`; const redraw = () => { document.querySelector('#playbook-render').innerHTML = renderPlaybook(selected); document.querySelectorAll('[data-next]').forEach(button => button.onclick = () => { playbookPhase = Math.max(0, selected.phases.findIndex(phase => phase.id === button.dataset.next)); redraw(); }); }; document.querySelector('#guided-mode').onclick = () => { playbookMode = 'guided'; redraw(); }; document.querySelector('#field-mode').onclick = () => { playbookMode = 'field'; redraw(); }; document.querySelector('#playbook-select').onchange = event => { selected = list.find(book => book.id === event.target.value); playbookPhase = 0; redraw(); }; redraw(); }
function route() { const name = location.hash.slice(1) || 'today'; if (name === 'today') today(); else if (name === 'lab-runner') runner(); else if (name === 'range') rangePage(); else if (name === 'notes') notes(); else if (name === 'progress') progress(); else if (name === 'playbooks') playbooks(); else other(name); }
window.addEventListener('hashchange', route);
route();
