(function exposeLearningView(global) {
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }[char]));
  }

  function debriefSummary({lab, item, parsedFacts, mentorFeedback}) {
    const execute = (lab.steps || []).find(entry => entry.kind === 'execute') || {};
    const facts = parsedFacts && parsedFacts.facts ? parsedFacts.facts : [];
    const flagged = mentorFeedback && mentorFeedback.flagged_as_fact ? mentorFeedback.flagged_as_fact : [];
    return {
      command: execute.command || 'Команда не требовалась.',
      proven: facts.length ? facts.map(entry => entry.text).join('; ') : 'Открой предыдущий шаг и зафиксируй вывод команды.',
      caution: flagged.length ? 'Пока не доказано: ' + flagged.join('; ') + '.' : 'Не делай выводов, которых нет в сохранённых строках или в собственном заключении.',
      principle: item.solution || item.prompt,
    };
  }

  function resumeDecision(context) {
    return context.decision_feedback || null;
  }

  global.CyberRangeLearningView = {escapeHtml, debriefSummary, resumeDecision};
}(globalThis));
