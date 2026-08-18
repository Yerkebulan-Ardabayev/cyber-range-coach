const app = document.querySelector('#app');
const { debriefSummary, escapeHtml, resumeDecision } = globalThis.CyberRangeLearningView;
const esc = escapeHtml;
let labId = null, lab = null, phaseIndex = 0, attemptId = null, rangeStatus = 'не проверен';
let parsedFacts = null, mentorFeedback = null, decisionFeedback = null, playbookMode = 'guided', playbookPhase = 0;

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Ошибка сервера');
  return data;
}
const post = (url, body) => api(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
const step = () => lab && lab.steps[phaseIndex];
const kindTitle = kind => ({think: 'Сначала сформулируй цель', execute: 'Выполни команду у себя', analyse: 'Разбери свой вывод', decide: 'Выбери следующий шаг', debrief: 'Закрепи результат'})[kind] || kind;
const factKinds = {port: 'порт', state: 'состояние', service: 'сервис', version: 'версия'};
const errorBlock = message => `<p class="form-error" role="alert">${esc(message)}</p>`;

function setActive(route) { document.querySelectorAll('.sidebar nav a').forEach(link => link.classList.toggle('active', link.getAttribute('href') === '#' + route)); }
function runnerContext() {
  return `<aside class="lab-context"><p class="eyebrow">ТЕКУЩАЯ МИССИЯ</p><h2>${esc(lab.objective)}</h2><p>${esc(lab.mission)}</p>
    <dl class="context-list"><dt>Цель</dt><dd>${esc(lab.target || 'свой учебный стенд')}</dd><dt>Гипотеза</dt><dd>${attemptId ? 'Есть. Она не пропадёт после обновления страницы.' : 'Пока нет. Сначала запиши, что хочешь узнать.'}</dd><dt>Полигон</dt><dd><span class="range-dot ${rangeStatus === 'ONLINE' ? 'online' : ''}"></span>${esc(rangeStatus)}</dd></dl>
    <p class="context-rule">Работай только с указанной собственной целью. Сайт не запускает команды и не отправляет запросы вместо тебя.</p><a class="text-link" href="#range">Проверить готовность стенда</a></aside>`;
}
function runnerHeader() {
  return `<header class="runner-header"><div><p class="eyebrow">${esc(lab.role || 'LAB')} · ШАГ ${phaseIndex + 1} ИЗ ${lab.steps.length}</p><h1>${esc(kindTitle(step().kind))}</h1></div><div class="step-rail" aria-label="Прогресс по шагам">${lab.steps.map((item, index) => `<span class="${index < phaseIndex ? 'done' : index === phaseIndex ? 'now' : ''}" title="${esc(kindTitle(item.kind))}">${index + 1}</span>`).join('')}</div></header>`;
}
function whyBox(item) { return item.why ? `<aside class="why-box"><strong>Зачем это сейчас</strong><p>${esc(item.why)}</p><strong>Проверь себя</strong><p>${esc(item.guiding_question || '')}</p></aside>` : ''; }
function help(item) {
  if (!item.hints && !item.solution) return '';
  return `<details class="help"><summary>Я застрял, нужна подсказка</summary><p>Подсказка не выполняет действие за тебя. Уровень 3 и готовый разбор сохраняются в попытке.</p><div class="help-actions"><button type="button" data-hint="1">Подсказка 1: направление</button><button type="button" data-hint="2">Подсказка 2: на что смотреть</button><button type="button" data-hint="3">Подсказка 3: почти ответ</button>${item.solution ? '<button type="button" class="danger-quiet" id="solution">Показать готовый разбор</button>' : ''}</div><div id="help-result" class="help-result"></div></details>`;
}
function executionDiagnosis() {
  const diagnosis = parsedFacts && parsedFacts.diagnosis;
  if (!diagnosis) return '';
  return `<section class="execution-diagnosis ${esc(diagnosis.level || 'warning')}"><p class="eyebrow">РАЗБОР ОТВЕТА TERMINAL</p><h3>${esc(diagnosis.title || 'Что произошло')}</h3><p>${esc(diagnosis.message || '')}</p><p><strong>Что делать дальше:</strong> ${esc(diagnosis.next || '')}</p></section>`;
}
function factsTable() {
  if (!parsedFacts) return `<div class="empty-state"><strong>Пока нет разобранных фактов</strong><span>Вставь полный вывод команды и нажми «Разобрать».</span></div>`;
  const facts = parsedFacts.facts || [];
  const rows = facts.length ? facts.map(fact => `<tr><td>${esc(fact.text)}</td><td>${esc(factKinds[fact.kind] || fact.kind || 'факт')}</td><td>${fact.line ? 'стр. ' + esc(fact.line) : 'из сохранённой попытки'}</td></tr>`).join('') : '<tr><td colspan="3">Парсер не нашёл структурированных фактов. Прочитай исходный вывод и не додумывай результат.</td></tr>';
  const leftovers = (parsedFacts.unparsed || []).map(item => `<li><span>стр. ${esc(item.line)}</span><code>${esc(item.text)}</code></li>`).join('');
  return `<section class="facts-panel"><div class="section-heading"><div><p class="eyebrow">ДОКАЗАНО ТЕКСТОМ ВЫВОДА</p><h2>Вот что команда действительно сообщила</h2></div><span class="fact-count">${facts.length} факт${facts.length === 1 ? '' : facts.length < 5 ? 'а' : 'ов'}</span></div>${executionDiagnosis()}<table class="facts-table"><thead><tr><th>Значение из вывода</th><th>Тип</th><th>Источник</th></tr></thead><tbody>${rows}</tbody></table>${(parsedFacts.unparsed || []).length ? `<details class="unparsed"><summary>Неразобранные строки: ${(parsedFacts.unparsed || []).length}</summary><p>Это не ошибка и не вывод. Система показала строки дословно, потому что не может честно превратить их в факт.</p><ul>${leftovers}</ul></details>` : ''}</section>`;
}
function feedbackPanel() {
  if (!mentorFeedback) return '';
  const list = values => values && values.length ? `<ul>${values.map(value => `<li>${esc(value)}</li>`).join('')}</ul>` : '<p>Ничего не отмечено.</p>';
  return `<section class="mentor-panel"><p class="eyebrow">РАЗБОР ТВОЕГО ТЕКСТА</p><h2>Не ответ за тебя, а проверка твоего вывода</h2><div class="mentor-grid"><div class="mentor-good"><h3>Ты назвал</h3>${list(mentorFeedback.named)}</div><div class="mentor-missing"><h3>Стоило добавить</h3>${list(mentorFeedback.missed)}</div><div class="mentor-careful"><h3>Пока не доказано</h3>${list(mentorFeedback.flagged_as_fact)}</div></div><p class="mentor-question"><strong>Следующий вопрос:</strong> ${esc(mentorFeedback.question)}</p></section>`;
}
function decisionPanel() {
  if (!decisionFeedback) return '';
  const ok = decisionFeedback.correct;
  const noFacts = !parsedFacts || !(parsedFacts.facts || []).length;
  const recovery = noFacts ? '<button class="danger-quiet" id="restart-lab">Начать эту лабораторную заново с новым выводом</button>' : '';
  return `<section class="decision-result ${ok ? 'correct' : 'incorrect'}"><strong>${ok ? 'Выбор опирается на подтверждённые факты' : 'Этот выбор нельзя принять'}</strong><p>${esc(decisionFeedback.why)}</p>${noFacts ? '<p>Сейчас нет ни одного подтверждённого факта. Не закрывай лабу с догадкой: подними стенд и начни этот шаг заново с реальным выводом.</p>' : ''}${ok ? '<button id="continue-debrief">Перейти к закреплению результата</button>' : '<button id="return-analysis">Выбрать другое действие</button>'}${recovery}</section>`;
}
function phaseBody(item) {
  if (item.kind === 'think') return `<p class="lead">${esc(item.prompt)}</p>${whyBox(item)}<label class="input-label" for="hypothesis">Моя гипотеза до команды</label><textarea id="hypothesis" placeholder="Например: хочу узнать, какие сервисы отвечают на этом одном учебном узле. Не пиши название уязвимости, если вывода ещё нет."></textarea><p class="input-hint">Пиши наблюдаемый результат, который ожидаешь увидеть. После сохранения появится ровно один следующий шаг.</p><button id="save-hypothesis">Сохранить гипотезу и перейти к команде</button><div id="form-error"></div>`;
  if (item.kind === 'execute') {
    const command = item.command ? `<div class="command-card"><div><p class="eyebrow">КОМАНДА ДЛЯ ТВОЕГО TERMINAL НА MAC</p><pre>${esc(item.command)}</pre></div><button type="button" id="copy-command">Копировать</button></div>` : `<button id="reveal-command">Показать команду для этой цели</button>`;
    return `<p class="lead">${esc(item.prompt)}</p>${whyBox(item)}${command}<details class="command-anatomy" open><summary>Разбор команды: что вводить и как читать результат</summary><ol>${(item.command_anatomy || []).map(part => `<li>${esc(part)}</li>`).join('')}</ol></details><label class="input-label" for="raw-output">Что напечатал Terminal</label><textarea id="raw-output" spellcheck="false" placeholder="Вставь полный текст от первой до последней строки. Если команда не дала результата или выдала ошибку, вставь это тоже."></textarea><p class="input-hint">Не пересказывай вывод. Вставь его как есть: наставник отдельно объяснит успех, отказ, тайм-аут или ошибку ключа.</p><button id="parse-output">Разобрать мой вывод</button><div id="form-error"></div>${help(item)}`;
  }
  if (item.kind === 'analyse') return `<p class="lead">${esc(item.prompt)}</p>${factsTable()}${whyBox(item)}<label class="input-label" for="conclusion">Мой вывод по этим строкам</label><textarea id="conclusion" placeholder="Напиши: 1) какой факт увидел, 2) в какой строке он виден, 3) чего вывод пока не доказывает."></textarea><p class="input-hint">Сначала твой текст. Затем наставник покажет, что ты назвал, пропустил или выдал за факт.</p><button id="send-conclusion">Отправить мой вывод на разбор</button><div id="form-error"></div>${help(item)}`;
  if (item.kind === 'decide') return `${feedbackPanel()}${factsTable()}<p class="lead">${esc(item.prompt)}</p>${whyBox(item)}<fieldset class="decision-options"><legend>Выбери только одно действие</legend>${(item.decision_options || []).map((option, index) => `<label><input type="radio" name="choice" value="${esc(option)}"> <span><b>${String.fromCharCode(65 + index)}.</b> ${esc(option)}</span></label>`).join('')}</fieldset><button id="choose">Проверить выбор</button><div id="form-error"></div>${decisionPanel()}`;
  const summary = debriefSummary({lab, item, parsedFacts, mentorFeedback});
  return `<p class="lead">${esc(item.prompt)}</p><section class="debrief-card"><p class="eyebrow">ИТОГ ЭТОЙ ПОПЫТКИ</p><h2>Что ты сделал и что теперь можешь утверждать</h2><div class="debrief-grid"><div><h3>Команда или действие</h3><p>${esc(summary.command)}</p></div><div><h3>Доказано</h3><p>${esc(summary.proven)}</p></div><div><h3>Граница вывода</h3><p>${esc(summary.caution)}</p></div><div><h3>Принцип этой лабы</h3><p>${esc(summary.principle)}</p></div></div></section><p class="input-hint">Закрытие создаст Field Note из твоей гипотезы, вывода и решения. Его можно открыть в Notes.</p><button id="close-step">Закрыть попытку и сохранить Field Note</button><div id="form-error"></div>`;
}
function hydrate(context) {
  if (!context) return;
  attemptId = context.attempt_id;
  const index = lab.steps.findIndex(entry => entry.id === context.step_id);
  if (index >= 0) phaseIndex = index;
  const output = context.attempts.find(entry => entry.raw_output);
  if (output) parsedFacts = {facts: output.facts || [], unparsed: [], diagnosis: output.diagnosis || null};
  mentorFeedback = context.mentor_feedback || null;
  decisionFeedback = resumeDecision(context);
}
async function loadLab() { lab = await api('/api/lab/' + labId + (attemptId ? '?attempt_id=' + attemptId : '')); }
async function runner() {
  setActive('lab-runner');
  try { rangeStatus = (await api('/api/range/health')).verdict; } catch (_) { rangeStatus = 'не проверен'; }
  if (!labId) { const current = await api('/api/today'); labId = current.lab; attemptId = current.resume ? current.resume.attempt_id : null; phaseIndex = 0; }
  await loadLab();
  if (attemptId) { const context = await api('/api/lab/' + labId + '/attempt-context?attempt_id=' + attemptId); await loadLab(); hydrate(context); }
  if (!step()) { app.innerHTML = `<section class="page">${errorBlock('У этой лабораторной нет доступного шага. Выбери другую на странице Today.')}</section>`; return; }
  app.innerHTML = `<div class="lab-layout">${runnerContext()}<main class="lab-main">${runnerHeader()}<section class="runner">${phaseBody(step())}</section></main></div>`;
  bindRunner(step());
}
function showError(error) { const node = document.querySelector('#form-error'); if (node) node.innerHTML = errorBlock(error.message || error); }
async function createAttempt(item, hypothesis) {
  const body = {lab_id: lab.id, step_id: item.id, hypothesis};
  if (attemptId) body.continue_attempt_id = attemptId;
  attemptId = (await post('/api/attempt', body)).attempt_id;
}
function bindHelp(item) {
  document.querySelectorAll('[data-hint]').forEach(button => button.onclick = async () => { try { const result = await api('/api/hint/' + lab.id + '/' + item.id + '?level=' + button.dataset.hint + '&attempt_id=' + attemptId); document.querySelector('#help-result').textContent = 'Подсказка ' + result.level + ': ' + result.hint; } catch (error) { showError(error); } });
  const solution = document.querySelector('#solution');
  if (solution) solution.onclick = async () => { if (!confirm('Показать готовый разбор этого шага? Это сохранится в прогрессе и не даст засчитать чистое прохождение.')) return; try { document.querySelector('#help-result').textContent = (await post('/api/attempt/' + attemptId + '/solution', {confirm: true})).solution; } catch (error) { showError(error); } };
}
function bindRunner(item) {
  const copy = document.querySelector('#copy-command');
  if (copy) copy.onclick = async () => { try { await navigator.clipboard.writeText(item.command); copy.textContent = 'Скопировано. Вставь в Terminal.'; } catch (_) { copy.textContent = 'Выдели команду и скопируй вручную.'; } };
  const reveal = document.querySelector('#reveal-command');
  if (reveal) reveal.onclick = async () => { try { lab = await api('/api/lab/' + labId + '?attempt_id=' + attemptId + '&reveal=command'); await runner(); } catch (error) { showError(error); } };
  const save = document.querySelector('#save-hypothesis');
  if (save) save.onclick = async () => { const hypothesis = document.querySelector('#hypothesis').value.trim(); if (!hypothesis) { showError('Сначала напиши гипотезу: что именно команда должна помочь тебе узнать.'); return; } try { await createAttempt(lab.steps[phaseIndex + 1], hypothesis); phaseIndex += 1; await runner(); } catch (error) { showError(error); } };
  const parse = document.querySelector('#parse-output');
  if (parse) parse.onclick = async () => { const raw = document.querySelector('#raw-output').value.trim(); if (!raw) { showError('Вставь весь фактический вывод Terminal. Если есть ошибка или пустой результат, вставь сообщение об этом.'); return; } try { parsedFacts = await post('/api/attempt/' + attemptId + '/output', {raw}); await createAttempt(lab.steps[phaseIndex + 1], 'Разобрать факты из сохранённого вывода команды.'); phaseIndex += 1; await runner(); } catch (error) { showError(error); } };
  const conclude = document.querySelector('#send-conclusion');
  if (conclude) conclude.onclick = async () => { const text = document.querySelector('#conclusion').value.trim(); if (!text) { showError('Сначала напиши свой вывод. Он нужен, чтобы наставник мог проверить именно твое рассуждение.'); return; } try { mentorFeedback = await post('/api/attempt/' + attemptId + '/conclusion', {text}); await createAttempt(lab.steps[phaseIndex + 1], 'Выбрать следующий шаг только по подтверждённым фактам.'); phaseIndex += 1; await runner(); } catch (error) { showError(error); } };
  const choose = document.querySelector('#choose');
  if (choose) choose.onclick = async () => { const selected = document.querySelector('input[name=choice]:checked'); if (!selected) { showError('Выбери один вариант. Затем сайт объяснит, какие факты поддерживают или не поддерживают его.'); return; } try { decisionFeedback = await post('/api/attempt/' + attemptId + '/decision', {choice: selected.value}); await runner(); } catch (error) { showError(error); } };
  const next = document.querySelector('#continue-debrief');
  if (next) next.onclick = async () => { try { await createAttempt(lab.steps[phaseIndex + 1], 'Закрепить: перечисление подтверждённых сервисов предшествует оценке риска.'); phaseIndex += 1; await runner(); } catch (error) { showError(error); } };
  const back = document.querySelector('#return-analysis');
  if (back) back.onclick = () => { decisionFeedback = null; runner(); };
  const restart = document.querySelector('#restart-lab');
  if (restart) restart.onclick = async () => {
    if (!confirm('Закрыть текущую незавершённую попытку как «начать заново»? Старый журнал останется в базе, но новая лабораторная начнётся с чистого шага.')) return;
    try {
      await post('/api/lab/' + lab.id + '/abandon', {attempt_id: attemptId});
      attemptId = null; phaseIndex = 0; parsedFacts = null; mentorFeedback = null; decisionFeedback = null;
      location.hash = '#today';
    } catch (error) { showError(error); }
  };
  const close = document.querySelector('#close-step');
  if (close) close.onclick = async () => { try { const result = await post('/api/attempt/' + attemptId + '/debrief', {verdict: 'completed'}); const learning = result.learning && result.learning.length ? ` Навык обновлён: уровень ${result.learning[0].level}, помощь L${result.learning[0].assistance_level}.` : ''; app.innerHTML = `<section class="page completion"><p class="eyebrow">ПОПЫТКА СОХРАНЕНА</p><h1>Лабораторная закрыта</h1><p>Field Note создана из твоей гипотезы, терминального вывода и собственного заключения.${esc(learning)}</p><div class="completion-actions"><button id="next-lab">Открыть следующий учебный шаг</button><a class="text-link" href="#notes">Посмотреть Field Note</a></div></section>`; document.querySelector('#next-lab').onclick = () => { attemptId = null; labId = null; phaseIndex = 0; parsedFacts = null; mentorFeedback = null; decisionFeedback = null; location.hash = '#today'; }; } catch (error) { showError(error); } };
  bindHelp(item);
}
async function today() {
  setActive('today');
  const [data, labs] = await Promise.all([api('/api/today'), api('/api/content/labs')]);
  const current = labs.find(item => item.id === data.lab);
  const catalog = data.resume ? `<section class="resume-lock"><h2>Сначала заверши эту попытку</h2><p>Новая лабораторная пока закрыта, чтобы её не смешать с уже сохранённым выводом и решением. После debrief откроется следующий шаг трека.</p></section>` : `<section class="lab-catalog"><h2>Маршрут трека</h2><p>Выбирай лабораторную только на своём стенде. Если навык закрыт в Progress, начни с указанного предыдущего навыка.</p>${labs.map(item => `<article><p class="eyebrow">${esc(item.role || '')}</p><h3>${esc(item.objective)}</h3><p>${esc(item.mission)}</p><button data-lab="${esc(item.id)}">Открыть эту лабораторную</button></article>`).join('')}</section>`;
  app.innerHTML = `<section class="page today-page"><p class="eyebrow">ОДНА ЯСНАЯ ТОЧКА ВХОДА</p><h1>Сегодня</h1><article class="today-card"><p class="eyebrow">${data.resume ? 'НЕЗАВЕРШЁННАЯ ПОПЫТКА' : 'СЛЕДУЮЩАЯ ЛАБОРАТОРНАЯ'}</p><h2>${esc(current ? current.objective : data.lab)}</h2><p><strong>Сейчас:</strong> ${esc(kindTitle(data.step))}. ${data.resume ? 'Сайт вернёт к тому же шагу и восстановит твои факты.' : 'Начни с цели, затем получишь ровно одну команду.'}</p><button id="go">${data.resume ? 'Продолжить с сохранённого места' : 'Начать лабораторную'}</button></article>${catalog}</section>`;
  document.querySelector('#go').onclick = () => { labId = data.lab; attemptId = data.resume ? data.resume.attempt_id : null; phaseIndex = 0; parsedFacts = null; mentorFeedback = null; decisionFeedback = null; location.hash = '#lab-runner'; };
  document.querySelectorAll('[data-lab]').forEach(button => button.onclick = () => { labId = button.dataset.lab; attemptId = null; phaseIndex = 0; parsedFacts = null; mentorFeedback = null; decisionFeedback = null; location.hash = '#lab-runner'; });
}
async function rangePage() {
  setActive('range'); const data = await api('/api/range/health');
  app.innerHTML = `<section class="page"><p class="eyebrow">ГОТОВНОСТЬ УЧЕБНОГО СТЕНДА</p><h1>Range: ${esc(data.verdict)}</h1><p>${data.verdict === 'ONLINE' ? 'Оба учебных сервиса отвечают. Ты можешь выполнить команду на Mac и вставить результат в лабу.' : 'Сайт не будет выдумывать вывод: сначала подними стенд или используй реальное сообщение Terminal как учебный материал.'}</p><div class="range-checks">${(data.checks || []).map(item => `<article class="range-check ${item.ok ? 'ok' : 'bad'}"><h3>${esc(item.name || ('Порт ' + item.port))}</h3><p>${esc(item.detail || '')}</p></article>`).join('')}</div><section class="diagnosis"><h2>Что проверить</h2>${(data.diagnosis || []).map(item => `<p class="${esc(item.level)}">${esc(item.message)}</p>`).join('')}</section><p class="context-rule">Эта проверка только сверяет доступность двух заранее заданных сервисов. Сканирование и атаки выполняет только человек на своей разрешённой цели.</p></section>`;
}
async function notes() {
  setActive('notes'); const items = await api('/api/notes');
  app.innerHTML = `<section class="page"><h1>Field Notes</h1><p>Твой журнал: что ожидал, какую команду выполнял, что получил и какой вывод сделал.</p>${items.map(item => `<article class="note"><h2>${esc(item.date)} · ${esc(item.goal)}</h2><dl><dt>Гипотеза</dt><dd>${esc(item.hypothesis)}</dd><dt>Команда</dt><dd><code>${esc(item.commands)}</code></dd><dt>Вывод Terminal</dt><dd><pre>${esc(item.results)}</pre></dd><dt>Твоё заключение</dt><dd>${esc(item.conclusion)}</dd></dl><label for="note-${item.id}">Личный итог одним абзацем</label><textarea id="note-${item.id}" data-note="${item.id}" placeholder="Что я сделаю иначе в следующий раз">${esc(item.manual_paragraph)}</textarea><button data-save-note="${item.id}">Сохранить мой итог</button></article>`).join('') || '<div class="empty-state"><strong>Пока нет закрытых попыток</strong><span>Одна закрытая лабораторная создаст здесь читаемую Field Note.</span></div>'}</section>`;
  document.querySelectorAll('[data-save-note]').forEach(button => button.onclick = async () => { const id = button.dataset.saveNote; try { await post('/api/note/' + id + '/paragraph', {paragraph: document.querySelector('[data-note="' + id + '"]').value}); button.textContent = 'Сохранено'; } catch (error) { button.insertAdjacentHTML('afterend', errorBlock(error.message)); } });
}
async function progress() { setActive('progress'); const data = await api('/api/progress'); app.innerHTML = `<section class="page"><h1>Прогресс</h1><p>Шагов закрыто без подсказок 2 и 3: ${data.closed_without_hints_2_3.without_hints} из ${data.closed_without_hints_2_3.closed}.</p><table class="facts-table"><thead><tr><th>Навык</th><th>Уровень</th><th>Помощь</th><th>Что открыть дальше</th></tr></thead><tbody>${data.skills.map(skill => `<tr><td>${esc(skill.title)}</td><td>${skill.level} / 5</td><td>L${skill.assistance_level}</td><td>${skill.available ? 'Можно практиковать' : 'Сначала: ' + esc(skill.unlock_first.join(', '))}</td></tr>`).join('')}</tbody></table><p class="input-hint">Уровень растёт только за прохождение без готового решения. Это не оценка личности, а запись о том, сколько поддержки тебе сейчас нужно.</p></section>`; }
function renderPlaybook(book) { if (playbookMode === 'field') return `<section class="playbook-field"><h2>${esc(book.title)}</h2>${book.phases.map(phase => `<article><h3>${esc(phase.title)}</h3><ul>${phase.checks.map(check => `<li>${esc(check)}</li>`).join('')}</ul></article>`).join('')}</section>`; const phase = book.phases[playbookPhase]; return `<section class="playbook-guided"><p class="eyebrow">ФАЗА ${playbookPhase + 1} ИЗ ${book.phases.length}</p><h2>${esc(phase.title)}</h2><p>Сначала проверь эти наблюдаемые условия, только затем выбирай ветку.</p><ul>${phase.checks.map(check => `<li>${esc(check)}</li>`).join('')}</ul><p><strong>${esc(phase.decision.question)}</strong></p>${phase.decision.branches.map(branch => `<button data-next="${esc(branch.next)}">${esc(branch.answer)}</button>`).join('')}</section>`; }
async function playbooks() {
  setActive('playbooks'); const books = await api('/api/content/playbooks'); let selected = books[0];
  app.innerHTML = `<section class="page"><h1>Playbooks</h1><p>Это отдельный тренажёр решения, не замена лабораторной с твоим выводом.</p><div class="toolbar"><label>Сценарий <select id="playbook-select">${books.map(book => `<option value="${esc(book.id)}">${esc(book.role)}: ${esc(book.title)}</option>`).join('')}</select></label><button id="guided-mode">Пошагово</button><button id="field-mode">Полный список</button></div><div id="playbook-render"></div></section>`;
  const redraw = () => { document.querySelector('#playbook-render').innerHTML = renderPlaybook(selected); document.querySelectorAll('[data-next]').forEach(button => button.onclick = () => { playbookPhase = Math.max(0, selected.phases.findIndex(phase => phase.id === button.dataset.next)); redraw(); }); };
  document.querySelector('#guided-mode').onclick = () => { playbookMode = 'guided'; redraw(); }; document.querySelector('#field-mode').onclick = () => { playbookMode = 'field'; redraw(); }; document.querySelector('#playbook-select').onchange = event => { selected = books.find(book => book.id === event.target.value); playbookPhase = 0; redraw(); }; redraw();
}
function reference() { setActive('reference'); app.innerHTML = `<section class="page"><h1>Reference</h1><p>Термины и команды открывай только когда в лабораторной увидел конкретный незнакомый элемент. Основной маршрут остаётся в Lab Runner.</p><a class="text-link" href="#lab-runner">Вернуться к учебному шагу</a></section>`; }
function route() { const name = location.hash.slice(1) || 'today'; if (name === 'today') today(); else if (name === 'lab-runner') runner(); else if (name === 'range') rangePage(); else if (name === 'notes') notes(); else if (name === 'progress') progress(); else if (name === 'playbooks') playbooks(); else if (name === 'reference') reference(); else today(); }
window.addEventListener('hashchange', route); route();
