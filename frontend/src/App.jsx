import { useState, useRef, useEffect, useCallback } from 'react'
import { api } from './api/client.js'

/* ─────────────────────────────────────────────────────────────────────────
   CONSTANTS
───────────────────────────────────────────────────────────────────────── */
const DEFAULT_TOPICS = ['product vision', 'prioritization', 'metrics and analytics', 'stakeholder management', 'past launches']

const SCORE_META = {
  technical_depth:       { label: 'Technical Depth',       color: '#60a5fa' },
  communication_quality: { label: 'Communication',          color: '#34d399' },
  epistemic_calibration: { label: 'Epistemic Calibration',  color: '#fbbf24' },
  groundedness:          { label: 'Groundedness',           color: '#f87171' },
}

const BACKEND_URL = 'http://localhost:8000'

/* ─────────────────────────────────────────────────────────────────────────
   STYLES
───────────────────────────────────────────────────────────────────────── */
const STYLES = `
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700&family=Instrument+Serif:ital@0;1&family=DM+Mono:wght@400;500&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #0a0a0f;
  --bg2: #111118;
  --surface: #16161f;
  --surface2: #1e1e2a;
  --border: #2a2a3a;
  --border2: #363648;
  --text: #e8e6f0;
  --text2: #9896b0;
  --text3: #5a5870;
  --accent: #7c6af7;
  --accent2: #a594ff;
  --accent-glow: rgba(124,106,247,0.25);
  --green: #34d399;
  --green-bg: rgba(52,211,153,0.1);
  --amber: #fbbf24;
  --amber-bg: rgba(251,191,36,0.1);
  --red: #f87171;
  --red-bg: rgba(248,113,113,0.1);
  --blue: #60a5fa;
  --blue-bg: rgba(96,165,250,0.1);
  --mono: 'DM Mono', monospace;
  --serif: 'Instrument Serif', serif;
  --sans: 'Syne', sans-serif;
  --r: 12px;
  --r-sm: 8px;
}

body {
  font-family: var(--sans);
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}

/* ── SETUP ── */
.setup {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  background:
    radial-gradient(ellipse 60% 50% at 20% 40%, rgba(124,106,247,0.12) 0%, transparent 60%),
    radial-gradient(ellipse 40% 60% at 80% 70%, rgba(96,165,250,0.08) 0%, transparent 60%),
    var(--bg);
}

.setup-inner {
  max-width: 500px;
  width: 100%;
}

.logo-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 2.5rem;
}

.logo-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 12px var(--accent);
}

.logo-text {
  font-family: var(--mono);
  font-size: 0.72rem;
  letter-spacing: 0.15em;
  color: var(--text3);
  text-transform: uppercase;
}

h1 {
  font-family: var(--serif);
  font-size: 2.8rem;
  line-height: 1.1;
  color: var(--text);
  margin-bottom: 0.5rem;
  font-weight: 400;
}

h1 em {
  font-style: italic;
  color: var(--accent2);
}

.subtitle {
  font-size: 0.85rem;
  color: var(--text2);
  line-height: 1.7;
  margin-bottom: 2.5rem;
}

.form-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 2rem;
}

.fg { margin-bottom: 1.1rem; }

.lbl {
  display: block;
  font-family: var(--mono);
  font-size: 0.68rem;
  letter-spacing: 0.1em;
  color: var(--text3);
  text-transform: uppercase;
  margin-bottom: 0.4rem;
}

.inp {
  width: 100%;
  padding: 0.6rem 0.9rem;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  font-family: var(--sans);
  font-size: 0.88rem;
  color: var(--text);
  outline: none;
  transition: border-color 0.2s;
}
.inp:focus { border-color: var(--accent); }

textarea.inp { resize: vertical; min-height: 60px; }

.row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.9rem; }

.pills { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 0.4rem; }

.pill {
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 0.75rem;
  font-family: var(--mono);
  cursor: pointer;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text2);
  transition: all 0.15s;
  user-select: none;
}
.pill.on {
  background: var(--accent);
  border-color: var(--accent);
  color: white;
  box-shadow: 0 0 12px var(--accent-glow);
}


.btn-primary {
  width: 100%;
  padding: 0.85rem;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: var(--r-sm);
  font-family: var(--sans);
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  margin-top: 0.5rem;
  transition: all 0.2s;
  letter-spacing: 0.02em;
  box-shadow: 0 0 20px var(--accent-glow);
}
.btn-primary:hover { opacity: 0.9; box-shadow: 0 0 30px var(--accent-glow); }
.btn-primary:disabled { opacity: 0.35; cursor: not-allowed; box-shadow: none; }

.err {
  background: var(--red-bg);
  border: 1px solid rgba(248,113,113,0.3);
  border-radius: var(--r-sm);
  padding: 0.7rem 0.9rem;
  font-size: 0.82rem;
  color: var(--red);
  margin-bottom: 1rem;
}

/* ── INTERVIEW ── */
.interview {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg);
}

.iheader {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0.8rem 1.5rem;
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-shrink: 0;
}

.hlogo { display: flex; align-items: center; gap: 8px; }
.hlogo-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 8px var(--accent); }
.hrole { font-size: 0.83rem; font-weight: 600; color: var(--text); }
.hmeta { font-size: 0.7rem; color: var(--text3); font-family: var(--mono); }

.badges { display: flex; gap: 6px; margin-left: auto; align-items: center; }
.badge {
  padding: 2px 9px;
  border-radius: 20px;
  font-size: 0.68rem;
  font-family: var(--mono);
  font-weight: 500;
  letter-spacing: 0.04em;
}
.b-topic { background: var(--blue-bg); color: var(--blue); border: 1px solid rgba(96,165,250,0.2); }
.b-turn  { background: var(--surface2); color: var(--text2); border: 1px solid var(--border); }
.b-phase { background: var(--green-bg); color: var(--green); border: 1px solid rgba(52,211,153,0.2); }

/* AI speaking indicator in header */
.speaking-badge {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 20px;
  background: rgba(124,106,247,0.15);
  border: 1px solid rgba(124,106,247,0.3);
  font-family: var(--mono);
  font-size: 0.68rem;
  color: var(--accent2);
}
.speaking-bars {
  display: flex;
  gap: 2px;
  align-items: center;
}
.speaking-bar {
  width: 2px;
  background: var(--accent2);
  border-radius: 2px;
  animation: soundbar 0.8s ease-in-out infinite;
}
.speaking-bar:nth-child(1) { height: 6px; animation-delay: 0s; }
.speaking-bar:nth-child(2) { height: 10px; animation-delay: 0.15s; }
.speaking-bar:nth-child(3) { height: 7px; animation-delay: 0.3s; }
.speaking-bar:nth-child(4) { height: 12px; animation-delay: 0.1s; }
.speaking-bar:nth-child(5) { height: 5px; animation-delay: 0.25s; }
@keyframes soundbar { 0%,100% { transform: scaleY(0.4); } 50% { transform: scaleY(1); } }

/* Chat area */
.chat-wrap { display: flex; flex: 1; overflow: hidden; }

.chat {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.chat::-webkit-scrollbar { width: 4px; }
.chat::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 4px; }

.mrow { display: flex; gap: 10px; max-width: 680px; }
.mrow.ai { align-self: flex-start; }
.mrow.you { align-self: flex-end; flex-direction: row-reverse; }

.avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.68rem;
  font-family: var(--mono);
  font-weight: 500;
  letter-spacing: 0.05em;
}
.av-ai {
  background: linear-gradient(135deg, var(--accent), #a594ff);
  color: white;
  box-shadow: 0 0 12px var(--accent-glow);
}
.av-you {
  background: var(--surface2);
  border: 1px solid var(--border2);
  color: var(--text2);
}

.bubble {
  padding: 0.8rem 1.1rem;
  border-radius: 14px;
  font-size: 0.87rem;
  line-height: 1.7;
  max-width: 520px;
}
.bubble.ai {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 4px 14px 14px 14px;
}
.bubble.you {
  background: var(--accent);
  color: white;
  border-radius: 14px 4px 14px 14px;
  box-shadow: 0 0 20px var(--accent-glow);
}

/* Typing indicator */
.typing { display: flex; gap: 5px; align-items: center; padding: 0.3rem 0; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text3); animation: bop 1.2s infinite; }
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes bop { 0%,80%,100%{transform:translateY(0)} 40%{transform:translateY(-5px)} }

/* ── VOICE INPUT AREA ── */
.input-area {
  background: var(--surface);
  border-top: 1px solid var(--border);
  padding: 1.25rem 1.5rem;
  flex-shrink: 0;
}

.voice-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  max-width: 680px;
  margin: 0 auto;
}

.transcript-box {
  flex: 1;
  min-height: 44px;
  max-height: 120px;
  padding: 0.65rem 0.9rem;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  font-family: var(--sans);
  font-size: 0.87rem;
  color: var(--text);
  resize: none;
  outline: none;
  overflow-y: auto;
  line-height: 1.5;
  transition: border-color 0.2s;
}
.transcript-box:focus { border-color: var(--accent); }
.transcript-box.listening { border-color: var(--red); box-shadow: 0 0 12px rgba(248,113,113,0.2); }
.transcript-box.has-text { border-color: var(--border2); }

/* Mic button */
.mic-btn {
  width: 48px; height: 48px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  transition: all 0.2s;
  position: relative;
}
.mic-btn.idle {
  background: var(--surface2);
  border: 1px solid var(--border2);
  color: var(--text2);
}
.mic-btn.idle:hover {
  background: var(--accent);
  border-color: var(--accent);
  color: white;
  box-shadow: 0 0 16px var(--accent-glow);
}
.mic-btn.recording {
  background: var(--red);
  border-color: var(--red);
  color: white;
  box-shadow: 0 0 20px rgba(248,113,113,0.4);
  animation: pulse-mic 1.5s infinite;
}
@keyframes pulse-mic {
  0%,100% { box-shadow: 0 0 20px rgba(248,113,113,0.4); }
  50% { box-shadow: 0 0 35px rgba(248,113,113,0.7); }
}
.mic-btn:disabled { opacity: 0.3; cursor: not-allowed; }

/* Send button */
.send-btn {
  height: 48px;
  padding: 0 1.1rem;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: var(--r-sm);
  cursor: pointer;
  font-family: var(--sans);
  font-size: 0.83rem;
  font-weight: 600;
  flex-shrink: 0;
  transition: all 0.2s;
  box-shadow: 0 0 16px var(--accent-glow);
}
.send-btn:hover { opacity: 0.9; }
.send-btn:disabled { opacity: 0.3; cursor: not-allowed; box-shadow: none; }

.voice-hints {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1.5rem;
  margin-top: 0.6rem;
  max-width: 680px;
  margin-left: auto;
  margin-right: auto;
}
.hint-item {
  font-family: var(--mono);
  font-size: 0.67rem;
  color: var(--text3);
  display: flex;
  align-items: center;
  gap: 5px;
}
.hint-dot { width: 4px; height: 4px; border-radius: 50%; background: var(--text3); }

/* Recording wave animation */
.wave-container {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 0 0.5rem;
}
.wave-bar {
  width: 3px;
  background: var(--red);
  border-radius: 2px;
  animation: wave 0.8s ease-in-out infinite;
}
.wave-bar:nth-child(1) { height: 8px; animation-delay: 0s; }
.wave-bar:nth-child(2) { height: 14px; animation-delay: 0.1s; }
.wave-bar:nth-child(3) { height: 10px; animation-delay: 0.2s; }
.wave-bar:nth-child(4) { height: 16px; animation-delay: 0.15s; }
.wave-bar:nth-child(5) { height: 8px; animation-delay: 0.05s; }
@keyframes wave { 0%,100%{transform:scaleY(0.4)} 50%{transform:scaleY(1)} }

/* ── REPORT ── */
.report { min-height: 100vh; background: var(--bg); }

.rbar {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0.9rem 2rem;
  position: sticky; top: 0; z-index: 10;
  display: flex; align-items: center; gap: 1rem;
}
.rtitle { font-family: var(--serif); font-size: 1.2rem; font-weight: 400; }
.rmeta { font-family: var(--mono); font-size: 0.68rem; color: var(--text3); }
.btn-sm {
  margin-left: auto;
  padding: 0.4rem 0.9rem;
  border: 1px solid var(--border2);
  border-radius: var(--r-sm);
  background: transparent;
  cursor: pointer;
  font-family: var(--sans);
  font-size: 0.78rem;
  color: var(--text2);
  transition: all 0.15s;
}
.btn-sm:hover { background: var(--surface2); color: var(--text); }

.rlayout {
  max-width: 1080px; margin: 0 auto; padding: 1.75rem;
  display: grid; grid-template-columns: 1fr 300px; gap: 1.25rem;
  align-items: start;
}
@media(max-width:820px){ .rlayout{ grid-template-columns:1fr; } }

.rmain, .rside { display: flex; flex-direction: column; gap: 1.1rem; }
.rside { position: sticky; top: 68px; }

.rcrd {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 1.35rem;
}

.slbl {
  font-family: var(--mono);
  font-size: 0.65rem;
  letter-spacing: 0.12em;
  color: var(--text3);
  text-transform: uppercase;
  margin-bottom: 0.9rem;
}

.summary { font-size: 0.9rem; line-height: 1.8; color: var(--text); }

.traj {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 10px; border-radius: 20px;
  font-size: 0.68rem; font-family: var(--mono); font-weight: 500;
  margin-top: 0.7rem;
}
.tj-improving { background: var(--green-bg); color: var(--green); border: 1px solid rgba(52,211,153,0.2); }
.tj-declining { background: var(--red-bg); color: var(--red); border: 1px solid rgba(248,113,113,0.2); }
.tj-stable { background: var(--amber-bg); color: var(--amber); border: 1px solid rgba(251,191,36,0.2); }
.tj-insufficient_data { background: var(--surface2); color: var(--text3); border: 1px solid var(--border); }

/* Score bars */
.slist { display: flex; flex-direction: column; gap: 11px; }
.srow { display: flex; flex-direction: column; gap: 4px; }
.srh { display: flex; justify-content: space-between; align-items: baseline; }
.sdim { font-size: 0.77rem; color: var(--text2); }
.sval { font-size: 0.77rem; font-family: var(--mono); font-weight: 500; }
.strack { height: 4px; background: var(--surface2); border-radius: 3px; overflow: hidden; }
.sfill { height: 100%; border-radius: 3px; transition: width 0.6s ease; }

/* Mini score cards */
.scards { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
.smc { background: var(--surface2); border-radius: var(--r-sm); padding: 0.75rem; border: 1px solid var(--border); }
.sml { font-size: 0.62rem; color: var(--text3); font-family: var(--mono); letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 0.25rem; }
.smv { font-size: 0.85rem; font-weight: 600; }

/* Feedback */
.fsec { display: flex; flex-direction: column; gap: 9px; }
.fc { border: 1px solid var(--border); border-radius: var(--r); padding: 1rem 1.15rem; background: var(--surface); }
.fc.str { border-left: 3px solid var(--green); }
.fc.imp { border-left: 3px solid var(--amber); }
.fobs { font-size: 0.85rem; font-weight: 600; color: var(--text); margin-bottom: 0.5rem; line-height: 1.5; }
.fsug { font-size: 0.79rem; color: var(--text2); line-height: 1.65; margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px solid var(--border); }
.fsug::before { content: "→ "; color: var(--text3); }

/* Evidence chips */
.evlist { display: flex; flex-direction: column; gap: 5px; margin: 0.4rem 0; }
.chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 9px; background: var(--surface2); border-radius: var(--r-sm);
  font-size: 0.72rem; cursor: pointer;
  border: 1px solid var(--border);
  transition: all 0.15s; width: fit-content;
}
.chip:hover { background: var(--blue-bg); border-color: rgba(96,165,250,0.3); color: var(--blue); }
.cturn { font-family: var(--mono); font-weight: 500; }
.cexc { color: var(--text2); font-style: italic; }

/* Topics */
.tgrid { display: flex; flex-direction: column; gap: 8px; }
.trow { display: flex; align-items: center; gap: 8px; }
.tname { font-size: 0.8rem; color: var(--text); flex: 1; }
.tbar { flex: 1; height: 3px; background: var(--surface2); border-radius: 2px; overflow: hidden; }
.tbfill { height: 100%; background: var(--accent); border-radius: 2px; transition: width 0.5s; }
.tstat { padding: 2px 7px; border-radius: 20px; font-size: 0.64rem; font-family: var(--mono); font-weight: 500; white-space: nowrap; }
.s-visited { background: var(--green-bg); color: var(--green); }
.s-depth_ceiling { background: var(--amber-bg); color: var(--amber); }
.s-unvisited { background: var(--surface2); color: var(--text3); }

/* Recommendations */
.rlist { display: flex; flex-direction: column; gap: 10px; }
.ritem { display: flex; gap: 10px; align-items: flex-start; }
.rnum {
  width: 22px; height: 22px; border-radius: 50%;
  background: var(--accent); color: white;
  font-size: 0.67rem; font-weight: 600;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; margin-top: 1px;
  font-family: var(--mono);
  box-shadow: 0 0 8px var(--accent-glow);
}
.rtext { font-size: 0.83rem; line-height: 1.65; color: var(--text2); }

/* Transcript */
.ttoggle { font-size: 0.74rem; color: var(--accent2); cursor: pointer; background: none; border: none; text-decoration: underline; text-underline-offset: 3px; padding: 0; }
.tpanel { margin-top: 0.9rem; display: flex; flex-direction: column; gap: 10px; }
.tturn { border: 1px solid var(--border); border-radius: var(--r-sm); overflow: hidden; scroll-margin-top: 80px; transition: border-color 0.3s; }
.tturn.hl { border-color: var(--accent); box-shadow: 0 0 12px var(--accent-glow); }
.tq { padding: 0.55rem 0.9rem; background: var(--surface2); font-size: 0.73rem; color: var(--text2); border-bottom: 1px solid var(--border); font-family: var(--mono); }
.tqlbl { color: var(--text3); margin-right: 5px; }
.ta { padding: 0.7rem 0.9rem; font-size: 0.83rem; line-height: 1.65; color: var(--text); }

/* Loading */
.loading { min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1rem; background: var(--bg); }
.spin { width: 32px; height: 32px; border: 2px solid var(--border2); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.ltxt { font-family: var(--mono); font-size: 0.75rem; color: var(--text3); }
`

