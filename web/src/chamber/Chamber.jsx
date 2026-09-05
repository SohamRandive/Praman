import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { EffectComposer, Bloom, Selection, Select } from '@react-three/postprocessing'
import * as THREE from 'three'
import { useGraphLayout } from './useGraphLayout.js'
import Adjacency from './Adjacency.jsx'
import graph from '../graph.json'

/* The network chamber.

   This view is NOT justified by analytical value - network features are worth
   Rs 8,176 of Rs 94,04,449, and the panel is told that out loud. It exists
   because the ring finding is spatial and does not survive a table: 21 rings
   against 24 decoy groups whose burst-rate ranges overlap, where structure is
   identical and only tempo separates them. Overlapping communities also
   collapse into a hairball in 2D projection; depth and rotation separate them.

   Node KIND is carried by geometry, never by colour, so colour stays free to
   carry the detector's verdict and the view survives greyscale. */

const INK = '#08090c'
const RISK = { flagged: '#c4565a', cleared: '#6b7fc7' }
const KIND_GEOMETRY = [
  { name: 'identity', make: () => new THREE.SphereGeometry(1.7, 12, 12) },
  { name: 'device', make: () => new THREE.BoxGeometry(2.4, 2.4, 2.4) },
  { name: 'address', make: () => new THREE.OctahedronGeometry(1.9) },
  { name: 'instrument', make: () => new THREE.TetrahedronGeometry(2.1) },
]

function Nodes({ positions, nodes, kind, visible, onHover, onSelect, geometry }) {
  const meshRef = useRef()
  const dummy = useMemo(() => new THREE.Object3D(), [])
  const invalidate = useThree((s) => s.invalidate)
  const last = useRef(0)

  const members = useMemo(
    () => nodes.map((n, i) => [n, i]).filter(([n]) => n.kind === kind),
    [nodes, kind],
  )

  useLayoutEffect(() => {
    const mesh = meshRef.current
    if (!positions || !mesh) return
    const colour = new THREE.Color()
    members.forEach(([n, gi], i) => {
      const on = n.t <= visible
      dummy.position.set(positions[gi * 3], positions[gi * 3 + 1], positions[gi * 3 + 2])
      // Hidden by scale rather than by re-instancing: the buffer stays stable
      // and the scrubber costs one matrix write per node.
      dummy.scale.setScalar(on ? 1 : 0)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
      mesh.setColorAt(i, colour.set(RISK[n.risk]))
    })
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
    mesh.count = members.length
    invalidate()
  }, [positions, members, visible, dummy, invalidate])

  if (!members.length) return null

  return (
    <instancedMesh
      ref={meshRef}
      args={[geometry, undefined, members.length]}
      onPointerMove={(e) => {
        e.stopPropagation() // without it, every instance behind the cursor fires
        const now = performance.now()
        if (now - last.current < 30) return // raycasting thousands of instances is expensive
        last.current = now
        onHover(members[e.instanceId]?.[0] ?? null)
      }}
      onPointerOut={() => onHover(null)}
      onClick={(e) => {
        e.stopPropagation()
        onSelect(members[e.instanceId]?.[0] ?? null)
      }}
    >
      <meshStandardMaterial vertexColors roughness={0.55} metalness={0.1} />
    </instancedMesh>
  )
}

function Edges({ positions, links, visible }) {
  const geometryRef = useRef()
  const invalidate = useThree((s) => s.invalidate)

  useLayoutEffect(() => {
    if (!positions || !geometryRef.current) return
    const shown = links.filter((l) => l.when <= visible)
    const verts = new Float32Array(shown.length * 6)
    shown.forEach((l, i) => {
      const s = l.s * 3
      const t = l.t * 3
      verts.set(
        [positions[s], positions[s + 1], positions[s + 2],
         positions[t], positions[t + 1], positions[t + 2]],
        i * 6,
      )
    })
    geometryRef.current.setAttribute('position', new THREE.BufferAttribute(verts, 3))
    geometryRef.current.attributes.position.needsUpdate = true
    geometryRef.current.computeBoundingSphere()
    invalidate()
  }, [positions, links, visible, invalidate])

  // raycast disabled so only nodes are tested by the pointer
  return (
    <lineSegments raycast={null}>
      <bufferGeometry ref={geometryRef} />
      <lineBasicMaterial color="#4a5a7a" transparent opacity={0.22} />
    </lineSegments>
  )
}

/* The highlighted cluster is a SEPARATE object above the base edges rather than
   a mutation of the shared buffer. Isolating it is what lets selective bloom
   target the path without turning the whole scene into a screensaver. */
