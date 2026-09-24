import { useState } from 'react'

import type { SimpleTheory } from '../types'
import { Eyebrow } from './Common'

// Text between backticks is a command or a path and is shown as code.
export function InlineCode({ text }: { text: string }) {
  return <>{text.split('`').map((part, index) => (index % 2 ? <code key={index}>{part}</code> : part))}</>
}

export function SimpleTheoryCard({ theory }: { theory: SimpleTheory }) {
  const [answerShown, setAnswerShown] = useState(false)
  return (
    <section className="paper-card simple-theory" aria-label="Просто о главном">
      <Eyebrow>ПРОСТО О ГЛАВНОМ</Eyebrow>
      <p className="large-copy simple-theory__analogy"><InlineCode text={theory.analogy} /></p>
      <ul className="simple-theory__steps">
        {theory.what_it_does.map((line) => <li key={line}><InlineCode text={line} /></li>)}
      </ul>
      <pre className="simple-theory__picture" aria-label="Схема">{theory.picture}</pre>
      {theory.words.length ? (
        <dl className="simple-theory__words">
          {theory.words.map((word) => (
            <div key={word.term}><dt>{word.term}</dt><dd><InlineCode text={word.meaning} /></dd></div>
          ))}
        </dl>
      ) : null}
      <div className="simple-theory__check">
        <strong>Проверь себя</strong>
        <p><InlineCode text={theory.check_question} /></p>
        {answerShown ? <p className="simple-theory__answer"><InlineCode text={theory.check_answer} /></p> : (
          <button className="button button--quiet" onClick={() => setAnswerShown(true)}>Показать ответ</button>
        )}
      </div>
    </section>
  )
}
