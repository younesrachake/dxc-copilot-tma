import { Component, OnDestroy, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { CommonModule } from '@angular/common';
import { ApiService } from '../services/api.service';
import { IconComponent } from '../shared/icon.component';

@Component({
  selector: 'app-admin-dashboard',
  standalone: true,
  imports: [CommonModule, IconComponent],
  templateUrl: './admin-dashboard.component.html',
  styleUrls: ['./admin-dashboard.component.scss']
})
export class AdminDashboardComponent implements OnInit, OnDestroy {
  stats = [
    { label: 'Utilisateurs actifs',   value: '—', icon: 'users' },
    { label: 'Sessions aujourd\'hui', value: '—', icon: 'zap' },
    { label: 'Messages totaux',       value: '—', icon: 'message-circle' },
    { label: 'Incidents détectés',    value: '—', icon: 'triangle-alert' },
  ];

  recentActivity: { user: string; action: string; time: string }[] = [];
  isLoading = false;
  loadError = false;
  lastUpdated = '';
  skeletonItems = [0, 1, 2, 3];

  readonly quickActions = [
    { icon: 'users',    title: 'Gérer les utilisateurs', desc: 'Ajouter, modifier ou désactiver des comptes', action: () => this.manageUsers() },
    { icon: 'file-text', title: 'Voir les rapports',      desc: 'Statistiques et analyses de performance',    action: () => this.viewReports() },
    { icon: 'settings', title: 'Configuration système',   desc: 'Paramètres globaux de l\'application',       action: () => this.configureSystem() },
    { icon: 'wrench',   title: 'Maintenance',             desc: 'Tâches planifiées et santé du système',      action: () => this.performMaintenance() },
  ];

  // ── Live feed (SSE) + anomaly alerts ────────────────────────
  isLive = false;
  anomalies: any[] = [];
  private eventStream: AbortController | null = null;

  constructor(private router: Router, private api: ApiService) {}

  ngOnInit(): void {
    this.refreshData();
    this.loadAnomalies();
    this.connectLiveFeed();
  }

  ngOnDestroy(): void {
    this.eventStream?.abort();
  }

  private connectLiveFeed(): void {
    this.eventStream = this.api.streamGet('/api/admin/events', (event, data) => {
      if (event !== 'activity') return;
      this.isLive = true;
      if (data.type === 'message') {
        // bump the "Messages totaux" tile and pulse the feed
        const tile = this.stats.find(s => s.icon === 'message-circle');
        if (tile && tile.value !== '—') tile.value = String(Number(tile.value) + 1);
        this.recentActivity = [{
          user: data.sender || 'bot',
          action: 'Nouveau message dans une conversation',
          time: data.at || new Date().toISOString(),
        }, ...this.recentActivity].slice(0, 15);
      } else if (data.type === 'incident') {
        const tile = this.stats.find(s => s.icon === 'triangle-alert');
        if (tile && tile.value !== '—') tile.value = String(Number(tile.value) + 1);
        this.recentActivity = [{
          user: 'bot',
          action: `Incident récurrent détecté (${data.incident_type || 'type inconnu'})`,
          time: data.at || new Date().toISOString(),
        }, ...this.recentActivity].slice(0, 15);
      }
    });
  }

  private loadAnomalies(): void {
    this.api.getAnomalies().subscribe({
      next: (r) => { this.anomalies = r.anomalies || []; },
      error: () => { this.anomalies = []; }
    });
  }

  refreshData(): void {
    this.isLoading = true;
    this.loadError = false;
    this.api.getDashboardStats().subscribe({
      next: (data) => {
        this.stats = [
          { label: 'Utilisateurs actifs',   value: String(data.total_users),           icon: 'users' },
          { label: 'Sessions aujourd\'hui', value: String(data.active_sessions_today), icon: 'zap' },
          { label: 'Messages totaux',       value: String(data.total_messages),        icon: 'message-circle' },
          { label: 'Incidents détectés',    value: String(data.total_incidents),       icon: 'triangle-alert' },
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
