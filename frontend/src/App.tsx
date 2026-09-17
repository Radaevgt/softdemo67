import { NavLink, Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from './auth'
import { AdminAuditPage } from './pages/AdminAuditPage'
import { AdminRulesPage } from './pages/AdminRulesPage'
import { AdminUsersPage } from './pages/AdminUsersPage'
import { AssessmentPage } from './pages/AssessmentPage'
import { CasePage } from './pages/CasePage'
import { CasesPage } from './pages/CasesPage'
import { EscalationsPage } from './pages/EscalationsPage'
import { LoginPage } from './pages/LoginPage'
import { Empty, ROLE_LABELS } from './ui'
import type { Role } from './types'

export function App() {
  const { user, loading } = useAuth()

  if (loading) return <Empty>Загружаем портал…</Empty>
  if (!user) return <LoginPage />

  return (
    <div className="app">
      <TopBar />
      <Routes>
        <Route path="/" element={<Navigate to="/cases" replace />} />
        <Route path="/cases" element={<CasesPage />} />
        <Route path="/cases/:caseId" element={<CasePage />} />
        <Route path="/assessments/:assessmentId" element={<AssessmentPage />} />
        <Route path="/escalations" element={<EscalationsPage />} />
        <Route
          path="/admin/rules"
          element={<Guard roles={['methodologist', 'operator']}><AdminRulesPage /></Guard>}
        />
        <Route
          path="/admin/users"
          element={<Guard roles={['operator']}><AdminUsersPage /></Guard>}
        />
        <Route
          path="/admin/audit"
          element={<Guard roles={['operator']}><AdminAuditPage /></Guard>}
        />
        <Route path="*" element={<div className="page"><Empty>Страница не найдена</Empty></div>} />
      </Routes>
    </div>
  )
}

function Guard({ roles, children }: { roles: Role[]; children: React.ReactNode }) {
  const { can } = useAuth()
  if (!can(...roles)) {
    return <div className="page"><Empty>Раздел доступен другим ролям.</Empty></div>
  }
  return <>{children}</>
}

function TopBar() {
  const { user, signOut, can } = useAuth()
  if (!user) return null

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <span className="topbar__mark">МИ</span>
        Заброшенные объекты
      </div>

      <nav>
        <NavLink to="/cases" className={({ isActive }) => (isActive ? 'is-active' : '')}>
          Реестр объектов
        </NavLink>
        <NavLink to="/escalations" className={({ isActive }) => (isActive ? 'is-active' : '')}>
          Обращения
        </NavLink>
        {can('methodologist', 'operator') && (
          <NavLink to="/admin/rules" className={({ isActive }) => (isActive ? 'is-active' : '')}>
            Матрица сценариев
          </NavLink>
        )}
        {can('operator') && (
          <>
            <NavLink to="/admin/users" className={({ isActive }) => (isActive ? 'is-active' : '')}>
              Пользователи
            </NavLink>
            <NavLink to="/admin/audit" className={({ isActive }) => (isActive ? 'is-active' : '')}>
              Журнал
            </NavLink>
          </>
        )}
      </nav>

      <div className="topbar__user">
        <div className="topbar__who">
          {user.full_name}
          <small>
            {ROLE_LABELS[user.role]}
            {user.municipality ? ` · ${user.municipality.name}` : ''}
          </small>
        </div>
        <button className="btn btn--small" onClick={signOut}>Выйти</button>
      </div>
    </header>
  )
}
