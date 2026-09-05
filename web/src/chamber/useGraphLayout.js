import { useEffect, useRef, useState } from 'react'
import { useThree } from '@react-three/fiber'
import LayoutWorker from './layout.worker.js?worker&inline'

/* The worker is imported through Vite's `?worker&inline` form rather than
   `new URL('./layout.worker.js', import.meta.url)`.
   Both are bundler-resolved - the thing that actually matters, since a bare
   string path resolves in dev and breaks in production. The inline form is
   used because this console also ships as a single self-contained file, where
   a separately-emitted worker chunk would 404 and the chamber would silently
   fall back to 2D. Deployment is the binding constraint, so the worker travels
   with the bundle. */
export function useGraphLayout(nodes, links) {
  const [positions, setPositions] = useState(null)
  const [settled, setSettled] = useState(false)
  const workerRef = useRef()
  const invalidate = useThree((s) => s.invalidate)

  useEffect(() => {
    const worker = new LayoutWorker()
    workerRef.current = worker

    worker.onmessage = ({ data }) => {
      if (data.type === 'positions') {
        setPositions(data.positions)
        if (data.done) setSettled(true)
        invalidate() // required under frameloop="demand"
      }
    }

    worker.postMessage({
      type: 'init',
      nodes: nodes.map((n) => ({ id: n.id })),
      links: links.map((l) => ({ source: nodes[l.s].id, target: nodes[l.t].id })),
    })

    return () => {
      worker.postMessage({ type: 'dispose' })
      worker.terminate()
    }
  }, [nodes, links, invalidate])

  return { positions, settled }
}