/* ─────────────────────────────────────────────────────────────────────────
   VOICE TEXT-TO-SPEECH HOOK  (backend-proxied — no client-side API keys)
───────────────────────────────────────────────────────────────────────── */
function useElevenLabs() {
  const [isSpeaking, setIsSpeaking] = useState(false)
  // Start optimistic; flip false on first 503 so we stop trying silently
  const voiceAvailableRef = useRef(true)
  const audioRef = useRef(null)

  const speak = useCallback(async (text) => {
    if (!voiceAvailableRef.current || !text) return

    // Stop any currently playing audio
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }

    setIsSpeaking(true)
    try {
      const response = await fetch(`${BACKEND_URL}/voice/speak`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })

      if (!response.ok) {
        if (response.status === 503) {
          // Voice not configured server-side — stop attempting silently
          voiceAvailableRef.current = false
        } else {
          console.warn('[Voice] Backend error:', response.status)
        }
        setIsSpeaking(false)
        return
      }

      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audioRef.current = audio

      audio.onended = () => {
        setIsSpeaking(false)
        URL.revokeObjectURL(url)
        audioRef.current = null
      }
      audio.onerror = () => {
        setIsSpeaking(false)
        audioRef.current = null
      }

      await audio.play()
    } catch (e) {
      // Network error (backend down, etc.) — degrade silently
      console.warn('[Voice] Unavailable:', e.message)
      setIsSpeaking(false)
    }
  }, [])

  const stopSpeaking = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    setIsSpeaking(false)
  }, [])

  return { speak, stopSpeaking, isSpeaking }
}

