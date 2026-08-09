import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useRepo, useTheme } from '../lib/store'
import { RepoSwitcher } from './RepoSwitcher'
import {
  GridIcon, HomeIcon, ListIcon, LogoIcon, MapIcon, MoonIcon, PencilIcon,
  PlayIcon, SunIcon, WrenchIcon,
} from './icons'

const NAV = [
  { to: '/', label: 'Home', Icon: HomeIcon },
  { to: '/overview', label: 'Overview', Icon: GridIcon },
  { to: '/findings', label: 'Findings', Icon: ListIcon },
  { to: '/roadmap', label: 'Roadmap', Icon: MapIcon },
  { to: '/fixes', label: 'Fix review', Icon: WrenchIcon },
  { to: '/editor', label: 'Editor', Icon: PencilIcon },
  { to: '/run', label: 'Run pipeline', Icon: PlayIcon },
]

export function Layout() {
  const { theme, toggle } = useTheme()
  const { error } = useRepo()
  const { pathname } = useLocation()
  const isLanding = pathname === '/'

  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-20 flex w-64 flex-col border-r border-edge bg-surface px-3 py-5">
        <div className="mb-5 flex items-center gap-2.5 px-2">
          <span aria-hidden
            className="flex size-8 items-center justify-center rounded-lg text-white"
            style={{ background: 'var(--series-1)' }}>
            <LogoIcon />
          </span>
          <div>
            <div className="text-sm font-semibold leading-tight text-ink">Code Debt Collector</div>
            <div className="text-xs text-ink-3">tech-debt dashboard</div>
          </div>
        </div>

        <RepoSwitcher />

        <nav className="mt-5 flex flex-col gap-0.5">
          <p className="px-3 pb-1.5 text-xs font-medium uppercase tracking-wider text-ink-3">Views</p>
          {NAV.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `group flex h-9 items-center gap-2.5 rounded-lg border-l-2 px-3 text-sm transition-colors duration-200 ${
                  isActive
                    ? 'border-[var(--series-1)] bg-page font-medium text-ink'
                    : 'border-transparent text-ink-2 hover:bg-page hover:text-ink'
                }`}
            >
              {({ isActive }) => (
                <>
                  <Icon style={isActive ? { color: 'var(--series-1)' } : undefined}
                    className={isActive ? '' : 'text-ink-3 group-hover:text-ink-2'} />
                  {label}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <button
          onClick={toggle}
          className="mt-auto flex h-9 items-center gap-2.5 rounded-lg px-3 text-sm text-ink-2 transition-colors duration-200 hover:bg-page hover:text-ink"
        >
          {theme === 'dark' ? <SunIcon className="text-ink-3" /> : <MoonIcon className="text-ink-3" />}
          {theme === 'dark' ? 'Light mode' : 'Dark mode'}
        </button>
      </aside>

      <div className="ml-64 flex min-w-0 flex-1 flex-col">
        {error && !isLanding && (
          <div className="mx-6 mt-4 rounded-lg border border-edge bg-surface px-4 py-2.5 text-sm text-ink-2">
            <span aria-hidden style={{ color: 'var(--status-critical)' }}>✕</span> {error}
          </div>
        )}
        <main className="min-w-0 flex-1 px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
