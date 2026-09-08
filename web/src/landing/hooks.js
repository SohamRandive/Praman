import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

/* Motion primitives for the landing surface.

   No animation library is used. Everything below is IntersectionObserver for
   entrances, one shared rAF for anything that has to run per frame, and
   scroll-position maths read through refs so that a scroll-linked value never
   forces a React render. A landing page that re-renders the tree on scroll
   janks on the first mid-range laptop it meets, and a janky 3D page is worse
   than no 3D page. */

/* One matchMedia listener, read by every component that has motion to suppress.
   Reduced motion kills autoplay and camera drift; it does NOT kill
   scroll-linked position, because the user is still the one scrolling. */
export function useReducedMotion() {
  const [reduced, setReduced] = useState(
    () => typeof window !== 'undefined'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const on = () => setReduced(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return reduced
}

/* Entrance gate. `once` is the default because an element that re-animates
   every time it re-enters reads as a screensaver rather than as authorship. */
export function useInView({ threshold = 0.2, rootMargin = '0px 0px -12% 0px', once = true } = {}) {
  const ref = useRef(null)
  const [inView, setInView] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    if (typeof IntersectionObserver === 'undefined') { setInView(true); return undefined }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true)
          if (once) io.disconnect()
        } else if (!once) setInView(false)
      },
      { threshold, rootMargin },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [threshold, rootMargin, once])
  return [ref, inView]
}

/* Scroll progress through one tall section that pins something inside itself:
   0 when the section's top reaches the top of the viewport, 1 when its bottom
   reaches the bottom. That is the span over which a `position: sticky` child is
   actually pinned, so a scene choreographed on it starts at its first frame and
   ends on its last, with nothing happening off screen.

   The value is written into a ref and read inside useFrame rather than held in
   state: a scroll must cost a uniform write, not a re-render of the tree.
   `onChange` exists so a canvas under frameloop="demand" can request exactly
   one repaint per scroll event. */
export function useSectionProgress(onChange) {
  const ref = useRef(null)
  const progress = useRef(0)
  const cb = useRef(onChange)
  cb.current = onChange

  useEffect(() => {
    let frame = 0
    const measure = () => {
      frame = 0
      const el = ref.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const top = rect.top + window.scrollY
      const span = rect.height - window.innerHeight
      // A section shorter than the viewport can never pin anything, so it falls
      // back to entering-from-below progress rather than dividing by zero.
      const p = span > 0
        ? (window.scrollY - top) / span
        : (window.innerHeight - rect.top) / (rect.height + window.innerHeight)
      progress.current = Math.min(1, Math.max(0, p))
      cb.current?.(progress.current)
    }
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(measure) }
    measure()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      if (frame) cancelAnimationFrame(frame)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [])

  return [ref, progress]
}

/* Whole-document progress, for the hairline at the top of the window. */
export function useDocumentProgress() {
  const [p, setP] = useState(0)
  useEffect(() => {
    let frame = 0
    const measure = () => {
      frame = 0
      const max = document.documentElement.scrollHeight - window.innerHeight
      setP(max <= 0 ? 0 : Math.min(1, Math.max(0, window.scrollY / max)))
    }
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(measure) }
    measure()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      if (frame) cancelAnimationFrame(frame)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [])
  return p
}

/* A number that counts to its final value once, on entry.

   The easing is the same expo-out the type entrances use, so a figure and the
   rule beneath it feel like one gesture. Under reduced motion the final value
   is rendered immediately - a count-up is decorative, and these are financial
   figures that must be readable the instant they are on screen. */
