import React, { useEffect, useMemo, useRef } from 'react'
import { Canvas, extend, useFrame, useThree } from '@react-three/fiber'
import { shaderMaterial } from '@react-three/drei'
import * as THREE from 'three'
import graph from '../graph.json'
import { usePointer } from './hooks.js'

/* The hero field: 869 points, one per entity, resolving out of noise.

   The points are not decoration and they are not random. Every one of them is a
   node in `graph.json` - a shared identity, device, address or instrument
   observed across merchants in the held-out window - carrying its real cluster
   and the detector's real verdict on that cluster. Scroll drives a single
   uniform from 0 to 1; at 0 the entities sit in an undifferentiated shell,
   which is what one merchant's view of one dispute looks like, and at 1 they
   fall into the 45 candidate clusters the network agent actually found.

   The whole resolve happens on the GPU. Position is mixed in the vertex shader
   from two static attributes, so the per-frame cost on the CPU is four uniform
   writes regardless of how many entities are on screen, and the edge lines
   reuse the identical mix so they track their endpoints exactly rather than
   being re-uploaded every frame. */

const PALETTE = {
  ink: new THREE.Color('#8A8F9A'),
  cleared: new THREE.Color('#6B7FC7'),
  flagged: new THREE.Color('#C4565A'),
}

/* Deterministic layout: the hero is identical on every load, which makes it a
   composition rather than a lottery. */
