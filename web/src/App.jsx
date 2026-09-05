import React, { useState } from 'react'
import cases from './cases.json'
import metrics from './metrics.json'
import Sidebar from './Sidebar.jsx'
import CaseQueue from './CaseQueue.jsx'
import CaseDetail from './CaseDetail.jsx'
import AuditTrail from './AuditTrail.jsx'
import Chamber from './chamber/Chamber.jsx'

/* The shell.

   The console used to open on one case, with no portfolio view at all. That call
   is reversed in ADR-013 and the reasoning is recorded there rather than
   deleted: opening on one case is better for the operator working a queue and
   worse for a reviewer, who has no case context to land in.

   Routing is a piece of state, not a router. Four destinations over twelve
   pre-computed cases does not need history integration, and a dependency added
   for a demo is a dependency the panel has to be told about. */

export default function App() {
  const [view, setView] = useState('queue')
  const [selected, setSelected] = useState(0)

  /* The one transition in the product. Descending into the network drops the
     ground away and the case chrome with it; everything else in this console is
     instant, which is what a surface operated against a deadline should feel
     like. The chamber takes the whole viewport, sidebar included, because a mode
     change that leaves the chrome behind is not a mode change. */
  if (view === 'chamber') {
    return <Chamber onExit={() => setView('queue')} exitLabel="← Case queue" />
  }

  return (
    <div className="app">
      <Sidebar view={view} onNavigate={setView} cases={cases} metrics={metrics} />
      <main className="sheet">
        {view === 'queue' && (
          <CaseQueue
            cases={cases}
            metrics={metrics}
            onOpenCase={(i) => { setSelected(i); setView('case') }}
          />
        )}
        {view === 'case' && (
          <CaseDetail
            c={cases[selected]}
            onBack={() => setView('queue')}
            onOpenChamber={() => setView('chamber')}
            onOpenAudit={() => setView('audit')}
          />
        )}
        {view === 'audit' && (
          <AuditTrail cases={cases} selected={selected} onSelect={setSelected} />
        )}
      </main>
    </div>
  )
}
