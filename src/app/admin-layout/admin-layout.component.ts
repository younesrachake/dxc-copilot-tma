import { Component } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import { CommonModule } from '@angular/common';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { ApiService } from '../services/api.service';

@Component({
  selector: 'app-admin-layout',
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <div class="admin-layout">
      <!-- Sidebar -->
      <aside class="sidebar" [class.collapsed]="isCollapsed">
        <div class="brand">
          <img class="brand-logo-img" src="assets/images/dxc-logo.png" alt="DXC Technology" style="height:34px;width:auto;object-fit:contain;flex-shrink:0;filter:drop-shadow(0 1px 2px rgba(0,0,0,0.4));" />
          <span class="nav-text">DXC Copilot <span class="badge-admin">ADMIN</span></span>
        </div>

        <ul class="nav-list">
          <li class="nav-item" [class.active]="router.url === '/admin/dashboard' || router.url === '/admin'" routerLink="dashboard" routerLinkActive="active">
            <span class="nav-icon">📊</span> <span class="nav-text">Tableau de bord</span>
          </li>
          <li class="nav-item" routerLink="users" routerLinkActive="active">
            <span class="nav-icon">👥</span> <span class="nav-text">Utilisateurs</span>
          </li>
          <li class="nav-item" routerLink="analytics" routerLinkActive="active">
            <span class="nav-icon">📈</span> <span class="nav-text">Analytics</span>
          </li>
          <li class="nav-item" routerLink="system" routerLinkActive="active">
            <span class="nav-icon">🔧</span> <span class="nav-text">Système</span>
          </li>
          <li class="nav-item" routerLink="logs" routerLinkActive="active">
            <span class="nav-icon">📝</span> <span class="nav-text">Logs</span>
          </li>
          <li class="nav-item" routerLink="reports" routerLinkActive="active">
            <span class="nav-icon">📊</span> <span class="nav-text">Rapports</span>
          </li>
          <li class="nav-item" routerLink="maintenance" routerLinkActive="active">
            <span class="nav-icon">🔧</span> <span class="nav-text">Maintenance</span>
          </li>
        </ul>

        <div class="sidebar-bottom">
          <ul class="nav-list">
            <li class="nav-item" routerLink="settings" routerLinkActive="active">
              <span class="nav-icon">⚙️</span> <span class="nav-text">Paramètres</span>
            </li>
            <li class="nav-item" (click)="logout()">
              <span class="nav-icon">🚪</span> <span class="nav-text">Déconnexion</span>
            </li>
          </ul>

          <div class="sidebar-collapse-toggle">
            <button class="collapse-btn" (click)="toggleCollapse()">
              <svg class="collapse-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M15 19L8 12L15 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <span class="nav-text">Réduire</span>
            </button>
          </div>
        </div>
      </aside>

      <!-- Main Content Outlet -->
      <main class="main-content">
        <router-outlet></router-outlet>
      </main>
    </div>
  `,
  styles: `
    .admin-layout {
      display: flex;
      height: 100vh;
      background-color: var(--dxc-white);
    }

    .sidebar {
      width: 280px;
      background-color: var(--dxc-dark-gray);
      color: var(--dxc-white);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      padding: 24px;
      position: relative;
      transition: width 0.3s ease, padding 0.3s ease;
      box-shadow: 2px 0 10px rgba(0, 0, 0, 0.1);
    }

    .sidebar.collapsed {
      width: 88px;
      padding: 24px 12px;
    }

    .sidebar.collapsed .nav-text {
      display: none;
    }

    .sidebar.collapsed .brand {
      justify-content: center;
    }

    .sidebar.collapsed .nav-item {
      justify-content: center;
    }

    .sidebar.collapsed .collapse-icon {
      transform: rotate(180deg);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      padding-bottom: 20px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
      margin-bottom: 20px;
    }

    .brand-logo {
      background: var(--dxc-purple);
      color: var(--dxc-white);
      width: 40px;
      height: 40px;
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: bold;
      font-size: 18px;
      flex-shrink: 0;
    }

    .nav-text {
      white-space: nowrap;
      opacity: 1;
      transition: opacity 0.3s ease;
    }

    .badge-admin {
      background: var(--dxc-danger);
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 10px;
      margin-left: 8px;
    }

    .nav-list {
      list-style: none;
      padding: 0;
      margin: 0;
      flex: 1;
    }

    .nav-item {
      padding: 12px 16px;
      margin-bottom: 4px;
      border-radius: 8px;
      cursor: pointer;
      transition: all 0.3s ease;
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .nav-item:hover {
      background: rgba(255, 255, 255, 0.1);
    }

    .nav-item.active {
      background: var(--dxc-purple);
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    }

    .nav-icon {
      font-size: 18px;
      flex-shrink: 0;
    }

    .sidebar-bottom {
      margin-top: auto;
      padding-top: 20px;
      border-top: 1px solid rgba(255, 255, 255, 0.1);
    }

    .sidebar-collapse-toggle {
      padding-top: 16px;
      border-top: 1px solid rgba(255, 255, 255, 0.1);
      margin-top: 16px;
    }

    .collapse-btn {
      width: 100%;
      padding: 10px;
      background: rgba(255, 255, 255, 0.1);
      border: none;
      border-radius: 8px;
      color: var(--dxc-white);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      transition: all 0.3s ease;
    }

    .collapse-btn:hover {
      background: rgba(255, 255, 255, 0.2);
    }

    .collapse-icon {
      transition: transform 0.3s ease;
    }

    .main-content {
      flex: 1;
      overflow-y: auto;
      background-color: var(--dxc-light-gray);
    }

    @media (max-width: 768px) {
      .sidebar {
        position: fixed;
        left: 0;
        top: 0;
        height: 100vh;
        z-index: 1000;
        transform: translateX(-100%);
      }

      .sidebar.mobile-open {
        transform: translateX(0);
      }

      .sidebar.collapsed {
        width: 280px;
      }

      .main-content {
        margin-left: 0;
      }
    }
  `
})
export class AdminLayoutComponent {
  isCollapsed = false;

  constructor(public router: Router, private route: ActivatedRoute, private api: ApiService) {}

  toggleCollapse(): void {
    this.isCollapsed = !this.isCollapsed;
  }

  openSettings(): void {
    this.router.navigate(['/admin/settings']);
  }

  logout(): void {
    this.api.logout().subscribe({
      next: () => this.router.navigate(['/login']),
      error: () => this.router.navigate(['/login'])
    });
  }
}
