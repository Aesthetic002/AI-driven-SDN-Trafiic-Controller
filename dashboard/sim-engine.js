/* ═══════════════════════════════════════════════════════════════════════════
   AI-SDN Simulation Engine  (sim-engine.js)
   ───────────────────────────────────────────────────────────────────────────
   A deterministic, in-browser network simulator that powers the Simulation Lab.

   DESIGN PRINCIPLE — "one source of truth":
     • A scenario injects FLOWS (ingress switch, traffic type, bitrate).
     • A routing POLICY assigns each flow exactly one PATH (an ordered node list).
     • Link utilization is COMPUTED by summing the bitrate of every flow whose
       chosen path traverses that link.
     • The renderer animates packets along those SAME chosen paths.
   => utilisation, link colours and packet animation are derived from the same
      routing result, so they can never disagree. This is what guarantees the
      "packet only appears where the data says it should" consistency.

   Pure logic only — no DOM access. The page (simulation.html) renders frames.
   ═══════════════════════════════════════════════════════════════════════════ */

const SIM = (function () {
  'use strict';

  /* ── Seeded PRNG (mulberry32) — reproducible runs, no flicker ───────────── */
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* ── Path colour palette (shared with renderer) ────────────────────────── */
  const PATH_COLORS = ['#3b82f6', '#8b5cf6', '#f97316', '#06b6d4', '#ec4899',
                       '#14b8a6', '#eab308', '#ef4444'];

  /* ── Traffic types ─────────────────────────────────────────────────────── */
  const TRAFFIC = {
    sensor:    { label: 'Sensor',    rate: 1,   priority: false, color: '#22c55e' },
    video:     { label: 'Video',     rate: 6,   priority: false, color: '#eab308' },
    elephant:  { label: 'Elephant',  rate: 18,  priority: false, color: '#f97316' },
    emergency: { label: 'Emergency', rate: 2,   priority: true,  color: '#ef4444' },
    actuator:  { label: 'Actuator',  rate: 2,   priority: true,  color: '#f59e0b' },
  };

  /* ───────────────────────────────────────────────────────────────────────
     TOPOLOGIES
     Each topology declares nodes (with layout coords in a 960×560 box),
     links (undirected, with capacity Mbps) and a getPaths(ingress) function
     returning the candidate routes from that ingress switch to the data
     centre. Every path is an ordered list of node ids; links are derived
     from consecutive pairs.
     ─────────────────────────────────────────────────────────────────────── */

  function L(a, b, cap) { return { id: linkId(a, b), a, b, cap }; }
  function linkId(a, b) { return [a, b].sort().join('~'); }

  const TOPOLOGIES = {

    /* 1 ── Full 3-Cluster (the project's real 7-switch net) ─────────────── */
    cluster3: {
      id: 'cluster3',
      name: 'Full 3-Cluster',
      tag: '7 switches · 5 paths',
      desc: 'The project\'s production topology. Three IoT clusters, two core ' +
            'switches, dual aggregation. Five distinct routes to the data centre.',
      ingress: ['s1', 's2', 's6'],
      ingressLabel: { s1: 'Cluster A', s2: 'Cluster B', s6: 'Cluster C' },
      nodes: [
        { id: 'hubA', type: 'cluster', x: 110, y: 54, label: 'Cluster A', sub: '4 hosts', cluster: 'A' },
        { id: 'hubB', type: 'cluster', x: 480, y: 54, label: 'Cluster B', sub: '4 hosts', cluster: 'B' },
        { id: 'hubC', type: 'cluster', x: 850, y: 54, label: 'Cluster C', sub: '4 hosts', cluster: 'C' },
        { id: 's1', type: 'edge', x: 110, y: 168, label: 's1', cluster: 'A' },
        { id: 's2', type: 'edge', x: 480, y: 168, label: 's2', cluster: 'B' },
        { id: 's6', type: 'edge', x: 850, y: 168, label: 's6', cluster: 'C' },
        { id: 's3', type: 'core', x: 360, y: 300, label: 's3', sub: 'low-latency' },
        { id: 's4', type: 'core', x: 620, y: 300, label: 's4', sub: 'high-BW' },
        { id: 's5', type: 'agg', x: 380, y: 422, label: 's5', sub: 'primary' },
        { id: 's7', type: 'agg', x: 600, y: 422, label: 's7', sub: 'secondary' },
        { id: 'DC', type: 'dc', x: 490, y: 520, label: 'Data Centre', sub: 'servers' },
      ],
      links: [
        L('hubA', 's1', 40), L('hubB', 's2', 40), L('hubC', 's6', 40),
        L('s1', 's3', 20), L('s1', 's4', 20),
        L('s2', 's3', 20), L('s2', 's4', 20),
        L('s6', 's3', 20), L('s6', 's4', 20),
        L('s3', 's4', 50),
        L('s3', 's5', 50), L('s4', 's5', 100),
        L('s3', 's7', 75), L('s4', 's7', 80),
        L('s5', 'DC', 1000), L('s7', 'DC', 1000),
      ],
      getPaths(ing) {
        const hub = { s1: 'hubA', s2: 'hubB', s6: 'hubC' }[ing];
        return [
          { key: 'A', label: 'Path A', nodes: [hub, ing, 's3', 's5', 'DC'] },
          { key: 'B', label: 'Path B', nodes: [hub, ing, 's4', 's5', 'DC'] },
          { key: 'C', label: 'Path C', nodes: [hub, ing, 's3', 's4', 's5', 'DC'] },
          { key: 'D', label: 'Path D', nodes: [hub, ing, 's3', 's7', 'DC'] },
          { key: 'E', label: 'Path E', nodes: [hub, ing, 's4', 's7', 'DC'] },
        ];
      },
    },

    /* 2 ── Compact (original 5-switch net) ──────────────────────────────── */
    compact: {
      id: 'compact',
      name: 'Compact Core',
      tag: '5 switches · 3 paths',
      desc: 'Two clusters, two core switches, single aggregation. The classic ' +
            'A / B / cross-link decision — easiest to read.',
      ingress: ['s1', 's2'],
      ingressLabel: { s1: 'Cluster A', s2: 'Cluster B' },
      nodes: [
        { id: 'hubA', type: 'cluster', x: 150, y: 60, label: 'Cluster A', sub: '4 hosts', cluster: 'A' },
        { id: 'hubB', type: 'cluster', x: 810, y: 60, label: 'Cluster B', sub: '4 hosts', cluster: 'B' },
        { id: 's1', type: 'edge', x: 230, y: 190, label: 's1', cluster: 'A' },
        { id: 's2', type: 'edge', x: 730, y: 190, label: 's2', cluster: 'B' },
        { id: 's3', type: 'core', x: 380, y: 320, label: 's3', sub: 'low-latency' },
        { id: 's4', type: 'core', x: 580, y: 320, label: 's4', sub: 'high-BW' },
        { id: 's5', type: 'agg', x: 480, y: 430, label: 's5', sub: 'aggregation' },
        { id: 'DC', type: 'dc', x: 480, y: 520, label: 'Data Centre', sub: 'servers' },
      ],
      links: [
        L('hubA', 's1', 40), L('hubB', 's2', 40),
        L('s1', 's3', 20), L('s1', 's4', 20),
        L('s2', 's3', 20), L('s2', 's4', 20),
        L('s3', 's4', 50),
        L('s3', 's5', 50), L('s4', 's5', 100),
        L('s5', 'DC', 1000),
      ],
      getPaths(ing) {
        const hub = ing === 's1' ? 'hubA' : 'hubB';
        return [
          { key: 'A', label: 'Path A', nodes: [hub, ing, 's3', 's5', 'DC'] },
          { key: 'B', label: 'Path B', nodes: [hub, ing, 's4', 's5', 'DC'] },
          { key: 'C', label: 'Path C', nodes: [hub, ing, 's3', 's4', 's5', 'DC'] },
        ];
      },
    },

    /* 3 ── Linear Chain (teaching: no path diversity) ───────────────────── */
    linear: {
      id: 'linear',
      name: 'Linear Chain',
      tag: '4 switches · 1 path',
      desc: 'A single line with no alternate route. Teaching case: when the ' +
            'topology offers no choice, AI routing cannot beat the baseline — ' +
            'path diversity is what makes DQN valuable.',
      ingress: ['s1'],
      ingressLabel: { s1: 'Cluster A' },
      nodes: [
        { id: 'hubA', type: 'cluster', x: 90, y: 280, label: 'Cluster A', sub: '4 hosts', cluster: 'A' },
        { id: 's1', type: 'edge', x: 250, y: 280, label: 's1' },
        { id: 's2', type: 'core', x: 420, y: 280, label: 's2' },
        { id: 's3', type: 'core', x: 590, y: 280, label: 's3' },
        { id: 's4', type: 'agg', x: 760, y: 280, label: 's4' },
        { id: 'DC', type: 'dc', x: 900, y: 280, label: 'Data Centre', sub: 'servers' },
      ],
      links: [
        L('hubA', 's1', 40),
        L('s1', 's2', 20), L('s2', 's3', 20), L('s3', 's4', 20),
        L('s4', 'DC', 1000),
      ],
      getPaths() {
        return [
          { key: 'P1', label: 'Only Path', nodes: ['hubA', 's1', 's2', 's3', 's4', 'DC'] },
        ];
      },
    },

    /* 4 ── Leaf-Spine (Clos) Fabric ─────────────────────────────────────── */
    leafspine: {
      id: 'leafspine',
      name: 'Leaf-Spine Fabric',
      tag: '5 switches · 3 ECMP paths',
      desc: 'A data-centre Clos fabric. Three equal-cost spine paths between ' +
            'leaves — the showcase for load-aware balancing vs blind ECMP.',
      ingress: ['l1'],
      ingressLabel: { l1: 'Cluster A' },
      nodes: [
        { id: 'hubA', type: 'cluster', x: 90, y: 290, label: 'Cluster A', sub: '8 hosts', cluster: 'A' },
        { id: 'l1', type: 'edge', x: 250, y: 290, label: 'leaf-1' },
        { id: 'sp1', type: 'core', x: 490, y: 130, label: 'spine-1' },
        { id: 'sp2', type: 'core', x: 490, y: 290, label: 'spine-2' },
        { id: 'sp3', type: 'core', x: 490, y: 450, label: 'spine-3' },
        { id: 'l2', type: 'agg', x: 730, y: 290, label: 'leaf-2' },
        { id: 'DC', type: 'dc', x: 890, y: 290, label: 'Data Centre', sub: 'servers' },
      ],
      links: [
        L('hubA', 'l1', 60),
        L('l1', 'sp1', 25), L('l1', 'sp2', 25), L('l1', 'sp3', 25),
        L('sp1', 'l2', 25), L('sp2', 'l2', 25), L('sp3', 'l2', 25),
        L('l2', 'DC', 1000),
      ],
      getPaths() {
        return [
          { key: 'S1', label: 'via spine-1', nodes: ['hubA', 'l1', 'sp1', 'l2', 'DC'] },
          { key: 'S2', label: 'via spine-2', nodes: ['hubA', 'l1', 'sp2', 'l2', 'DC'] },
          { key: 'S3', label: 'via spine-3', nodes: ['hubA', 'l1', 'sp3', 'l2', 'DC'] },
        ];
      },
    },
  };

  /* Pre-compute link maps + path link-lists + colours for each topology. */
  Object.values(TOPOLOGIES).forEach(topo => {
    topo.linkMap = {};
    topo.links.forEach(l => { topo.linkMap[l.id] = l; });
    topo.nodeMap = {};
    topo.nodes.forEach(n => { topo.nodeMap[n.id] = n; });
    // Build a colour index over the union of path keys across ingresses.
    const keys = [];
    topo.ingress.forEach(ing => topo.getPaths(ing).forEach(p => {
      if (!keys.includes(p.key)) keys.push(p.key);
    }));
    topo.pathColor = {};
    keys.forEach((k, i) => { topo.pathColor[k] = PATH_COLORS[i % PATH_COLORS.length]; });
    topo.pathKeys = keys;
  });

  function pathLinks(path) {
    const out = [];
    for (let i = 0; i < path.nodes.length - 1; i++) {
      out.push(linkId(path.nodes[i], path.nodes[i + 1]));
    }
    return out;
  }

  /* ───────────────────────────────────────────────────────────────────────
     SCENARIOS
     flowsAt(tick, topo, intensity) returns the list of ACTIVE flows for this
     tick. A flow = { id, ingress, type, rate }. Engine handles routing.
     `events` may down a link at a given tick (Link Failure scenario).
     ─────────────────────────────────────────────────────────────────────── */

  function mkFlows(spec) {
    // spec: [{ingress, type, n}] → expand into individual flows
    const flows = [];
    spec.forEach((s, gi) => {
      for (let i = 0; i < (s.n || 1); i++) {
        flows.push({
          id: `${s.ingress}-${s.type}-${gi}-${i}`,
          ingress: s.ingress, type: s.type,
          rate: TRAFFIC[s.type].rate * (s.mul || 1),
          priority: TRAFFIC[s.type].priority,
        });
      }
    });
    return flows;
  }

  const SCENARIOS = {

    calm: {
      id: 'calm', name: 'Calm', icon: '🌙',
      desc: 'Sensors only, light periodic readings. The network is far from ' +
            'congestion — DQN and baseline perform almost identically.',
      watch: 'Low utilisation everywhere. Notice DQN and baseline barely differ — ' +
             'there is no congestion to avoid yet.',
      length: 40,
      flowsAt(tick, topo) {
        return mkFlows(topo.ingress.map(ing => ({ ingress: ing, type: 'sensor', n: 2 })));
      },
    },

    rush: {
      id: 'rush', name: 'Rush Hour', icon: '🏙️',
      desc: 'Every cluster streams video simultaneously. Sustained moderate-high ' +
            'load — load balancing starts to matter.',
      watch: 'Baseline piles flows onto its favourite path and reddens it; DQN ' +
             'spreads load so no single link saturates.',
      length: 50,
      flowsAt(tick, topo) {
        const spec = [];
        topo.ingress.forEach(ing => {
          spec.push({ ingress: ing, type: 'sensor', n: 2 });
          spec.push({ ingress: ing, type: 'video', n: 2 });
        });
        return mkFlows(spec);
      },
    },

    elephant: {
      id: 'elephant', name: 'Elephant Flow', icon: '🐘',
      desc: 'A bulk transfer (huge TCP) saturates one path while normal IoT ' +
            'traffic continues. Classic congestion-avoidance test.',
      watch: 'The elephant pins one path near 100%. DQN routes the small flows ' +
             'AROUND the hot path; shortest-path baseline keeps stacking onto it.',
      length: 50,
      flowsAt(tick, topo) {
        const spec = [];
        topo.ingress.forEach((ing, i) => {
          spec.push({ ingress: ing, type: 'sensor', n: 2 });
          if (i === 0) spec.push({ ingress: ing, type: 'video', n: 1 });
        });
        // Elephant appears after a short warm-up and persists.
        if (tick >= 6) spec.push({ ingress: topo.ingress[0], type: 'elephant', n: 1 });
        return mkFlows(spec);
      },
    },

    emergency: {
      id: 'emergency', name: 'Emergency Burst', icon: '🚨',
      desc: 'A safety-critical priority flow appears amid heavy background ' +
            'traffic. Priority must take the lowest-latency route and never drop.',
      watch: 'When the emergency flow (red) appears, DQN immediately gives it the ' +
             'fastest clean path. Baseline treats it like any other flow.',
      length: 48,
      flowsAt(tick, topo) {
        const spec = [];
        topo.ingress.forEach(ing => {
          spec.push({ ingress: ing, type: 'sensor', n: 2 });
          spec.push({ ingress: ing, type: 'video', n: 1 });
        });
        if (tick >= 10 && tick <= 30) spec.push({ ingress: topo.ingress[0], type: 'emergency', n: 1 });
        return mkFlows(spec);
      },
    },

    failure: {
      id: 'failure', name: 'Link Failure', icon: '⚡',
      desc: 'A core link goes down mid-run. A reactive policy must re-route ' +
            'survivors onto healthy paths; a static one keeps hitting the dead link.',
      watch: 'At the failure (≈ tick 18) the downed link greys out. DQN re-routes ' +
             'instantly; shortest-path baseline loses the flows that depended on it.',
      length: 50,
      // Down the primary low-latency core link on each topology.
      failAt: 18,
      failLink(topo) {
        const cand = {
          cluster3: linkId('s3', 's5'),
          compact:  linkId('s3', 's5'),
          linear:   linkId('s2', 's3'),
          leafspine: linkId('sp1', 'l2'),
        };
        return cand[topo.id];
      },
      flowsAt(tick, topo) {
        const spec = [];
        topo.ingress.forEach(ing => {
          spec.push({ ingress: ing, type: 'sensor', n: 2 });
          spec.push({ ingress: ing, type: 'video', n: 1 });
        });
        return mkFlows(spec);
      },
    },

    cascade: {
      id: 'cascade', name: 'Cascading Overload', icon: '📈',
      desc: 'Load ramps steadily from calm to severe congestion. Watch how long ' +
            'each policy keeps the network healthy as pressure mounts.',
      watch: 'As the ramp climbs, baseline\'s busiest link hits red far sooner. ' +
             'DQN keeps the peak link cooler for longer by balancing.',
      length: 60,
      flowsAt(tick, topo, intensity) {
        const ramp = Math.min(1, tick / 40);          // 0 → 1 over 40 ticks
        const heavy = 1 + Math.round(ramp * 3);        // 1 → 4 video flows
        const spec = [];
        topo.ingress.forEach(ing => {
          spec.push({ ingress: ing, type: 'sensor', n: 2 });
          spec.push({ ingress: ing, type: 'video', n: heavy });
        });
        if (ramp > 0.6) spec.push({ ingress: topo.ingress[0], type: 'elephant', n: 1 });
        return mkFlows(spec);
      },
    },
  };

  /* ───────────────────────────────────────────────────────────────────────
     ROUTING POLICIES
     pick(paths, ctx) → chosen path object, where ctx carries current link
     loads, capacities, the flow, downed links and a per-policy memo.
     ─────────────────────────────────────────────────────────────────────── */

  function pathStats(path, ctx) {
    // bottleneck = highest projected utilisation across the path's links if the
    // flow were added; hops = link count (latency proxy); blocked if any link down.
    let bottleneck = 0, blocked = false, sumU = 0;
    const links = ctx.pathLinkCache[path._idx];
    for (const lid of links) {
      if (ctx.down[lid]) { blocked = true; }
      const cap = ctx.cap[lid] || 1;
      const proj = (ctx.load[lid] + ctx.flow.rate) / cap;
      bottleneck = Math.max(bottleneck, proj);
      sumU += (ctx.load[lid]) / cap;
    }
    return { bottleneck, blocked, hops: links.length, avgU: sumU / links.length };
  }

  const POLICIES = {

    /* The learned agent, faithfully emulated by its own reward objective:
       maximise (1−congestion)·0.4 + (1−latency)·0.3 + headroom·0.2 + fairness·0.1,
       with hard priority handling and failure-awareness. The real DQN is trained
       to maximise exactly this objective, so reward-greedy ≈ the converged net. */
    dqn: {
      id: 'dqn', label: 'DQN (load + latency aware)',
      pick(paths, ctx) {
        let best = null, bestScore = -Infinity;
        const maxHops = Math.max(...paths.map(p => ctx.pathLinkCache[p._idx].length));
        for (const p of paths) {
          const st = pathStats(p, ctx);
          if (st.blocked) continue;                    // never use a downed link
          const congestionR = 1 - Math.min(1, st.bottleneck);
          const latencyR    = 1 - (st.hops / maxHops);
          const headroomR   = 1 - st.avgU;
          let score = congestionR * 0.45 + latencyR * 0.25 +
                      headroomR * 0.15 + (1 - Math.abs(st.bottleneck - st.avgU)) * 0.15;
          if (ctx.flow.priority) score += latencyR * 0.6 + congestionR * 0.3; // rush priority onto fast clean path
          if (st.bottleneck > 1) score -= 2;            // avoid overflowing a link
          if (score > bestScore) { bestScore = score; best = p; }
        }
        return best || paths[0];
      },
    },

    /* STATIC policies below are NOT failure-aware: they route by a fixed rule
       over ALL paths, so when a link goes down they keep sending into it and
       lose traffic — exactly the weakness DQN's reactive routing fixes. */

    /* Always the fewest-hops route, load-blind. The most common classical
       default and the clearest contrast to DQN. */
    shortest_path: {
      id: 'shortest_path', label: 'Shortest Path (static)',
      pick(paths, ctx) {
        return paths.reduce((a, b) =>
          ctx.pathLinkCache[a._idx].length <= ctx.pathLinkCache[b._idx].length ? a : b);
      },
    },

    /* Hash the flow id to a path — spreads statically but ignores load + health. */
    ecmp_hash: {
      id: 'ecmp_hash', label: 'ECMP Hash (static spread)',
      pick(paths, ctx) {
        let h = 0; const s = ctx.flow.id;
        for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
        return paths[h % paths.length];
      },
    },

    /* Cycle through paths in order, blind to load + health. */
    round_robin: {
      id: 'round_robin', label: 'Round Robin (static)',
      pick(paths, ctx) {
        const i = (ctx.memo.rr = (ctx.memo.rr || 0) + 1);
        return paths[i % paths.length];
      },
    },

    /* Greedy least-loaded — load-aware but no latency/priority/fairness finesse. */
    least_utilized: {
      id: 'least_utilized', label: 'Least Utilised (greedy)',
      pick(paths, ctx) {
        let best = null, bestB = Infinity;
        for (const p of paths) {
          const st = pathStats(p, ctx);
          if (st.blocked) continue;
          if (st.bottleneck < bestB) { bestB = st.bottleneck; best = p; }
        }
        return best || paths[0];
      },
    },
  };

  const BASELINE_POLICY_IDS = ['shortest_path', 'ecmp_hash', 'round_robin', 'least_utilized'];

  /* ───────────────────────────────────────────────────────────────────────
     REWARD  (mirrors the project's weights: 0.4 lat / 0.3 rel / 0.2 thr / 0.1 fair)
     Computed from the realised link utilisations + delivered throughput so the
     number always matches what is on screen.
     ─────────────────────────────────────────────────────────────────────── */
  function rewardComponents(util, deliveredMbps, offeredMbps, utilsArr) {
    const maxU = utilsArr.length ? Math.max(...utilsArr) : 0;
    const avgU = utilsArr.length ? utilsArr.reduce((a, b) => a + b, 0) / utilsArr.length : 0;
    // Jain fairness over link utils
    const sum = utilsArr.reduce((a, b) => a + b, 0);
    const sum2 = utilsArr.reduce((a, b) => a + b * b, 0);
    const fairness = sum2 === 0 ? 1 : (sum * sum) / (utilsArr.length * sum2);
    const latency     = 1 - Math.min(1, maxU);                 // congested peak hurts latency
    const reliability = offeredMbps === 0 ? 1 : Math.min(1, deliveredMbps / offeredMbps);
    const throughput  = Math.min(1, deliveredMbps / Math.max(1, offeredMbps));
    return {
      latency, reliability, throughput, fairness,
      total: latency * 0.4 + reliability * 0.3 + throughput * 0.2 + fairness * 0.1,
    };
  }

  /* ───────────────────────────────────────────────────────────────────────
     REAL-MODEL BRIDGE  (cluster3 topology only)
     The trained DQN has a fixed 26-feature input and 6 path-actions, defined
     for the 7-switch topology. These map its action indices to path keys and
     build the exact 26-feature state vector the model expects, derived from
     the simulation's realised link utilisations (same numbers shown on screen).
     Feature indices MUST match constants.py STATE_FEATURES.
     ─────────────────────────────────────────────────────────────────────── */
  const STATE_DIM_SIM = 26;
  const SEQ_LEN = 10;
  const ACTION_KEYS = ['A', 'B', 'C', 'D', 'E', 'DROP'];   // action idx → cluster3 path key

  function buildStateVecCluster3(util, counts, anyPriority, prevAvg) {
    const g = (a, b) => util[linkId(a, b)] || 0;
    const f = new Array(STATE_DIM_SIM).fill(0);
    // 0–6: core link utilisations
    f[0] = g('s1', 's3'); f[1] = g('s1', 's4'); f[2] = g('s2', 's3'); f[3] = g('s2', 's4');
    f[4] = g('s3', 's5'); f[5] = g('s4', 's5'); f[6] = g('s3', 's4');
    // 7–9: active flows per path A/B/C  (normalised /20 like the collector)
    f[7] = Math.min(1, (counts.A || 0) / 20);
    f[8] = Math.min(1, (counts.B || 0) / 20);
    f[9] = Math.min(1, (counts.C || 0) / 20);
    // 10–15: loss / jitter / bytes — not modelled in the sandbox → 0 (in-distribution)
    // 16: time of day
    f[16] = (Date.now() / 1000 % 86400) / 86400;
    // 17: utilisation trend (Δ of mean util vs previous tick)
    const vals = Object.values(util);
    const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
    f[17] = Math.max(-1, Math.min(1, avg - (prevAvg || avg)));
    // 18: priority flag, 19: congestion flag
    f[18] = anyPriority ? 1 : 0;
    f[19] = (vals.length ? Math.max(...vals) : 0) > 0.8 ? 1 : 0;
    // 20–23: S6 + secondary-aggregation link utilisations
    f[20] = g('s6', 's3'); f[21] = g('s6', 's4'); f[22] = g('s3', 's7'); f[23] = g('s4', 's7');
    // 24–25: active flows per path D/E
    f[24] = Math.min(1, (counts.D || 0) / 20);
    f[25] = Math.min(1, (counts.E || 0) / 20);
    return f;
  }

  /* ───────────────────────────────────────────────────────────────────────
     ENGINE
     One Engine drives BOTH the active policy and a shadow policy on the same
     flows each tick, so DQN-vs-baseline comparison is always apples-to-apples.
     ─────────────────────────────────────────────────────────────────────── */
  class Engine {
    constructor({ topoId, scenarioId, policyId = 'dqn', baselineId = 'shortest_path',
                  intensity = 1, seed = 1234 }) {
      this.topo = TOPOLOGIES[topoId];
      this.scenario = SCENARIOS[scenarioId];
      this.policyId = policyId;
      this.baselineId = baselineId;
      this.intensity = intensity;
      this.rng = mulberry32(seed);
      this.tick = 0;
      this.cumDqn = 0; this.cumBase = 0;
      this.history = [];           // [{tick, dqnReward, baseReward}]
      this.memoA = {}; this.memoB = {};
      // cache path link-lists per ingress
      this._pathCache = {};
      // real-model mode: sticky per-flow assignments + rolling state buffer
      this.stickyDqn = {};         // flowId → pathKey (persists across ticks)
      this.stateBuf = [];          // rolling list of 26-feature state vectors
      this._prevAvg = 0;
    }

    _paths(ing) {
      if (!this._pathCache[ing]) {
        const ps = this.topo.getPaths(ing);
        ps.forEach((p, i) => { p._idx = i; p.color = this.topo.pathColor[p.key]; p._links = pathLinks(p); });
        this._pathCache[ing] = ps;
      }
      return this._pathCache[ing];
    }

    /* Route every flow under one policy → returns {assign:Map(flowId→path),
       load:{linkId→Mbps}, util:{linkId→0..1}, delivered, offered}. */
    _route(flows, policy, memo, down) {
      const cap = {}; this.topo.links.forEach(l => { cap[l.id] = l.cap; });
      const load = {}; this.topo.links.forEach(l => { load[l.id] = 0; });
      const assign = {};
      let delivered = 0, offered = 0;

      // Stable order so routing is deterministic; priority flows routed first.
      const ordered = flows.slice().sort((a, b) => (b.priority ? 1 : 0) - (a.priority ? 1 : 0));

      for (const flow of ordered) {
        offered += flow.rate;
        const paths = this._paths(flow.ingress);
        const pathLinkCache = paths.map(p => p._links);
        const ctx = { load, cap, down, flow, memo, pathLinkCache };
        const chosen = policy.pick(paths, ctx);
        assign[flow.id] = chosen;
        // add load; track delivered respecting residual capacity (loss if over)
        let bottleneckOver = false;
        chosen._links.forEach(lid => {
          load[lid] += flow.rate;
          if (down[lid]) bottleneckOver = true;
          if (load[lid] > cap[lid]) bottleneckOver = true;
        });
        if (!bottleneckOver) delivered += flow.rate;
        else delivered += flow.rate * 0.5;   // partial delivery under congestion/failure
      }

      const util = {};
      this.topo.links.forEach(l => {
        util[l.id] = down[l.id] ? 0 : Math.min(1.4, load[l.id] / l.cap);
      });
      return { assign, load, util, delivered, offered };
    }

    _downLinks() {
      const sc = this.scenario, down = {};
      if (sc.failLink && this.tick >= (sc.failAt || 1e9)) down[sc.failLink(this.topo)] = true;
      return down;
    }

    _flows() {
      return this.scenario.flowsAt(this.tick, this.topo, this.intensity)
        .map(f => ({ ...f, rate: f.rate * this.intensity }));
    }

    /* Assemble a frame from two routing results + bookkeeping. Shared by the
       emulated step() and the real-model stepReal(). */
    _assemble(dqnRes, baseRes, flows, down) {
      const topo = this.topo, sc = this.scenario;
      const dqnUtils  = topo.links.map(l => dqnRes.util[l.id]);
      const baseUtils = topo.links.map(l => baseRes.util[l.id]);
      const dqnR  = rewardComponents(dqnRes.util,  dqnRes.delivered,  dqnRes.offered,  dqnUtils);
      const baseR = rewardComponents(baseRes.util, baseRes.delivered, baseRes.offered, baseUtils);

      this.cumDqn += dqnR.total; this.cumBase += baseR.total;
      this.history.push({ tick: this.tick, dqnReward: this.cumDqn, baseReward: this.cumBase });
      if (this.history.length > 200) this.history.shift();

      const countByPath = (res) => {
        const c = {};
        Object.values(res.assign).forEach(p => { c[p.key] = (c[p.key] || 0) + 1; });
        return c;
      };

      return {
        tick: this.tick, length: sc.length, flows, down,
        dqn:  { ...dqnRes,  reward: dqnR,  counts: countByPath(dqnRes) },
        base: { ...baseRes, reward: baseR, counts: countByPath(baseRes) },
        cumDqn: this.cumDqn, cumBase: this.cumBase,
        history: this.history, topo, scenario: sc,
        policyId: this.policyId, baselineId: this.baselineId,
      };
    }

    /* Emulated step — both sides routed by JS policies. */
    step() {
      const down = this._downLinks();
      const flows = this._flows();
      const dqnRes  = this._route(flows, POLICIES[this.policyId], this.memoA, down);
      const baseRes = this._route(flows, POLICIES[this.baselineId], this.memoB, down);
      const frame = this._assemble(dqnRes, baseRes, flows, down);
      this.tick++;
      return frame;
    }

    /* ── Real-model mode (cluster3 only) ────────────────────────────────────
       The DQN side is routed by the ACTUAL model: `action` (0..5) is the path
       the trained network chose for the CURRENT network state. New flows this
       tick take that path; existing flows keep theirs (sticky) — mirroring how
       the real controller assigns a path per flow on arrival and lets balancing
       emerge across state windows. The baseline side uses its JS policy. */
    routeStickyDqn(flows, action, down) {
      const cap = {}, load = {}; this.topo.links.forEach(l => { cap[l.id] = l.cap; load[l.id] = 0; });
      const assign = {}; const newSticky = {}; let delivered = 0, offered = 0;
      const wantKey = ACTION_KEYS[action] || 'A';

      for (const flow of flows) {
        offered += flow.rate;
        const paths = this._paths(flow.ingress);
        const valid = p => p && !p._links.some(l => down[l]);
        // keep prior assignment if still healthy
        let chosen = null;
        const prevKey = this.stickyDqn[flow.id];
        if (prevKey && prevKey !== 'DROP') {
          const p = paths.find(x => x.key === prevKey);
          if (valid(p)) chosen = p;
        }
        if (!chosen) {
          if (wantKey === 'DROP') { newSticky[flow.id] = 'DROP'; continue; }  // dropped: no load, not delivered
          let p = paths.find(x => x.key === wantKey);
          if (!valid(p)) p = paths.find(valid) || paths[0];   // failover if model's choice is down
          chosen = p;
        }
        newSticky[flow.id] = chosen.key;
        assign[flow.id] = chosen;
        let over = false;
        chosen._links.forEach(l => { load[l] += flow.rate; if (down[l] || load[l] > cap[l]) over = true; });
        delivered += over ? flow.rate * 0.5 : flow.rate;
      }
      this.stickyDqn = newSticky;
      const util = {};
      this.topo.links.forEach(l => { util[l.id] = down[l.id] ? 0 : Math.min(1.4, load[l.id] / l.cap); });
      return { assign, load, util, delivered, offered };
    }

    /* Advance one tick using a real-model `action`. Returns the frame plus the
       10-step state sequence to feed back for the NEXT decision. */
    stepReal(action) {
      const down = this._downLinks();
      const flows = this._flows();
      const anyPrio = flows.some(f => f.priority);
      const dqnRes  = this.routeStickyDqn(flows, action, down);
      const baseRes = this._route(flows, POLICIES[this.baselineId], this.memoB, down);
      const frame = this._assemble(dqnRes, baseRes, flows, down);

      // build the state vector the model will see next tick (cluster3 layout)
      const counts = frame.dqn.counts;
      const sv = buildStateVecCluster3(dqnRes.util, counts, anyPrio, this._prevAvg);
      const utils = this.topo.links.map(l => dqnRes.util[l.id]);
      this._prevAvg = utils.reduce((a, b) => a + b, 0) / utils.length;
      this.stateBuf.push(sv);
      while (this.stateBuf.length > SEQ_LEN) this.stateBuf.shift();

      frame.stateSeq = this._paddedSeq();
      frame.usedAction = action;
      frame.usedKey = ACTION_KEYS[action];
      frame.real = true;
      this.tick++;
      return frame;
    }

    _paddedSeq() {
      const seq = this.stateBuf.slice();
      while (seq.length < SEQ_LEN) seq.unshift(new Array(STATE_DIM_SIM).fill(0));
      return seq;
    }

    /* Cold-start sequence (all-zero) for the first real decision. */
    initialSeq() { return Array.from({ length: SEQ_LEN }, () => new Array(STATE_DIM_SIM).fill(0)); }

    reset() {
      this.tick = 0; this.cumDqn = 0; this.cumBase = 0;
      this.history = []; this.memoA = {}; this.memoB = {};
      this.stickyDqn = {}; this.stateBuf = []; this._prevAvg = 0;
    }
  }

  /* ── Public API ────────────────────────────────────────────────────────── */
  return {
    TOPOLOGIES, SCENARIOS, POLICIES, TRAFFIC,
    BASELINE_POLICY_IDS, PATH_COLORS,
    Engine, linkId, pathLinks,
    ACTION_KEYS, SEQ_LEN, STATE_DIM_SIM, buildStateVecCluster3,
    REAL_TOPO: 'cluster3',   // the only topology the trained model understands
  };
})();

if (typeof window !== 'undefined') window.SIM = SIM;
