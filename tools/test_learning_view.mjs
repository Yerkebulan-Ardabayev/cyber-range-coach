#!/usr/bin/env node
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const readJson = async name => JSON.parse(await readFile(join(root, 'content/labs', name), 'utf8'));
const viewContext = {};
vm.runInNewContext(await readFile(join(root, 'web/learning-view.js'), 'utf8'), viewContext);
const { debriefSummary, escapeHtml, resumeDecision } = viewContext.CyberRangeLearningView;

assert.equal(
  escapeHtml('<script>answer & "quoted"</script>'),
  '&lt;script&gt;answer &amp; &quot;quoted&quot;&lt;/script&gt;',
  'Terminal output must remain visible as text, not HTML',
);

const enumeration = await readJson('lab-1-2-service-enumeration.json');
const blue = await readJson('lab-1-7-blue-auth-events.json');
const debrief = lab => lab.steps.find(step => step.id === 'debrief');
const enumerationSummary = debriefSummary({
  lab: enumeration, item: debrief(enumeration),
  parsedFacts: {facts: [{text: '8080/tcp open http'}]},
  mentorFeedback: {flagged_as_fact: ['уязвимость без проверки']},
});
const blueSummary = debriefSummary({
  lab: blue, item: debrief(blue), parsedFacts: {facts: [{text: '401 source=192.168.10.20'}]},
  mentorFeedback: {flagged_as_fact: ['перебор без временного ряда']},
});
assert.equal(enumerationSummary.principle, debrief(enumeration).solution);
assert.equal(blueSummary.principle, debrief(blue).solution);
assert.match(blueSummary.principle, /контекст|ряду|401/i);
assert.doesNotMatch(blueSummary.principle, /перечисление.*оценк[аи] риск/i);
assert.match(blueSummary.caution, /перебор без временного ряда/i);

const feedback = {correct: true, why: 'Этот вариант сохраняет цель шага: временная шкала.', next_step: 'debrief'};
assert.deepEqual(resumeDecision({decision_feedback: feedback}), feedback);
assert.equal(resumeDecision({}), null);

const appSource = await readFile(join(root, 'web/app.js'), 'utf8');
assert.match(appSource, /debriefSummary\(\{lab, item, parsedFacts, mentorFeedback\}\)/);
assert.match(appSource, /resumeDecision\(context\)/);
assert.match(appSource, /function executionDiagnosis\(\)/);
assert.match(appSource, /РАЗБОР ОТВЕТА TERMINAL/);
assert.match(appSource, /diagnosis: output\.diagnosis \|\| null/);

const reachability = await readJson('lab-1-1-scope-reachability.json');
const execute = reachability.steps.find(step => step.id === 'execute');
assert.equal(execute.command, 'ping -c 4 192.168.10.10\nnc -vz 192.168.10.10 8080');
assert.match(execute.command_anatomy.join(' '), /nc -VZ/i);
assert.match(execute.command_anatomy.join(' '), /-v.*строчн|строчн.*-v/i);
assert.match(execute.command_anatomy.join(' '), /succeeded/);

const attackSurface = await readJson('lab-1-4-attack-surface.json');
const browserObservation = attackSurface.steps.find(step => step.id === 'execute');
assert.equal(browserObservation.interaction, 'browser-observation');
assert.equal(browserObservation.parser, 'log');
assert.ok(browserObservation.browser_steps.length >= 3);
assert.match(browserObservation.browser_steps.join(' '), /Option \+ Command \+ I/);
assert.match(appSource, /ДЕЙСТВИЕ.*ИЗ.*CHROME/);
assert.match(appSource, /Я сделал это, показать следующий шаг/);
assert.match(appSource, /Это не команда и не вывод Terminal/);
assert.match(appSource, /item\.interaction \? 'Сначала запиши наблюдаемые поля из Chrome или Coach\.'/);
assert.doesNotMatch(appSource, /item\.interaction \?[^:]*Terminal/);
assert.doesNotMatch(appSource, /Field Note создана.*терминального вывода/);
assert.doesNotMatch(appSource, /получишь ровно одну команду/);
assert.match(appSource, /actionNoun\(executeStep\)/);

const interactionExpectations = {
  'lab-1-1-scope-reachability.json': null,
  'lab-1-2-service-enumeration.json': null,
  'lab-1-3-http-protocol.json': null,
  'lab-1-4-attack-surface.json': 'browser-observation',
  'lab-1-5-authentication-boundary.json': 'browser-observation',
  'lab-1-6-access-control.json': 'browser-observation',
  'lab-1-7-blue-auth-events.json': 'guided-observation',
};
for (const [name, expectedInteraction] of Object.entries(interactionExpectations)) {
  const exercise = await readJson(name);
  const execution = exercise.steps.find(step => step.kind === 'execute');
  assert.equal(execution.interaction || null, expectedInteraction, name + ' must name the real place of action');
  if (expectedInteraction) {
    assert.equal(execution.parser, 'log', name + ' must accept a learner observation, not demand a raw terminal response');
    assert.ok(execution.browser_steps.length >= 3, name + ' must guide the learner one action at a time');
  }
}
console.log('LEARNING VIEW REGRESSION PASSED');
