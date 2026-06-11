import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';
import { adminGuard } from './core/guards/admin.guard';

export const routes: Routes = [
  { path: '', redirectTo: '/login', pathMatch: 'full' },
  { 
    path: 'login', 
    loadComponent: () => import('./login/login.component').then(c => c.LoginComponent) 
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () => import('./layout/layout.component').then(c => c.LayoutComponent),
    children: [
      { 
        path: 'chat', 
        loadComponent: () => import('./chat/chat.component').then(c => c.ChatComponent) 
      },
      { 
        path: 'settings', 
        loadComponent: () => import('./settings/settings.component').then(c => c.SettingsComponent) 
      },
      {
        path: 'admin',
        canActivate: [adminGuard],
        loadComponent: () => import('./admin-layout/admin-layout.component').then(c => c.AdminLayoutComponent),
        children: [
          { 
            path: '', 
            redirectTo: 'dashboard',
            pathMatch: 'full'
          },
          { 
            path: 'dashboard', 
            loadComponent: () => import('./admin-dashboard/admin-dashboard.component').then(c => c.AdminDashboardComponent) 
          },
          { 
            path: 'users', 
            loadComponent: () => import('./admin/users/users.component').then(c => c.UsersComponent) 
          },
          { 
            path: 'analytics', 
            loadComponent: () => import('./admin/analytics/analytics.component').then(c => c.AnalyticsComponent) 
          },
          { 
            path: 'system', 
            loadComponent: () => import('./admin/system/system.component').then(c => c.SystemComponent) 
          },
          { 
            path: 'logs', 
            loadComponent: () => import('./admin/system-logs/system-logs.component').then(c => c.SystemLogsComponent) 
          },
          { 
            path: 'reports', 
            loadComponent: () => import('./admin/reports/reports.component').then(c => c.ReportsComponent) 
          },
          { 
            path: 'maintenance', 
            loadComponent: () => import('./admin/maintenance/maintenance.component').then(c => c.MaintenanceComponent) 
          },
          {
            path: 'settings',
            loadComponent: () => import('./admin/settings/settings.component').then(c => c.AdminSettingsComponent)
          },
          {
            path: 'audit-log',
            loadComponent: () => import('./admin/audit-log/audit-log.component').then(c => c.AuditLogComponent)
          }
        ]
      },
      { 
        path: 'viewer', 
        loadComponent: () => import('./document-viewer/document-viewer.component').then(c => c.DocumentViewerComponent) 
      }
    ]
  },
  { path: '**', redirectTo: '/login' }
];