function mulberry32(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/* The shared displacement. Both the points and the edges compile this, so a
   line endpoint can never drift from the point it is drawn to. */
const MIX = /* glsl */ `
  attribute vec3 aChaos;
  attribute vec3 aOrder;
  attribute float aSeed;
  attribute float aTone;
  uniform float uTime;
  uniform float uResolve;
  varying float vTone;
  varying float vSettle;

  float easeInOutCubic(float t) {
    return t < 0.5 ? 4.0 * t * t * t : 1.0 - pow(-2.0 * t + 2.0, 3.0) / 2.0;
  }

  vec3 displaced() {
    // Each entity settles on its own schedule, so structure arrives as a sweep
    // across the field rather than as one synchronised snap.
    float stagger = aSeed * 0.45;
    float t = clamp((uResolve - stagger) / max(1.0 - stagger, 0.001), 0.0, 1.0);
    t = easeInOutCubic(t);
    vSettle = t;
    vec3 p = mix(aChaos, aOrder, t);
    // Noise breathes; structure barely moves. The drift is what makes the
    // resolve feel like settling rather than like a transition.
    float drift = mix(1.0, 0.10, t);
    p.x += sin(uTime * 0.21 + aSeed * 31.0) * 3.4 * drift;
    p.y += cos(uTime * 0.17 + aSeed * 19.0) * 3.0 * drift;
    p.z += sin(uTime * 0.13 + aSeed * 43.0) * 3.0 * drift;
    return p;
  }
`

const FieldPointsMaterial = shaderMaterial(
  { uTime: 0, uResolve: 0, uFade: 1, uSize: 6.6, uDpr: 1,
    uInk: PALETTE.ink, uCleared: PALETTE.cleared, uFlagged: PALETTE.flagged },
  /* glsl */ `
    ${MIX}
    uniform float uSize;
    uniform float uDpr;
    void main() {
      vTone = aTone;
      vec4 mv = modelViewMatrix * vec4(displaced(), 1.0);
      gl_Position = projectionMatrix * mv;
      // Noise is large and soft, structure is small and exact. The size ramp
      // runs backwards for that reason: an unresolved entity should read as an
      // unresolved entity, not as a smaller version of a finding.
      gl_PointSize = uSize * uDpr * mix(1.75, 0.85, vSettle) * (150.0 / max(-mv.z, 1.0));
    }
  `,
  /* glsl */ `
    uniform float uFade;
    uniform vec3 uInk;
    uniform vec3 uCleared;
    uniform vec3 uFlagged;
    varying float vTone;
    varying float vSettle;
    void main() {
      // A round sprite cut from the quad. No texture, no additive blend: the
      // page is a financial instrument, not a light show.
      vec2 d = gl_PointCoord - 0.5;
      float r2 = dot(d, d);
      if (r2 > 0.25) discard;
      // The sprite hardens as the entity settles: a diffuse blob while it is
      // noise, a defined point once it belongs to a component.
      float core = smoothstep(0.25, mix(0.115, 0.012, vSettle), r2);
      vec3 verdict = mix(uCleared, uFlagged, step(0.5, vTone));
      // Colour is earned by settling: an unresolved entity carries no verdict.
      vec3 c = mix(uInk, verdict, smoothstep(0.35, 0.95, vSettle));
      gl_FragColor = vec4(c, core * uFade * mix(0.62, 0.95, vSettle));
    }
  `,
)

const FieldLinesMaterial = shaderMaterial(
  { uTime: 0, uResolve: 0, uFade: 1,
    uCleared: PALETTE.cleared, uFlagged: PALETTE.flagged },
  /* glsl */ `
    ${MIX}
    void main() {
      vTone = aTone;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(displaced(), 1.0);
    }
  `,
  /* glsl */ `
    uniform float uFade;
    uniform vec3 uCleared;
    uniform vec3 uFlagged;
    varying float vTone;
    varying float vSettle;
    void main() {
      // Edges exist only once the entities they join have found each other.
      float a = smoothstep(0.55, 1.0, vSettle) * uFade * 0.4;
      if (a <= 0.001) discard;
      gl_FragColor = vec4(mix(uCleared, uFlagged, step(0.5, vTone)), a);
    }
  `,
)

extend({ FieldPointsMaterial, FieldLinesMaterial })

/* Cluster centres on a phyllotaxis spiral, members on a jittered shell around
   them. Cheap, deterministic, and it reads as a constellation rather than as a
   grid - which matters, because the honest claim is that the rings were found
   in a mess, not laid out in one. */
function buildField() {
  const rand = mulberry32(20260904)
  const nodes = graph.nodes
  const clusters = graph.clusters
  const centres = clusters.map((c, i) => {
    const angle = i * 2.399963
    const radius = 13 + 7.6 * Math.sqrt(i)
    return new THREE.Vector3(
      Math.cos(angle) * radius * 1.5,
      Math.sin(angle) * radius * 0.86,
      (rand() - 0.5) * 66,
    )
  })

  const count = nodes.length
  const chaos = new Float32Array(count * 3)
  const order = new Float32Array(count * 3)
  const seed = new Float32Array(count)
  const tone = new Float32Array(count)

  nodes.forEach((n, i) => {
    const centre = centres[n.cluster] ?? new THREE.Vector3()
    const members = clusters[n.cluster]?.members ?? 6
    const shell = 2.6 + 1.45 * Math.sqrt(members)
    // Uniform on a sphere, then squashed: a shell reads as an object, a solid
    // ball reads as a blob.
    const theta = rand() * Math.PI * 2
    const phi = Math.acos(2 * rand() - 1)
    const rr = shell * (0.55 + 0.45 * Math.cbrt(rand()))
    order[i * 3] = centre.x + rr * Math.sin(phi) * Math.cos(theta)
    order[i * 3 + 1] = centre.y + rr * Math.sin(phi) * Math.sin(theta) * 0.9
    order[i * 3 + 2] = centre.z + rr * Math.cos(phi) * 1.15

    const ct = rand() * Math.PI * 2
    const cp = Math.acos(2 * rand() - 1)
    const cr = 62 + rand() * 46
    chaos[i * 3] = cr * Math.sin(cp) * Math.cos(ct)
    chaos[i * 3 + 1] = cr * Math.sin(cp) * Math.sin(ct) * 0.62
    chaos[i * 3 + 2] = cr * Math.cos(cp) * 0.9

    seed[i] = rand()
    tone[i] = n.risk === 'flagged' ? 1 : 0
  })

  // Edges are drawn as one LineSegments: every link duplicated end to end, with
  // its endpoints' own attributes, so the shader mix moves both ends together.
  const links = graph.links
  const lc = links.length * 2
  const lChaos = new Float32Array(lc * 3)
  const lOrder = new Float32Array(lc * 3)
  const lSeed = new Float32Array(lc)
  const lTone = new Float32Array(lc)
  links.forEach((l, i) => {
    const ends = [l.s, l.t]
    ends.forEach((n, e) => {
      const w = i * 2 + e
      for (let k = 0; k < 3; k++) {
        lChaos[w * 3 + k] = chaos[n * 3 + k]
        lOrder[w * 3 + k] = order[n * 3 + k]
      }
      // Both ends take the source's schedule, so an edge never stretches
      // between one settled and one unsettled endpoint.
      lSeed[w] = seed[l.s]
      lTone[w] = tone[l.s]
    })
  })

  return { count, chaos, order, seed, tone, lc, lChaos, lOrder, lSeed, lTone }
}

function Field({ progress, reduced, onInvalidate }) {
  const field = useMemo(buildField, [])
  const points = useRef()
  const lines = useRef()
  const group = useRef()
  const pointer = usePointer()
  const dpr = useThree((s) => s.viewport.dpr)
  const camera = useThree((s) => s.camera)
  const invalidate = useThree((s) => s.invalidate)

  // Under reduced motion the canvas drops to demand and repaints only when the
  // reader scrolls, so the scene still tracks the page without a loop running
  // behind a picture that is not moving.
  useEffect(() => {
    if (onInvalidate) onInvalidate.current = invalidate
  }, [invalidate, onInvalidate])

  useFrame((state, delta) => {
    const p = progress.current
    // Three movements over one stage. The field resolves under the hero; it
    // then drops to a quarter of its weight so the act beneath it can be read
    // over the top of it rather than beside it; and it leaves before the next
    // section starts, so no two grounds are ever fighting.
    const resolve = THREE.MathUtils.smoothstep(p, 0.0, 0.34)
    const recede = THREE.MathUtils.lerp(1, 0.26, THREE.MathUtils.smoothstep(p, 0.36, 0.6))
    const fade = recede * (1 - THREE.MathUtils.smoothstep(p, 0.84, 1.0))
    const t = reduced ? 0 : state.clock.elapsedTime

    for (const ref of [points, lines]) {
      const m = ref.current
      if (!m) continue
      m.uniforms.uTime.value = t
      m.uniforms.uResolve.value = resolve
      m.uniforms.uFade.value = fade
    }
    if (points.current) points.current.uniforms.uDpr.value = dpr

    if (group.current) {
      // Parallax under the cursor, and a slow pull toward the field as the
      // structure arrives. Both are suppressed under reduced motion, where the
      // scene stays where scroll puts it and nothing moves on its own.
      const tx = reduced ? 0 : pointer.current.y * 0.09
      const ty = reduced ? 0 : pointer.current.x * 0.14
      const k = 1 - Math.pow(0.001, delta)
      group.current.rotation.x += (tx - group.current.rotation.x) * k
      group.current.rotation.y += (ty + resolve * 0.22 - group.current.rotation.y) * k
      // The structure settles to the right of the headline rather than behind
      // it. Type over the middle of a field is a legibility problem solved with
      // scrims; type beside it is a composition.
      group.current.position.x += (resolve * 26 - group.current.position.x) * k
    }
    const z = 178 - resolve * 28 + (reduced ? 0 : Math.sin(t * 0.13) * 5)
    camera.position.z += (z - camera.position.z) * (1 - Math.pow(0.004, delta))
  })

  // Attributes are static for the life of the page; only uniforms change.
  const attrs = (o, c, s, tn) => (
    <>
      <bufferAttribute attach="attributes-position" args={[o, 3]} />
      <bufferAttribute attach="attributes-aOrder" args={[o, 3]} />
      <bufferAttribute attach="attributes-aChaos" args={[c, 3]} />
      <bufferAttribute attach="attributes-aSeed" args={[s, 1]} />
      <bufferAttribute attach="attributes-aTone" args={[tn, 1]} />
    </>
  )

  return (
    <group ref={group}>
      <lineSegments raycast={null} frustumCulled={false}>
        <bufferGeometry>
          {attrs(field.lOrder, field.lChaos, field.lSeed, field.lTone)}
        </bufferGeometry>
        <fieldLinesMaterial
          key={FieldLinesMaterial.key}
          ref={lines}
          transparent
          depthWrite={false}
        />
      </lineSegments>
      <points raycast={null} frustumCulled={false}>
        <bufferGeometry>
          {attrs(field.order, field.chaos, field.seed, field.tone)}
        </bufferGeometry>
        <fieldPointsMaterial
          key={FieldPointsMaterial.key}
          ref={points}
          transparent
          depthWrite={false}
        />
      </points>
    </group>
  )
}

/* Frame budget: the canvas runs only while the stage it belongs to is on
   screen. Off screen it drops to demand and paints nothing, which is what keeps
   a scroll past the hero from costing a frame anywhere else on the page. */
export default function Constellation({ progress, active, reduced, onInvalidate }) {
  return (
    <Canvas
      frameloop={active && !reduced ? 'always' : 'demand'}
      dpr={[1, 1.75]}
      gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
      camera={{ position: [0, 0, 205], fov: 46, near: 1, far: 900 }}
      style={{ pointerEvents: 'none' }}
    >
      <Field progress={progress} reduced={reduced} onInvalidate={onInvalidate} />
    </Canvas>
  )
}
