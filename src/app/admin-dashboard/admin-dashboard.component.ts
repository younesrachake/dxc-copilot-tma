import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { CommonModule } from '@angular/common';
import { ApiService } from '../services/api.service';

@Component({
  selector: 'app-admin-dashboard',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './admin-dashboard.component.html',
  styleUrls: ['./admin-dashboard.component.scss']
})
export class AdminDashboardComponent implements OnInit {
  stats = [
    { label: 'Utilisateurs actifs',   value: '—', icon: '👥', accent: 'purple' },
    { label: 'Sessions aujourd\'hui', value: '—', icon: '⚡', accent: 'blue'   },
    { label: 'Messages totaux',       value: '—', icon: '💬', accent: 'green'  },
    { label: 'Incidents détectés',    value: '—', icon: '🔔', accent: 'orange' },
  ];

  recentActivity: { user: string; action: string; time: string }[] = [];
  isLoading = false;
  loadError = false;
  lastUpdated = '';
  skeletonItems = [0, 1, 2, 3];

  readonly quickActions = [
    { icon: '👥', gradient: 'gradient-purple', title: 'Gérer les utilisateurs', desc: 'Ajouter, modifier ou désactiver des comptes', action: () => this.manageUsers() },
    { icon: '📊', gradient: 'gradient-blue',   title: 'Voir les rapports',       desc: 'Statistiques et analyses de performance',   action: () => this.viewReports() },
    { icon: '⚙️', gradient: 'gradient-teal',   title: 'Configuration système',   desc: 'Paramètres globaux de l\'application',      action: () => this.configureSystem() },
    { icon: '🔧', gradient: 'gradient-orange', title: 'Maintenance',             desc: 'Tâches planifiées et santé du système',     action: () => this.performMaintenance() },
  ];

  constructor(private router: Router, private api: ApiService) {}

  ngOnInit(): void {
    this.refreshData();
  }

  refreshData(): void {
    this.isLoading = true;
    this.loadError = false;
    this.api.getDashboardStats().subscribe({
      next: (data) => {
        this.stats = [
          { label: 'Utilisateurs actifs',   value: String(data.total_users),           icon: '👥', accent: 'purple' },
          { label: 'Sessions aujourd\'hui', value: String(data.active_sessions_today), icon: '⚡', accent: 'blue'   },
          { label: 'Messages totaux',       value: String(data.total_messages),         icon: '💬', accent: 'green'  },
          { label: 'Incidents détectés',    value: String(data.total_incidents),        icon: '🔔', accent: 'orange' },
        ];
        this.recentActivity = (data.recent_activity || []).map((a: any) => ({
          user:   a.user,
          action: a.action,
          time:   a.time,
        }));
        this.isLoading = false;
        this.setLastUpdated();
      },
      error: () => {
        this.isLoading = false;
        this.loadError = true;
      }
    });
  }

  timeAgo(isoString: string): string {
    if (!isoString) return '';
    const diff = Date.now() - new Date(isoString).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1)  return 'à l\'instant';
    if (mins < 60) return `il y a ${mins} min`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `il y a ${hours}h`;
    return `il y a ${Math.floor(hours / 24)}j`;
  }

  private setLastUpdated(): void {
    this.lastUpdated = new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  }

  exportData(): void {
    const rows = ['Stat,Valeur', ...this.stats.map(s => `${s.label},${s.value}`)];
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'dashboard-stats.csv';
    a.click();
  }

  manageUsers():        void { this.router.navigate(['/admin/users']); }
  viewReports():        void { this.router.navigate(['/admin/reports']); }
  configureSystem():    void { this.router.navigate(['/admin/system']); }
  performMaintenance(): void { this.router.navigate(['/admin/maintenance']); }
}
