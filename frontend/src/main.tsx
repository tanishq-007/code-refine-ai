import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import '@fontsource-variable/inter'
import '@fontsource/jetbrains-mono'
import './index.css'
import { RepoProvider, ThemeProvider } from './lib/store'
import { Layout } from './components/Layout'
import { LandingPage } from './pages/Landing'
import { OverviewPage } from './pages/Overview'
import { FindingsPage } from './pages/Findings'
import { RoadmapPage } from './pages/Roadmap'
import { FixesPage } from './pages/Fixes'
import { EditorPage } from './pages/Editor'
import { RunPage } from './pages/Run'

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <LandingPage /> },
      { path: '/overview', element: <OverviewPage /> },
      { path: '/findings', element: <FindingsPage /> },
      { path: '/roadmap', element: <RoadmapPage /> },
      { path: '/fixes', element: <FixesPage /> },
      { path: '/editor', element: <EditorPage /> },
      { path: '/run', element: <RunPage /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <RepoProvider>
        <RouterProvider router={router} />
      </RepoProvider>
    </ThemeProvider>
  </StrictMode>,
)
