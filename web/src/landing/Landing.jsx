import React, { useEffect, useRef, useState } from 'react'
import './landing.css'
import Constellation from './Constellation.jsx'
import Hero from './Hero.jsx'
import Problem from './Problem.jsx'
import Finding from './Finding.jsx'
import Ring from './Ring.jsx'
import Verifier from './Verifier.jsx'
import Close from './Close.jsx'
import { useDocumentProgress, useInView, useReducedMotion, useSectionProgress, useWebGL2 } from './hooks.js'

/* The landing surface.

   It sits in front of the console and does not touch it: every selector in
   landing.css is scoped under `.lp`, the console's stylesheet is untouched, and
   the only shared code is the data both read - metrics.json, cases.json,
   graph.json - plus the layout worker the network view already owned.

   The page is a document that scrolls. Nothing is hijacked, nothing is pinned
   away from the reader, and every scroll-linked value is read through a ref
   inside a frame loop rather than through React state, so a scroll costs a
   uniform write rather than a re-render of the tree. */

const NAV = [
  ['#act-window', 'The window'],
  ['#act-finding', 'The finding'],
  ['#act-ring', 'The ring'],
  ['#act-guardrail', 'The guardrail'],
]

/* One in-view gate per act, so entrances are authored per section rather than
   fired all at once when the page loads. */
function Act({ children, threshold = 0.16 }) {
  const [ref, inView] = useInView({ threshold })
  return (
    <div ref={ref} className={inView ? 'lp-in' : undefined}>
      {typeof children === 'function' ? children(inView) : children}
    </div>
  )
}

function Header({ shown }) {
  return (
    <div className={`lp-nav${shown ? ' lp-nav-on' : ''}`}>
      <a className="lp-nav-brand" href="#top">
        <span className="lp-deva">प्रमाण</span>
        <span>Praman</span>
      </a>
      <nav aria-label="Sections">
        {NAV.map(([href, label]) => (
          <a key={href} href={href}>{label}</a>
        ))}
      </nav>
      <a className="lp-btn lp-btn-primary lp-btn-sm" href="#/console">
        <span>Console</span>
        <span aria-hidden="true" className="lp-arrow">→</span>
      </a>
    </div>
  )
}

export default function Landing() {
  const reduced = useReducedMotion()
  const webgl2 = useWebGL2()
  const documentProgress = useDocumentProgress()
  const [live, setLive] = useState(false)
  const stageInvalidate = useRef(null)
  const [stageRef, stageProgress] = useSectionProgress(() => stageInvalidate.current?.())
  const [glRef, glActive] = useInView({ threshold: 0.05, once: false })
  const scrolled = useRef(0)
  const [navShown, setNavShown] = useState(false)

  // The hero counts up once, on the frame after mount, so the figures animate
  // in rather than being present before the type that introduces them.
  useEffect(() => {
    const id = requestAnimationFrame(() => setLive(true))
    return () => cancelAnimationFrame(id)
  }, [])

  useEffect(() => {
    const onScroll = () => {
      const past = window.scrollY > window.innerHeight * 0.72
      if (past !== (scrolled.current === 1)) {
        scrolled.current = past ? 1 : 0
        setNavShown(past)
      }
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <div className="lp" id="top">
      <span className="lp-progress" style={{ transform: `scaleX(${documentProgress})` }} aria-hidden="true" />
      <Header shown={navShown} />

      <div className="lp-stage" ref={stageRef}>
        <div className="lp-stage-gl" ref={glRef} aria-hidden="true">
          {webgl2 && (
            <Constellation
              progress={stageProgress}
              active={glActive}
              reduced={reduced}
              onInvalidate={stageInvalidate}
            />
          )}
          <span className="lp-vignette" />
        </div>

        {/* The hero's own entrance runs a frame after mount rather than on an
            observer: it is already on screen, and waiting for an intersection
            callback shows the reader an empty page first. */}
        <div className={live ? 'lp-in' : undefined}>
          <Hero live={live} />
        </div>
        <Act>{(inView) => <Problem live={inView} />}</Act>
      </div>

      <Act>{(inView) => <Finding live={inView} />}</Act>

      <Ring />

      <Verifier />

      <Act>
        <Close />
      </Act>
    </div>
  )
}