/* ─────────────────────────────────────────────────────────────────────────
   WEB SPEECH API — SPEECH TO TEXT HOOK
───────────────────────────────────────────────────────────────────────── */
function useSpeechToText() {
  const [isListening, setIsListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const recognitionRef = useRef(null)
  const supported = typeof window !== 'undefined' && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)

  const startListening = useCallback(() => {
    if (!supported) return
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    const recognition = new SR()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = 'en-US'

    recognition.onstart = () => setIsListening(true)

    recognition.onresult = (event) => {
      let finalTranscript = ''
      let interimTranscript = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript
        if (event.results[i].isFinal) finalTranscript += t
        else interimTranscript += t
      }
      setTranscript(prev => {
        const base = prev.replace(/\[listening...\]$/, '').trimEnd()
        if (finalTranscript) return (base + ' ' + finalTranscript).trim()
        return (base + ' ' + interimTranscript + '[listening...]').trim()
      })
    }

    recognition.onerror = () => setIsListening(false)
    recognition.onend = () => {
      setIsListening(false)
      setTranscript(prev => prev.replace(/\s*\[listening\.\.\.\]$/, '').trim())
    }

    recognitionRef.current = recognition
    recognition.start()
  }, [supported])

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop()
      recognitionRef.current = null
    }
    setTranscript(prev => prev.replace(/\s*\[listening\.\.\.\]$/, '').trim())
    setIsListening(false)
  }, [])

  const clearTranscript = useCallback(() => setTranscript(''), [])

  return { isListening, transcript, setTranscript, startListening, stopListening, clearTranscript, supported }
}