export function useCountUp(target, active, { duration = 1500, delay = 0 } = {}) {
  const reduced = useReducedMotion()
  const [value, setValue] = useState(reduced ? target : 0)

  /* THE RESTING STATE OF A NUMBER IS ITS TRUE VALUE.

     A count-up starts at zero, which means a counter that is never activated
     displays `0`. On this page that renders "₹0 net recovered" and "0.000 ring
     precision" - not a blank, not a spinner, but a plausible-looking WRONG
     measurement, in the house style, next to a label asserting it is real. The
     hero strip sits at the fold, so it is reachable by anyone whose observer
     misses, whose JS partially fails, or who simply does not scroll.

     So activation is treated as an enhancement with a deadline, and the
     deadline is unconditional - a `setTimeout`, not another frame callback.
     requestAnimationFrame is throttled in a background tab, paused under low
     power, and stalls outright in a headless capture, any of which freezes a
     count-up PART WAY and leaves a number that is wrong in a more convincing
     way than zero was. Whatever the animation does or fails to do, the figure
     converges to the measured value and stays there. The animation is allowed
     to be missed; the number is not allowed to be wrong. */
  useEffect(() => {
    if (reduced) { setValue(target); return undefined }

    let frame = 0
    let start = 0
    const tick = (now) => {
      if (!start) start = now
      const t = Math.min(1, Math.max(0, (now - start - delay) / duration))
      setValue(target * (1 - Math.pow(1 - t, 4)))
      if (t < 1) frame = requestAnimationFrame(tick)
      else setValue(target)          // land exactly, never on an eased approximation
    }
    if (active) frame = requestAnimationFrame(tick)

    // Fires whether or not the animation was started, and whether or not it
    // finished. This is the guarantee; the animation is only the flourish.
    const settle = setTimeout(() => setValue(target), delay + duration + 600)
    return () => { cancelAnimationFrame(frame); clearTimeout(settle) }
  }, [target, active, duration, delay, reduced])
  return value
}

/* A control that leans toward the cursor. Two pixels of pull is the whole
   effect: enough to feel responsive under the hand, not enough to look like a
   toy. Suppressed entirely under reduced motion and never used to convey
   anything, so a keyboard user loses nothing. */
export function useMagnetic(strength = 0.28) {
  const ref = useRef(null)
  const reduced = useReducedMotion()
  useEffect(() => {
    const el = ref.current
    if (!el || reduced) return undefined
    let frame = 0
    let tx = 0
    let ty = 0
    const apply = () => { frame = 0; el.style.transform = `translate(${tx}px, ${ty}px)` }
    const move = (e) => {
      const r = el.getBoundingClientRect()
      tx = (e.clientX - (r.left + r.width / 2)) * strength
      ty = (e.clientY - (r.top + r.height / 2)) * strength
      if (!frame) frame = requestAnimationFrame(apply)
    }
    const leave = () => { tx = 0; ty = 0; if (!frame) frame = requestAnimationFrame(apply) }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerleave', leave)
    return () => {
      if (frame) cancelAnimationFrame(frame)
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerleave', leave)
      el.style.transform = ''
    }
  }, [strength, reduced])
  return ref
}

/* Pointer position in clip space, as a ref. Feeds camera parallax; never a
   render. */
export function usePointer() {
  const pointer = useRef({ x: 0, y: 0 })
  useEffect(() => {
    const move = (e) => {
      pointer.current.x = (e.clientX / window.innerWidth) * 2 - 1
      pointer.current.y = (e.clientY / window.innerHeight) * 2 - 1
    }
    window.addEventListener('pointermove', move, { passive: true })
    return () => window.removeEventListener('pointermove', move)
  }, [])
  return pointer
}

/* Touch, or something like it. Orbit controls capture a one-finger drag, which
   on a phone is the same gesture as scrolling the page - so on a coarse pointer
   the graph is not made interactive at all, and the reader keeps their scroll. */
export function useCoarsePointer() {
  const [coarse, setCoarse] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(pointer: coarse)')
    const on = () => setCoarse(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return coarse
}

/* WebGL2 capability, checked once. The scenes have real fallbacks and this is
   what selects them; a landing page that renders a blank rectangle on a machine
   without a GPU has simply failed. */
export function useWebGL2() {
  return useMemo(() => {
    if (typeof document === 'undefined') return false
    try {
      return !!document.createElement('canvas').getContext('webgl2')
    } catch {
      return false
    }
  }, [])
}

/* Staggered entrance delay, in the inline custom property the stylesheet reads.
   Kept here so the cadence is one number in one place rather than a hundred
   hand-written delays. */
export function stagger(index, step = 90) {
  return { '--lp-delay': `${index * step}ms` }
}

export function useRafLoop(callback, active) {
  const cb = useRef(callback)
  cb.current = callback
  useEffect(() => {
    if (!active) return undefined
    let frame = requestAnimationFrame(function loop(t) {
      cb.current(t)
      frame = requestAnimationFrame(loop)
    })
    return () => cancelAnimationFrame(frame)
  }, [active])
}

export const clamp01 = (v) => Math.min(1, Math.max(0, v))
export const useStable = (fn) => useCallback(fn, [fn])
