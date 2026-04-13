export default function LoginPage({ onLogin }: { onLogin: () => void }) {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center relative overflow-hidden">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        {[...Array(6)].map((_, i) => (
          <div
            key={i}
            className="absolute rounded-full opacity-10 bg-blue-400 animate-float"
            style={{
              width: 80 + i * 40,
              height: 80 + i * 40,
              left: `${10 + i * 15}%`,
              top: `${20 + (i % 3) * 25}%`,
              animationDelay: `${i * 0.7}s`,
              animationDuration: `${6 + i * 2}s`,
            }}
          />
        ))}
      </div>

      <div className="relative z-10 w-full max-w-sm animate-fade-in">
        <div className="bg-white/10 backdrop-blur-xl rounded-2xl border border-white/20 shadow-2xl p-8">
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 shadow-lg shadow-blue-500/30 mb-4 animate-pulse-slow">
              <svg
                className="w-8 h-8 text-white"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z"
                />
              </svg>
            </div>
            <h1 className="text-2xl font-bold text-white tracking-tight">
              mas-pipeline
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Multi-Agent Content Pipeline
            </p>
          </div>

          <button
            type="button"
            onClick={onLogin}
            className="w-full rounded-lg bg-gradient-to-r from-blue-500 to-indigo-600 px-4 py-3 text-sm font-medium text-white shadow-lg shadow-blue-500/25 hover:shadow-blue-500/40 hover:from-blue-600 hover:to-indigo-700 transition-all duration-200"
          >
            进入
          </button>
        </div>
      </div>
    </div>
  );
}