function HighlightPath({ positions, links, cluster, visible }) {
  const geometryRef = useRef()
  const invalidate = useThree((s) => s.invalidate)

  useLayoutEffect(() => {
    if (!positions || !geometryRef.current) return
    const shown = links.filter((l) => l.cluster === cluster && l.when <= visible)
    const verts = new Float32Array(shown.length * 6)
    shown.forEach((l, i) => {
      const s = l.s * 3
      const t = l.t * 3
      verts.set(
        [positions[s], positions[s + 1], positions[s + 2],
         positions[t], positions[t + 1], positions[t + 2]],
        i * 6,
      )
    })
    geometryRef.current.setAttribute('position', new THREE.BufferAttribute(verts, 3))
    geometryRef.current.attributes.position.needsUpdate = true
    geometryRef.current.computeBoundingSphere()
    invalidate()
  }, [positions, links, cluster, visible, invalidate])

  if (cluster == null) return null
  return (
    <lineSegments raycast={null}>
      <bufferGeometry ref={geometryRef} />
      <lineBasicMaterial color="#c9913c" transparent opacity={0.95} />
    </lineSegments>
  )
}

/* Frames the camera to whatever the layout actually settles to, once. A fixed
   camera distance is a number tuned against one graph's measured spread, and
   it goes stale the moment the corpus regenerates with a different node count
   or the gravity/charge balance above changes - which is exactly how the
   console shipped with 866 of 869 nodes sitting outside the frustum. Fitting
   at runtime from the real settled positions is the fix that cannot go stale. */
function FitCamera({ positions, settled }) {
  const camera = useThree((s) => s.camera)
  const invalidate = useThree((s) => s.invalidate)
  const done = useRef(false)

  useEffect(() => {
    if (!settled || done.current || !positions) return
    done.current = true

    let radius = 0
    for (let i = 0; i < positions.length; i += 3) {
      const d = Math.hypot(positions[i], positions[i + 1], positions[i + 2])
      if (d > radius) radius = d
    }
    if (radius <= 0) return

    // Distance such that `radius` fills 75% of the half-frustum at this fov,
    // leaving a margin rather than cropping the outermost nodes at the edge.
    const halfFov = (camera.fov * Math.PI) / 360
    const distance = radius / (Math.tan(halfFov) * 0.75)

    camera.position.set(0, 0, distance)
    camera.far = (distance + radius) * 1.5
    camera.updateProjectionMatrix()
    invalidate() // required under frameloop="demand"
  }, [positions, settled, camera, invalidate])

  return null
}

function Scene({ visible, cluster, onHover, onSelect, reduced }) {
  const { positions, settled } = useGraphLayout(graph.nodes, graph.links)
  const geometries = useMemo(() => KIND_GEOMETRY.map((k) => k.make()), [])

  // Disposed explicitly: R3F does not own geometries created outside the tree.
  useEffect(() => () => geometries.forEach((g) => g.dispose()), [geometries])

  return (
    <>
      <FitCamera positions={positions} settled={settled} />
      <ambientLight intensity={0.55} />
      <directionalLight position={[40, 60, 30]} intensity={1.1} />
      <Edges positions={positions} links={graph.links} visible={visible} />
      <Selection>
        <EffectComposer autoClear={false}>
          {/* One effect. Bloom on everything reads as a screensaver. */}
          <Bloom luminanceThreshold={0.35} intensity={0.7} mipmapBlur />
        </EffectComposer>
        <Select enabled>
          <HighlightPath positions={positions} links={graph.links}
                         cluster={cluster} visible={visible} />
        </Select>
      </Selection>
      {KIND_GEOMETRY.map((k, i) => (
        <Nodes key={k.name} positions={positions} nodes={graph.nodes} kind={i}
               visible={visible} onHover={onHover} onSelect={onSelect}
               geometry={geometries[i]} />
      ))}
      <OrbitControls
        makeDefault
        enableDamping={!reduced}
        autoRotate={false}
        onChange={undefined}
      />
    </>
  )
}

