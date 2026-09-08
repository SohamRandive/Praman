import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import * as THREE from 'three'
import graph from '../graph.json'
import { useGraphLayout } from '../chamber/useGraphLayout.js'

/* Act 03 - the entity graph, with scroll wired to the clock.

   This is the console's own network export: 869 entities and 864 shared-entity
   edges observed across merchants in the held-out window, laid out by the same
   force simulation the console runs, in the same worker. Nothing is generated
   for the page.

   The choreography is the point. Scroll advances an observation clock across
   the 170.7-day window, and entities appear at the moment they were actually
   first seen. Clusters that assemble in a burst are the ones the detector
   flags; clusters that accrete slowly are households and shared devices. The
   claim being illustrated - that structure is identical between the two and
   only tempo separates them - is a claim the reader can watch happen.

   Node KIND is geometry, never colour, exactly as in the console: colour stays
   free to carry the verdict, and the scene survives greyscale. */

const RISK = { flagged: '#C4565A', cleared: '#6B7FC7' }
/* The console's chamber sizes these for a panel inside a shell. Here the scene
   is the whole viewport and is read from further back, so the same four shapes
   are cut larger; the ratios between them are unchanged, because that is what
   makes kind legible. */
const KINDS = [
  () => new THREE.SphereGeometry(2.6, 12, 12),
  () => new THREE.BoxGeometry(3.7, 3.7, 3.7),
  () => new THREE.OctahedronGeometry(2.9),
  () => new THREE.TetrahedronGeometry(3.2),
]

/* Per-instance colour needs a white per-vertex colour underneath it.

   `vertexColors` is what makes the fragment shader apply vColor at all, but the
   vertex shader computes `vColor *= color` before it multiplies in
   instanceColor - and a primitive geometry carries no `color` attribute, so the
   attribute falls back to the generic value (0, 0, 0) and every instance
   renders black no matter what setColorAt was given. A white attribute makes
   that multiply the identity it was assumed to be. This cost an hour and leaves
   no error in the console, which is the only reason it is written down. */
function withInstanceColour(geometry) {
  const count = geometry.getAttribute('position').count
  geometry.setAttribute(
    'color',
    new THREE.BufferAttribute(new Float32Array(count * 3).fill(1), 3),
  )
  return geometry
}

function Nodes({ positions, kind, geometry, clock }) {
  const mesh = useRef()
  const dummy = useMemo(() => new THREE.Object3D(), [])
  const members = useMemo(
    () => graph.nodes.map((n, i) => [n, i]).filter(([n]) => n.kind === kind),
    [kind],
  )
  // Current scale per instance, eased toward its target so an entity ignites
  // rather than pops. One Float32Array, mutated in place, no allocation in the
  // frame loop.
  const scale = useMemo(() => new Float32Array(members.length), [members.length])

  useLayoutEffect(() => {
    const m = mesh.current
    if (!m) return
    const colour = new THREE.Color()
    members.forEach(([n], i) => m.setColorAt(i, colour.set(RISK[n.risk])))
    if (m.instanceColor) m.instanceColor.needsUpdate = true
    m.count = members.length
  }, [members])

  useFrame((_, delta) => {
    const m = mesh.current
    if (!m || !positions) return
    const k = 1 - Math.pow(0.0015, Math.min(delta, 0.1))
    let dirty = false
    for (let i = 0; i < members.length; i++) {
      const [n, gi] = members[i]
      const target = n.t <= clock.current ? 1 : 0
      const next = scale[i] + (target - scale[i]) * k
      if (Math.abs(next - scale[i]) > 0.0005 || (target === 1 && scale[i] < 0.999)) dirty = true
      scale[i] = next
      dummy.position.set(positions[gi * 3], positions[gi * 3 + 1], positions[gi * 3 + 2])
      dummy.scale.setScalar(scale[i])
      dummy.updateMatrix()
      m.setMatrixAt(i, dummy.matrix)
    }
    if (dirty || m.userData.first !== false) {
      m.instanceMatrix.needsUpdate = true
      m.userData.first = false
    }
  })

  return (
    <instancedMesh
      ref={mesh}
      raycast={null}
      frustumCulled={false}
      args={[geometry, undefined, members.length]}
    >
      <meshBasicMaterial vertexColors fog />
    </instancedMesh>
  )
}

function Edges({ positions, clock }) {
  const geo = useRef()
  const shown = useRef(-1)
  const buffer = useMemo(() => new Float32Array(graph.links.length * 6), [])

  useFrame(() => {
    if (!positions || !geo.current) return
    const now = clock.current
    let count = 0
    for (const l of graph.links) {
      if (l.when > now) continue
      const s = l.s * 3
      const t = l.t * 3
      const w = count * 6
      buffer[w] = positions[s]; buffer[w + 1] = positions[s + 1]; buffer[w + 2] = positions[s + 2]
      buffer[w + 3] = positions[t]; buffer[w + 4] = positions[t + 1]; buffer[w + 5] = positions[t + 2]
      count++
    }
    // The attribute is written every frame while the layout is still moving,
    // but the draw range is what changes with the clock - so the geometry is
    // allocated once and never re-created.
    const attr = geo.current.getAttribute('position')
    if (!attr) {
      geo.current.setAttribute('position', new THREE.BufferAttribute(buffer, 3))
    } else {
      attr.needsUpdate = true
    }
    if (count !== shown.current) {
      geo.current.setDrawRange(0, count * 2)
      shown.current = count
    }
  })

  return (
    <lineSegments raycast={null} frustumCulled={false}>
      <bufferGeometry ref={geo} />
      <lineBasicMaterial color="#4A5A7A" transparent opacity={0.24} />
    </lineSegments>
  )
}

