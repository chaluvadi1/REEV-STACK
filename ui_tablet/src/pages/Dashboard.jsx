import { useState, useEffect } from 'react'
import { Zap, Fuel, Gauge, RotateCcw } from 'lucide-react'

const API = 'http://localhost:8000/api/v1'

const MODE_STYLES = {
  EV_ONLY:  { label: '⚡ EV Only',  bg: 'bg-blue-500' },
  HYBRID:   { label: '⚙ Hybrid',   bg: 'bg-yellow-500' },
  COASTING: { label: '↓ Coasting', bg: 'bg-cyan-500' },
  CHARGING: { label: '⏩ Charging', bg: 'bg-green-500' },
}

function BatteryGauge({ soc }) {
  const color = soc > 40 ? 'bg-green-400' : soc > 20 ? 'bg-yellow-400' : 'bg-red-500'
  return (
    <div className="flex flex-col items-center gap-2">
      <div className="text-6xl font-bold tabular-nums">
        {soc.toFixed(1)}<span className="text-3xl text-gray-400">%</span>
      </div>
      <div className="w-64 h-6 bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${soc}%` }}
        />
      </div>
      <div className="text-sm text-gray-400">Battery</div>
    </div>
  )
}

export default function Dashboard() {
  const [state, setState] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const fetchState = async () => {
      try {
        const res = await fetch(`${API}/vehicle/state`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        setState(await res.json())
        setError(null)
      } catch (e) {
        setError('API offline — is uvicorn running?')
      }
    }
    fetchState()
    const id = setInterval(fetchState, 1000)
    return () => clearInterval(id)
  }, [])

  const mode = state ? (MODE_STYLES[state.mode] ?? MODE_STYLES.EV_ONLY) : null

  return (
    <div className="min-h-screen bg-gray-900 text-white flex flex-col items-center justify-center gap-8 p-8">
      <h1 className="text-2xl font-semibold tracking-wide text-gray-300">REEV Stack</h1>

      {error && (
        <div className="bg-red-900 text-red-300 px-4 py-2 rounded-lg text-sm">{error}</div>
      )}

      {state ? (
        <>
          {/* Mode badge */}
          <div className={`px-6 py-2 rounded-full text-sm font-semibold ${mode.bg}`}>
            {mode.label}
          </div>

          {/* Battery */}
          <BatteryGauge soc={state.battery_soc_pct} />

          {/* Stats row */}
          <div className="grid grid-cols-3 gap-6 text-center">
            <div className="bg-gray-800 rounded-xl p-4">
              <Zap className="mx-auto mb-1 text-blue-400" size={20} />
              <div className="text-2xl font-bold">{state.ev_range_km.toFixed(0)}</div>
              <div className="text-xs text-gray-400">EV Range km</div>
            </div>
            <div className="bg-gray-800 rounded-xl p-4">
              <Gauge className="mx-auto mb-1 text-purple-400" size={20} />
              <div className="text-2xl font-bold">{state.total_range_km.toFixed(0)}</div>
              <div className="text-xs text-gray-400">Total Range km</div>
            </div>
            <div className="bg-gray-800 rounded-xl p-4">
              <Fuel className="mx-auto mb-1 text-yellow-400" size={20} />
              <div className="text-2xl font-bold">{state.fuel_level_pct.toFixed(0)}</div>
              <div className="text-xs text-gray-400">Fuel %</div>
            </div>
          </div>

          {/* Speed + odometer */}
          <div className="flex gap-8 text-center text-gray-400 text-sm">
            <div><span className="text-white font-semibold">{state.speed_kmh.toFixed(1)}</span> km/h</div>
            <div><span className="text-white font-semibold">{state.odometer_km.toFixed(1)}</span> km odo</div>
            <div><span className="text-white font-semibold">{state.motor_power_kw.toFixed(1)}</span> kW motor</div>
          </div>
        </>
      ) : (
        !error && <div className="text-gray-500 animate-pulse">Connecting to API...</div>
      )}
    </div>
  )
}