/* ─────────────────────────────────────────────────────────────────────────
   SETUP SCREEN
───────────────────────────────────────────────────────────────────────── */
function SetupScreen({ onStart }) {
  const [role, setRole] = useState('Product Manager')
  const [focusArea, setFocusArea] = useState('product strategy and execution')
  const [background, setBackground] = useState('3+ years of product management experience')
  const [difficulty, setDifficulty] = useState('mid')
  const [topics, setTopics] = useState(new Set(DEFAULT_TOPICS))
  const [customTopic, setCustomTopic] = useState('')
  const [interviewerRole, setInterviewerRole] = useState('Director of Product')
  const [interviewerSeniority, setInterviewerSeniority] = useState('director')
  const [interviewerYoe, setInterviewerYoe] = useState(15)
  const [interviewerStyle, setInterviewerStyle] = useState('Curious and direct. Focuses on reasoning behind decisions, not just outcomes.')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const toggle = (t) => setTopics(prev => {
    const n = new Set(prev)
    n.has(t) ? n.delete(t) : n.add(t)
    return n
  })

  const handleAddTopic = (e) => {
    if (e.key === 'Enter' || e.type === 'blur') {
      if (customTopic.trim()) {
        setTopics(prev => {
          const n = new Set(prev)
          n.add(customTopic.trim())
          return n
        })
        setCustomTopic('')
      }
    }
  }

  const handleStart = async () => {
    if (!role.trim() || topics.size === 0) return
    setLoading(true); setError(null)
    try {
      const data = await api.startSession({
        role, focus_area: focusArea,
        candidate_background: background,
        difficulty, topics: [...topics], target_turns: 6,
        interviewer_role: interviewerRole,
        interviewer_seniority: interviewerSeniority,
        interviewer_yoe: Number(interviewerYoe),
        interviewer_style: interviewerStyle,
      })
      onStart(data)
    } catch (e) {
      setError(e.message || 'Could not connect. Is the backend running on port 8000?')
    } finally { setLoading(false) }
  }

  return (
    <div className="setup">
      <div className="setup-inner">
        <div className="logo-row">
          <div className="logo-dot" />
          <div className="logo-text">AI Interview Coach</div>
        </div>
        <h1>Ace your next <em>interview</em></h1>
        <p className="subtitle">
          Practice with an AI that adapts to your answers, probes your depth,
          and gives you a detailed feedback report at the end.
        </p>

        <div className="form-card">
          {error && <div className="err">{error}</div>}

          <div className="fg">
            <label className="lbl">Role</label>
            <input className="inp" value={role} onChange={e => setRole(e.target.value)} />
          </div>

          <div className="row2">
            <div className="fg">
              <label className="lbl">Focus area</label>
              <input className="inp" value={focusArea} onChange={e => setFocusArea(e.target.value)} />
            </div>
            <div className="fg">
              <label className="lbl">Difficulty</label>
              <select className="inp" value={difficulty} onChange={e => setDifficulty(e.target.value)}>
                {['junior', 'mid', 'senior', 'staff'].map(d => (
                  <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="fg">
            <label className="lbl">Your background</label>
            <textarea className="inp" value={background} onChange={e => setBackground(e.target.value)} />
          </div>

          <div className="fg">
            <label className="lbl">Topics to cover (Dynamic Focus Areas)</label>
            <div className="pills">
              {[...topics].map(t => (
                <div key={t} className="pill on" onClick={() => toggle(t)}>{t} ✕</div>
              ))}
            </div>
            <input 
              className="inp" 
              style={{marginTop: '8px'}}
              placeholder="Type a custom topic and press Enter..." 
              value={customTopic} 
              onChange={e => setCustomTopic(e.target.value)}
              onKeyDown={handleAddTopic}
              onBlur={handleAddTopic}
            />
          </div>

          <div style={{borderTop: '1px solid var(--border)', margin: '1.5rem 0', paddingTop: '1rem'}}>
            <label className="lbl" style={{color: 'var(--accent)', fontSize: '0.8rem', marginBottom: '1rem'}}>Interviewer Persona Configuration</label>
            <div className="row2">
              <div className="fg">
                <label className="lbl">Interviewer Role</label>
                <input className="inp" value={interviewerRole} onChange={e => setInterviewerRole(e.target.value)} />
              </div>
              <div className="fg">
                <label className="lbl">Interviewer Seniority</label>
                <select className="inp" value={interviewerSeniority} onChange={e => setInterviewerSeniority(e.target.value)}>
                  {['mid', 'senior', 'staff', 'principal', 'director'].map(d => (
                    <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="row2">
              <div className="fg">
                <label className="lbl">Years of Experience</label>
                <input className="inp" type="number" min="1" max="50" value={interviewerYoe} onChange={e => setInterviewerYoe(e.target.value)} />
              </div>
              <div className="fg">
                <label className="lbl">Interviewer Style</label>
                <input className="inp" value={interviewerStyle} onChange={e => setInterviewerStyle(e.target.value)} />
              </div>
            </div>
          </div>

          <button className="btn-primary" onClick={handleStart} disabled={loading || topics.size === 0}>
            {loading ? 'Starting interview…' : 'Begin interview →'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────
   INTERVIEW SCREEN
───────────────────────────────────────────────────────────────────────── */
function InterviewScreen({ sessionId, firstQuestion, topic, phase: initPhase, role, onComplete }) {
  const [messages, setMessages] = useState([{ role: 'ai', content: firstQuestion }])
  const [loading, setLoading] = useState(false)
  const [topic_, setTopic] = useState(topic)
  const [phase_, setPhase] = useState(initPhase)
  const [turns, setTurns] = useState(0)
  const [error, setError] = useState(null)

  const chatRef = useRef(null)
  const { speak, stopSpeaking, isSpeaking } = useElevenLabs()
  const { isListening, transcript, setTranscript, startListening, stopListening, clearTranscript, supported } = useSpeechToText()

  // Auto-speak first question (voice degrades silently if backend has no key)
  useEffect(() => {
    if (firstQuestion) speak(firstQuestion)
  }, [])

  // Auto-scroll chat
  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight
  }, [messages, loading])

  const handleMicClick = () => {
    if (isListening) {
      stopListening()
    } else {
      stopSpeaking()
      startListening()
    }
  }

  const submit = async () => {
    const text = transcript.replace(/\s*\[listening\.\.\.\]$/, '').trim()
    if (!text || loading) return

    stopListening()
    clearTranscript()
    setMessages(prev => [...prev, { role: 'you', content: text }])
    setLoading(true); setError(null)

    try {
      const data = await api.submitAnswer(sessionId, text)
      setTurns(data.turn_count); setPhase(data.phase)

      if (data.is_complete) {
        const closing = data.question || 'Thank you — generating your report now…'
        setMessages(prev => [...prev, { role: 'ai', content: closing }])
        await speak(closing)
        setTimeout(() => onComplete(sessionId), 1500)
      } else {
        setTopic(data.topic)
        setMessages(prev => [...prev, { role: 'ai', content: data.question }])
        speak(data.question)
      }
    } catch (e) {
      setError(e.message || 'Something went wrong. Please try again.')
      setMessages(prev => prev.slice(0, -1))
      setTranscript(text)
    } finally { setLoading(false) }
  }

  // Clean display transcript (remove [listening...] for display)
  const displayTranscript = transcript.replace(/\s*\[listening\.\.\.\]$/, '')
  const isRecording = isListening
  const hasText = displayTranscript.trim().length > 0

  return (
    <div className="interview">
      {/* Header */}
      <div className="iheader">
        <div className="hlogo">
          <div className="hlogo-dot" />
          <div>
            <div className="hrole">{role}</div>
            <div className="hmeta">interview in progress</div>
          </div>
        </div>
        <div className="badges">
          {isSpeaking && (
            <div className="speaking-badge">
              <div className="speaking-bars">
                {[1,2,3,4,5].map(i => <div key={i} className="speaking-bar" />)}
              </div>
              AI speaking
            </div>
          )}
          {isRecording && (
            <div className="speaking-badge" style={{background:'rgba(248,113,113,0.15)',borderColor:'rgba(248,113,113,0.3)',color:'var(--red)'}}>
              <div className="wave-container">
                {[1,2,3,4,5].map(i => <div key={i} className="wave-bar" style={{background:'var(--red)'}} />)}
              </div>
              Recording
            </div>
          )}
          <span className="badge b-topic">{topic_}</span>
          <span className="badge b-turn">turn {turns}</span>
          <span className="badge b-phase">{phase_}</span>
        </div>
      </div>

      {/* Chat */}
      <div className="chat-wrap">
        <div className="chat" ref={chatRef}>
          {messages.map((m, i) => (
            <div key={i} className={`mrow ${m.role}`}>
              <div className={`avatar av-${m.role}`}>{m.role === 'ai' ? 'AI' : 'You'}</div>
              <div className={`bubble ${m.role}`}>{m.content}</div>
            </div>
          ))}
          {loading && (
            <div className="mrow ai">
              <div className="avatar av-ai">AI</div>
              <div className="bubble ai">
                <div className="typing">
                  <div className="dot" /><div className="dot" /><div className="dot" />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {error && <div className="err" style={{margin:'0 1.5rem .75rem'}}>{error}</div>}

      {/* Voice input area */}
      <div className="input-area">
        <div className="voice-row">
          {/* Mic button */}
          <button
            className={`mic-btn ${isRecording ? 'recording' : 'idle'}`}
            onClick={handleMicClick}
            disabled={loading || isSpeaking || !supported}
            title={!supported ? 'Speech recognition not supported in this browser. Use Chrome.' : isRecording ? 'Click to stop recording' : 'Click to start recording'}
          >
            {isRecording ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="6" width="12" height="12" rx="2"/>
              </svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                <line x1="12" y1="19" x2="12" y2="23"/>
                <line x1="8" y1="23" x2="16" y2="23"/>
              </svg>
            )}
          </button>

          {/* Transcript / text input */}
          <textarea
            className={`transcript-box ${isRecording ? 'listening' : ''} ${hasText ? 'has-text' : ''}`}
            value={displayTranscript}
            onChange={e => setTranscript(e.target.value)}
            placeholder={
              !supported
                ? 'Type your answer here (speech not supported in this browser)...'
                : isRecording
                ? 'Listening… speak now'
                : 'Click 🎙 to speak, or type your answer here…'
            }
            rows={1}
            disabled={loading}
          />

          {/* Send button */}
          <button
            className="send-btn"
            onClick={submit}
            disabled={loading || !hasText}
          >
            Send
          </button>
        </div>

        <div className="voice-hints">
          <div className="hint-item">
            <div className="hint-dot" />
            {supported ? 'click mic to speak' : 'type your answer'}
          </div>
          <div className="hint-dot" />
          <div className="hint-item">click mic again to stop</div>
          <div className="hint-dot" />
          <div className="hint-item">click send to submit</div>
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────
   REPORT COMPONENTS
───────────────────────────────────────────────────────────────────────── */
function ScoreBar({ label, score, color }) {
  return (
    <div className="srow">
      <div className="srh">
        <span className="sdim">{label}</span>
        <span className="sval" style={{ color }}>{(score || 0).toFixed(1)}</span>
      </div>
      <div className="strack">
        <div className="sfill" style={{ width: `${((score || 0) / 5) * 100}%`, background: color }} />
      </div>
    </div>
  )
}

function Citation({ ev, onCite }) {
  return (
    <div className="chip" onClick={() => onCite(ev.turn_index)}>
      <span className="cturn">Turn {ev.turn_index}</span>
      <span className="cexc">{(ev.excerpt || '').slice(0, 50)}{(ev.excerpt || '').length > 50 ? '…' : ''}</span>
    </div>
  )
}

function FeedbackCard({ fp, type, onCite }) {
  if (!fp) return null
  return (
    <div className={`fc ${type}`}>
      <div className="fobs">{fp.observation}</div>
      <div className="evlist">
        {(fp.evidence || []).map((ev, i) => <Citation key={i} ev={ev} onCite={onCite} />)}
      </div>
      <div className="fsug">{fp.suggestion}</div>
    </div>
  )
}

function Transcript({ turns, highlighted, refs }) {
  const [open, setOpen] = useState(false)
  if (!turns?.length) return null
  return (
    <div className="rcrd">
      <div className="slbl">Full transcript</div>
      <button className="ttoggle" onClick={() => setOpen(o => !o)}>
        {open ? 'hide transcript' : `show ${turns.length} turns`}
      </button>
      {open && (
        <div className="tpanel">
          {turns.map((t, i) => (
            <div key={i} id={`turn-${t.turn_index}`}
              ref={el => refs.current[t.turn_index] = el}
              className={`tturn ${highlighted === t.turn_index ? 'hl' : ''}`}
            >
              <div className="tq"><span className="tqlbl">Q{t.turn_index} · {t.topic}</span>{t.question}</div>
              <div className="ta">{t.answer}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────
   REPORT SCREEN
───────────────────────────────────────────────────────────────────────── */
function ReportScreen({ sessionId, onRestart }) {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [highlighted, setHighlighted] = useState(null)
  const turnRefs = useRef({})
  const transcriptRef = useRef(null)

  useEffect(() => {
    api.getReport(sessionId)
      .then(setReport)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [sessionId])

  const onCite = useCallback((idx) => {
    setHighlighted(idx)
    const el = turnRefs.current[idx]
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      setTimeout(() => setHighlighted(null), 2500)
    } else {
      transcriptRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [])

  if (loading) return (
    <div className="loading">
      <div className="spin" />
      <div className="ltxt">generating your performance report…</div>
    </div>
  )
  if (error) return (
    <div className="loading">
      <div className="err" style={{ maxWidth: 460 }}>{error}</div>
      <button className="btn-sm" onClick={onRestart}>Start over</button>
    </div>
  )
  if (!report) return null

  const ss = report.score_summary || {}
  const scores = ss.scores || {}
  const traj = ss.trajectory || 'insufficient_data'
  const turns = report._turns || []

  return (
    <div className="report">
      <div className="rbar">
        <div>
          <div className="rtitle">Interview Report</div>
          <div className="rmeta">{report.role} · {report.focus_area} · {report.total_turns} turns · {report.interview_duration_approx}</div>
        </div>
        <button className="btn-sm" onClick={onRestart}>New interview</button>
      </div>

      <div className="rlayout">
        <div className="rmain">
          <div className="rcrd">
            <div className="slbl">Overall assessment</div>
            <p className="summary">{report.overall_summary}</p>
            <div className={`traj tj-${traj}`}>
              {traj === 'improving' ? '↑ improving' : traj === 'declining' ? '↓ declining' : traj === 'stable' ? '→ stable' : '~ early data'}
            </div>
          </div>

          {report.strengths?.length > 0 && (
            <div className="rcrd">
              <div className="slbl">Strengths</div>
              <div className="fsec">{report.strengths.map((fp, i) => <FeedbackCard key={i} fp={fp} type="str" onCite={onCite} />)}</div>
            </div>
          )}

          {report.improvement_areas?.length > 0 && (
            <div className="rcrd">
              <div className="slbl">Growth areas</div>
              <div className="fsec">{report.improvement_areas.map((fp, i) => <FeedbackCard key={i} fp={fp} type="imp" onCite={onCite} />)}</div>
            </div>
          )}

          {(report.technical_feedback || report.communication_feedback) && (
            <div className="rcrd">
              <div className="slbl">Detailed feedback</div>
              <div className="fsec">
                {report.technical_feedback && <FeedbackCard fp={report.technical_feedback} type="imp" onCite={onCite} />}
                {report.communication_feedback && <FeedbackCard fp={report.communication_feedback} type="imp" onCite={onCite} />}
              </div>
            </div>
          )}

          <div ref={transcriptRef}>
            <Transcript turns={turns} highlighted={highlighted} refs={turnRefs} />
          </div>
        </div>

        <div className="rside">
          <div className="rcrd">
            <div className="slbl">Performance scores</div>
            <div className="slist">
              {Object.entries(SCORE_META).map(([k, m]) => (
                <ScoreBar key={k} label={m.label} score={scores[k] || 0} color={m.color} />
              ))}
            </div>
          </div>

          {(ss.strongest_dimension || ss.weakest_dimension) && (
            <div className="rcrd">
              <div className="scards">
                <div className="smc">
                  <div className="sml">Strongest</div>
                  <div className="smv" style={{ color: 'var(--green)', fontSize: '.82rem' }}>
                    {SCORE_META[ss.strongest_dimension]?.label || ss.strongest_dimension}
                  </div>
                </div>
                <div className="smc">
                  <div className="sml">Needs work</div>
                  <div className="smv" style={{ color: 'var(--red)', fontSize: '.82rem' }}>
                    {SCORE_META[ss.weakest_dimension]?.label || ss.weakest_dimension}
                  </div>
                </div>
              </div>
            </div>
          )}

          {report.topic_coverage?.length > 0 && (
            <div className="rcrd">
              <div className="slbl">Topic coverage</div>
              <div className="tgrid">
                {report.topic_coverage.map((tc, i) => (
                  <div key={i} className="trow">
                    <span className="tname">{tc.topic}</span>
                    {tc.peak_depth_score && (
                      <div className="tbar">
                        <div className="tbfill" style={{ width: `${(tc.peak_depth_score / 5) * 100}%` }} />
                      </div>
                    )}
                    <span className={`tstat s-${tc.status}`}>
                      {tc.status === 'visited' ? 'covered' : tc.status === 'depth_ceiling' ? 'ceiling' : 'skipped'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {report.practice_recommendations?.length > 0 && (
            <div className="rcrd">
              <div className="slbl">Practice recommendations</div>
              <div className="rlist">
                {report.practice_recommendations.map((r, i) => (
                  <div key={i} className="ritem">
                    <div className="rnum">{i + 1}</div>
                    <div className="rtext">{r}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────
   ROOT APP
───────────────────────────────────────────────────────────────────────── */
export default function App() {
  const [phase, setPhase] = useState('setup')
  const [session, setSession] = useState(null)

  const onStart = (data) => { setSession(data); setPhase('interview') }
  const onComplete = (sid) => { setSession(s => ({ ...s, session_id: sid })); setPhase('report') }
  const onRestart = () => { setSession(null); setPhase('setup') }

  return (
    <>
      <style>{STYLES}</style>
      {phase === 'setup' && <SetupScreen onStart={onStart} />}
      {phase === 'interview' && session && (
        <InterviewScreen
          sessionId={session.session_id}
          firstQuestion={session.question}
          topic={session.topic}
          phase={session.phase}
          role={session.role || 'Interview'}
          onComplete={onComplete}
        />
      )}
      {phase === 'report' && session && (
        <ReportScreen sessionId={session.session_id} onRestart={onRestart} />
      )}
    </>
  )
}
