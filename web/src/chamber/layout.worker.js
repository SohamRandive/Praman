/* Layout runs here, never on the main thread.
   Force-directed layout is CPU-bound and iterative; running it on the main
   thread destroys frame rate. Positions travel back as a transferable
   Float32Array - structured-cloning thousands of {x,y,z} objects per tick
   costs more than the layout itself. */

import {
  forceSimulation, forceLink, forceManyBody, forceCenter, forceX, forceY, forceZ,
} from 'd3-force-3d'

let sim = null

self.onmessage = ({ data }) => {
  if (data.type === 'init') {
    const { nodes, links, iterations = 300 } = data

    // The graph is a FOREST of ~45 disconnected components (each cluster is its
    // own connected component; solo claimants are excluded upstream). forceLink
    // only pulls nodes together WITHIN a component; forceManyBody repels every
    // node from every other node regardless of component; forceCenter only
    // re-centers the mean position once, it does not hold anything close to it.
    // With nothing pulling separate components back together, they fly apart
    // without bound - measured at a median 1,254 units from origin against a
    // camera 260 units away, i.e. almost the whole graph sits outside the
    // frustum. A gentle pull-to-origin on every axis is the standard fix (the
    // "gravity" term from the old d3.layout.force API, reintroduced here as
    // forceX/Y/Z(0)): it gives the repulsion something to push against, so the
    // layout settles at a bounded radius instead of expanding every tick.
    const GRAVITY = 0.15
    sim = forceSimulation(nodes, 3)
      .force('link', forceLink(links).id((d) => d.id).distance(26).strength(0.6))
      .force('charge', forceManyBody().strength(-110))
      .force('center', forceCenter())
      .force('x', forceX(0).strength(GRAVITY))
      .force('y', forceY(0).strength(GRAVITY))
      .force('z', forceZ(0).strength(GRAVITY))
      .stop()

    // Run headless in batches so the main thread can paint intermediate states.
    // Letting the simulation tick on its own timer inside a worker gives no
    // benefit, because nothing is painting between ticks.
    const batch = 12
    for (let i = 0; i < iterations; i += batch) {
      for (let j = 0; j < batch; j++) sim.tick()
      post(nodes, i + batch >= iterations)
    }
  }

  if (data.type === 'dispose') {
    sim?.stop()
    sim = null
  }
}

function post(nodes, done) {
  const positions = new Float32Array(nodes.length * 3)
  for (let i = 0; i < nodes.length; i++) {
    positions[i * 3] = nodes[i].x
    positions[i * 3 + 1] = nodes[i].y
    positions[i * 3 + 2] = nodes[i].z
  }
  self.postMessage({ type: 'positions', positions, done }, [positions.buffer])
}
