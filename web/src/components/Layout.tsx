import { Link, Outlet } from "react-router-dom";

export default function Layout() {
  return (
    <div className="min-h-full flex flex-col bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-6xl px-6 py-3 flex items-center justify-between">
          <Link to="/" className="text-lg font-semibold tracking-tight">
            mas-pipeline
          </Link>
          <span className="text-xs text-slate-500">web MVP</span>
        </div>
      </header>
      <main className="flex-1 mx-auto max-w-6xl w-full px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