export default function Chamber({ onExit, exitLabel = '← Back to case' }) {
  const reduced = useMemo(
    () => typeof matchMedia === 'function'
      && matchMedia('(prefers-reduced-motion: reduce)').matches,
    [],
  )
  const webgl = useMemo(() => {
    try {
      return !!document.createElement('canvas').getContext('webgl2')
    } catch {
      return false
    }
  }, [])

  const [day, setDay] = useState(graph.window_days)
  const [playing, setPlaying] = useState(false)
  const [hover, setHover] = useState(null)
  const [selected, setSelected] = useState(null)
  const [force2D, setForce2D] = useState(false)

  const cluster = selected?.cluster ?? hover?.cluster ?? null
  const detail = graph.clusters.find((c) => c.i === cluster) || null

  useEffect(() => {
    if (!playing) return
    const id = setInterval(() => {
      setDay((d) => {
        if (d >= graph.window_days) { setPlaying(false); return graph.window_days }
        return Math.min(graph.window_days, d + graph.window_days / 120)
      })
    }, 40)
    return () => clearInterval(id)
  }, [playing])

  const flat = reduced || !webgl || force2D

  return (
    <div className="chamber">
      {/* Entering the chamber INVERTS the whole screen: the light document
          workspace goes, the sidebar goes with it, and what is left is the
          graph on near-black. That inversion is the one dramatic gesture in the
          product and it earns its place by signalling a genuine mode change,
          from document work to spatial work. Chrome here is the minimum needed
          to keep the view honest about what it is worth. */}
      <div className="chamber-bar">
        <button className="ghost" onClick={onExit}>{exitLabel}</button>
        <span className="chamber-title">Network chamber</span>
        <span className="k">{graph.split} split</span>
        <span className="v n">{graph.summary.rings}</span>
        <span className="k">rings ·</span>
        <span className="v n">{graph.summary.decoys}</span>
        <span className="k">decoys ·</span>
        <span className="v n" style={{ color: 'var(--oxblood)' }}>
          {graph.summary.false_rings}
        </span>
        <span className="k">false ·</span>
        <span className="v n" style={{ color: 'var(--ochre)' }}>
          {graph.summary.missed}
        </span>
        <span className="k">missed</span>
        <span className="k" style={{ marginLeft: 'auto', maxWidth: 380, textAlign: 'right' }}>
          network features are worth ₹8,176 of ₹94,04,449 — this view is a way to
          see the finding, not where the money is
        </span>
      </div>

      {flat ? (
        <Adjacency graph={graph} cluster={cluster} day={day}
                   onSelect={setSelected} reason={
                     reduced ? 'reduced motion' : !webgl ? 'no WebGL' : 'chosen'} />
      ) : (
        <Canvas
          frameloop="demand"
          camera={{ position: [0, 0, 260], fov: 50 }}
          gl={{ antialias: true }}
          style={{ background: INK }}
        >
          <Scene visible={day} cluster={cluster} onHover={setHover}
                 onSelect={setSelected} reduced={reduced} />
        </Canvas>
      )}

      {/* The scrubber is the single most valuable interaction here: you watch a
          ring assemble out of orders that looked unrelated when they happened.
          Built before any camera work. */}
      <div className="scrub">
        <button className="ghost" onClick={() => { setPlaying(!playing) }}>
          {playing ? 'Pause' : 'Replay formation'}
        </button>
        <input
          type="range" min={0} max={graph.window_days} step={0.5} value={day}
          onChange={(e) => { setPlaying(false); setDay(parseFloat(e.target.value)) }}
          aria-label="Day within the corpus window"
        />
        <span className="v n">day {day.toFixed(0)} / {graph.window_days.toFixed(0)}</span>
        <button className="ghost" onClick={() => setForce2D(!force2D)}>
          {flat ? '3D view' : '2D adjacency'}
        </button>
      </div>

      {detail && (
        <aside className="chamber-panel">
          <div className="kicker">
            {detail.flagged ? 'Flagged as a ring' : 'Not flagged'}
            {detail.flagged !== detail.abusive && ' · WRONG'}
          </div>
          <table className="audit">
            <tbody>
              <tr><td>profile</td><td className="a">{detail.profile || 'unclustered'}</td></tr>
              <tr><td>cohesion</td><td className="a">{detail.score} vs {graph.threshold}</td></tr>
              <tr><td>members</td><td className="a">{detail.members}</td></tr>
              <tr><td>disputes</td><td className="a">{detail.disputes}</td></tr>
              <tr><td>merchants</td><td className="a">{detail.merchants}</td></tr>
              <tr><td>burst</td><td className="a">{detail.per_day}/day over {detail.days}d</td></tr>
              <tr><td>ground truth</td><td className="a">{detail.abusive ? 'ring' : 'decoy'}</td></tr>
            </tbody>
          </table>
          <p className="note">
            {detail.flagged === detail.abusive
              ? 'The detector agrees with ground truth on this cluster.'
              : detail.abusive
                ? 'Missed. Burst rate sits below the threshold — a ring at household tempo is what this method cannot see.'
                : 'False ring. An innocent cluster accused: the worst error this system can make.'}
          </p>
        </aside>
      )}
    </div>
  )
}
