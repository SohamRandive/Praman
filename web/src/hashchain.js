/* Recompute the audit hash chain in the browser.

   The console is given the full record bodies rather than a boolean, so the
   reader can watch the chain be verified instead of being told it is intact. A
   claim of tamper-evidence that has to be taken on trust is not evidence of
   anything, and an integrity button that always reports success is a decoration
   with a lock icon on it. */

const GENESIS = '0'.repeat(64)

/* The canonical form must match Python's json.dumps(sort_keys=True) byte for
   byte, which uses ", " and ": " as separators. JSON.stringify uses neither, so
   it is built by hand. Get this wrong and every record fails, which is at least
   a loud failure rather than a quiet pass. */
export function canonical(body) {
  const keys = Object.keys(body).sort()
  return '{' + keys.map((k) => `${JSON.stringify(k)}: ${JSON.stringify(body[k])}`).join(', ') + '}'
}

export async function sha256(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

/* Returns one entry per broken record, empty when the chain holds. Both checks
   matter and they fail differently: `prev_hash` catches a record removed or
   reordered, the recomputed hash catches a record edited in place. */
export async function verifyChain(records) {
  const problems = []
  let prev = GENESIS
  for (const [i, r] of records.entries()) {
    if (r.prev_hash !== prev) {
      problems.push({ i, why: 'prev_hash does not match the record before it' })
    }
    const body = {
      ts: r.ts,
      actor: r.actor,
      event: r.event,
      inputs_hash: r.inputs_hash,
      outputs_hash: r.outputs_hash,
      prev_hash: r.prev_hash,
    }
    if ((await sha256(canonical(body))) !== r.record_hash) {
      problems.push({ i, why: 'contents do not match this record’s own hash' })
    }
    prev = r.record_hash
  }
  return problems
}