function Scene({ clock, reduced, interactive, onInvalidate }) {
  const { positions, settled } = useGraphLayout(graph.nodes, graph.links)
  const group = useRef()
  const camera = useThree((s) => s.camera)
  const invalidate = useThree((s) => s.invalidate)
  const geometries = useMemo(() => KINDS.map((make) => withInstanceColour(make())), [])
  const fog = useRef()
  const fitted = useRef(false)

  // Geometries are created outside the tree, so they are disposed by hand.
  useEffect(() => () => geometries.forEach((g) => g.dispose()), [geometries])
  useEffect(() => { onInvalidate.current = invalidate }, [invalidate, onInvalidate])

  // Frame the graph once the simulation settles: the extent of a force layout
  // is not known until it stops, and a hard-coded camera distance either crops
  // it or leaves it a speck.
  useEffect(() => {
    if (!settled || !positions || fitted.current) return
    // Fit on the 88th percentile radius, not the maximum. A force layout over a
    // forest of 45 components always throws a few stragglers far out, and
    // framing to those pushes the camera back until every node is sub-pixel -
    // which is exactly what "it renders but you cannot see it" looks like.
    const radii = []
    for (let i = 0; i < positions.length; i += 3) {
      radii.push(Math.hypot(positions[i], positions[i + 1], positions[i + 2]))
    }
    radii.sort((a, b) => a - b)
    const r = radii[Math.floor(radii.length * 0.92)] || 200
    const z = Math.min(900, Math.max(240, (r * 1.9) / Math.tan((camera.fov * Math.PI) / 360)))
    camera.position.setZ(z)
    camera.updateProjectionMatrix()
    // Fog is measured from the camera, so its band has to be derived from the
    // same fit. Hard-coded distances put the whole graph past the far plane and
    // render a black screen that looks exactly like a bug in the layout.
    if (fog.current) {
      fog.current.near = Math.max(1, z - r * 1.05)
      fog.current.far = z + r * 2.2
    }
    fitted.current = true
    invalidate()
  }, [settled, positions, camera, invalidate])

  useFrame((_, delta) => {
    if (group.current && !reduced) group.current.rotation.y += delta * 0.045
  })

  return (
    <>
      {/* Depth is carried by fog rather than by shading, and the node material
          is unlit for it. Two reasons, in order: a lit PBR surface renders the
          verdict colour through a light term, so the same oxblood reads as four
          different reds depending on which way a node happens to face - and the
          colour IS the finding here; and an unlit material is one shader
          compile and no light loop, which is what keeps 869 instances honest on
          a laptop. Distance then does the job shading would have done, pushing
          far components back into the ground instead of dimming them randomly. */}

      <fog ref={fog} attach="fog" args={['#08090C', 400, 1200]} />
      <group ref={group}>
        <Edges positions={positions} clock={clock} />
        {geometries.map((g, kind) => (
          <Nodes key={kind} positions={positions} kind={kind} geometry={g} clock={clock} />
        ))}
      </group>
      {/* Zoom is off because the wheel belongs to the page, and the controls are
          dropped entirely on a coarse pointer because a one-finger drag there is
          the reader's scroll gesture. */}
      {interactive && (
        <OrbitControls
          makeDefault
          enablePan={false}
          enableZoom={false}
          autoRotate={false}
          enableDamping={!reduced}
          rotateSpeed={0.55}
        />
      )}
      {!reduced && (
        <EffectComposer disableNormalPass>
          <Bloom intensity={0.42} luminanceThreshold={0.4} luminanceSmoothing={0.6} mipmapBlur />
        </EffectComposer>
      )}
    </>
  )
}

export default function RingCanvas({ clock, active, reduced, interactive, onInvalidate }) {
  return (
    <Canvas
      frameloop={active && !reduced ? 'always' : 'demand'}
      dpr={[1, 1.6]}
      gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
      camera={{ position: [0, 0, 340], fov: 45, near: 1, far: 3000 }}
      // The renderer sets touch-action: none by default, which would eat a
      // vertical swipe over a full-viewport canvas - i.e. the page would stop
      // scrolling on a phone the moment the graph filled the screen.
      style={{ touchAction: 'pan-y' }}
    >
      <Scene clock={clock} reduced={reduced} interactive={interactive} onInvalidate={onInvalidate} />
    </Canvas>
  )
}
